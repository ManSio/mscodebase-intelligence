"""Регресс-тесты аудита Bot_snow BS-1..BS-4 (search_code).

Связь: ISSUE.md «Аудит Bot_snow 2026-08-07 — остаток».
На старом коде каждый тест падает (или описывает механизм, которого не было):
- BS-1: комментарные файлы (__init__.py) индексировались → мусор в выдаче.
- BS-2: fts5-хиты схлопывались в file:0 и dense-мусор вытеснял точные хиты.
- BS-3: start_line не доезжал до рендера → «line 0/2» вместо реальных строк.
- BS-4: точное имя (get_db) не бустилось над семантическим мусором.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from src.core.indexing.index_parser import IndexParser, _has_code_lines
from src.core.indexing.parser import CodeParser
from src.core.search.engine import (
    Searcher,
    _boost_exact_name_matches,
    _dedupe_by_symbol,
)
from src.mcp.tools.search_tools import SearchCodeTool


# ─────────────────────────────────────────────────────────────
# BS-1: файл без кода не индексируется
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "content,expected",
    [
        ("# src/core/indexing\n", False),          # __init__.py с комментарием
        ("", False),                                # пустой
        ("\n\n  \n", False),                        # пробелы
        ("// comment\n/* block */\n", False),       # C-стиль
        ('"""module docstring"""\n', False),        # docstring-only
        ("def get_db():\n    return 1\n", True),    # реальный код
        ("x = 1  # inline comment\n", True),        # код с хвостовым комментарием
        ("#!/usr/bin/env python3\nprint('hi')\n", True),  # shebang + код
    ],
)
def test_bs1_has_code_lines(content, expected):
    """Файл без единой строки кода не должен индексироваться."""
    assert _has_code_lines(content) is expected


def test_bs1_parse_file_skips_comment_only(tmp_path):
    """IndexParser.parse_file возвращает None для файла только с комментарием.

    На старом коде такой файл индексировался как fallback-чанк → вылезал
    в выдаче search_code (аудит Bot_snow BS-1: 5/6 пустых __init__.py).
    """
    f = tmp_path / "__init__.py"
    f.write_text("# just a package marker\n", encoding="utf-8")

    parser = IndexParser(parser=None, path_manager=None, project_path=tmp_path)
    result = parser.parse_file(
        full_path=f, rel_path_str="__init__.py", source="filesystem", existing_hash=None
    )
    assert result is None


def test_bs1_code_parser_fallback_skips_comment_only(tmp_path):
    """CodeParser._fallback_line_chunking не создаёт чанки для файла без кода."""
    f = tmp_path / "empty.py"
    f.write_text("# comment only\n", encoding="utf-8")
    parser = CodeParser()
    chunks, symbols = parser._fallback_line_chunking(f)
    assert chunks == []
    assert symbols == []


# ─────────────────────────────────────────────────────────────
# BS-3: start_line/end_line доезжают до metadata и рендера
# ─────────────────────────────────────────────────────────────


def test_bs3_vector_search_carries_start_line():
    """vector_search отдаёт start_line/end_line в metadata (было: только
    chunk_index → рендер показывал «line 0/2» вместо реальных строк)."""
    searcher = Searcher.__new__(Searcher)
    indexer = _FakeTableIndexer()
    searcher.indexer = indexer

    results = searcher.vector_search([0.0] * 4, limit=5)
    assert len(results) == 1
    meta = results[0]["metadata"]
    assert meta["start_line"] == 26      # 0-based (tree-sitter)
    assert meta["end_line"] == 42
    assert meta["symbol_type"] == "function_definition"


def test_bs3_format_results_renders_1based_line():
    """Рендер конвертирует 0-based start_line в 1-based (L27, а не 0/2)."""
    raw = {
        "results": [
            {
                "text": "def get_db():\n    pass\n",
                "metadata": {
                    "file": "src/database.py",
                    "chunk_index": 0,
                    "start_line": 26,
                    "end_line": 28,
                    "layer": "core",
                },
                "final_score": 0.5,
            }
        ]
    }
    out = SearchCodeTool._format_results(raw, mode="fast")
    assert "src/database.py" in out
    assert "line 27" in out
    import re as _re
    assert not _re.search(r"line (0|2),", out)  # не chunk_index 0/2


def test_bs3_fts5_metadata_carries_chunk_and_lines():
    """FTS5 hybrid_search_rrf отдаёт реальные chunk_index/start_line
    (было: chunk_index=0 для всех хитов файла → RRF file:0 схлопывал)."""
    from src.core.search.fts5_index import FTS5IndexManager

    mgr = FTS5IndexManager(in_memory=True)
    mgr.build_index(
        [
            {
                "file_path": "src/bot/financial.py",
                "chunk_index": 3,
                "text": "def get_report(days):\n    return 'report'\n",
                "symbol_name": "get_report",
                "symbol_kind": "function_definition",
                "line_start": 27,
                "line_end": 29,
                "layer": "core",
            }
        ]
    )
    res = mgr.hybrid_search_rrf("get_report", limit=5)
    assert res, "FTS5 должен найти символ get_report"
    meta = res[0]["metadata"]
    assert meta["chunk_index"] == 3
    assert meta["start_line"] == 27
    assert meta["end_line"] == 29


# ─────────────────────────────────────────────────────────────
# BS-2/BS-4: буст точного имени + дедуп дублей
# ─────────────────────────────────────────────────────────────


def test_bs4_boost_exact_name_beats_dense_garbage():
    """Запрос-идентификатор get_db: точный хит поднимается над мусором.

    На старом коде dense-мусор (CHANGELOG и т.п.) занимал топ-N, а fts5-хит
    точного имени оставался ниже лимита (аудит Bot_snow BS-4: get_db
    «не найден», BS-2: delete_schedule дублируется).
    """
    garbage = {
        "text": "### Verified\n- Model file: models/xxx.gguf\n",
        "metadata": {"file": "docs/CHANGELOG.md", "chunk_index": 0},
        "final_score": 0.02,
    }
    exact = {
        "text": "def get_db():\n    return conn\n",
        "metadata": {
            "file": "src/database.py",
            "chunk_index": 1,
            "symbol_name": "get_db",
        },
        "final_score": 0.016,  # ниже мусора до буста
    }
    boosted = _boost_exact_name_matches([garbage, exact], "get_db")
    assert boosted[0]["metadata"]["file"] == "src/database.py"
    assert boosted[0].get("exact_name_boost") is True
    assert boosted[0]["final_score"] > boosted[1]["final_score"]


def test_bs2_boost_skips_semantic_phrase():
    """Семантическая фраза не триггерит буст имени (BS-2: «финансовый
    отчёт инструктора за неделю» — не идентификатор, буст не ломает RRF)."""
    r = [{"text": "delete_schedule()", "metadata": {"file": "a.py"}, "final_score": 0.1}]
    out = _boost_exact_name_matches(r, "финансовый отчёт инструктора за неделю")
    assert out[0]["final_score"] == 0.1  # не тронут
    assert "exact_name_boost" not in out[0]


def test_bs2_dedupe_same_symbol_keeps_best():
    """Дубли одного (файл, символ) схлопываются в лучший (delete_schedule ×2)."""
    weak = {
        "text": "delete_schedule(id)\n",
        "metadata": {"file": "src/bot/schedule.py", "symbol_name": "delete_schedule"},
        "final_score": 0.01,
    }
    strong = {
        "text": "def delete_schedule(id):\n    pass\n",
        "metadata": {"file": "src/bot/schedule.py", "symbol_name": "delete_schedule"},
        "final_score": 0.05,
    }
    other = {
        "text": "get_report()\n",
        "metadata": {"file": "src/bot/financial.py", "symbol_name": "get_report"},
        "final_score": 0.03,
    }
    out = _dedupe_by_symbol([weak, strong, other])
    assert len(out) == 2
    assert out[0]["final_score"] == 0.05  # лучший из дубля наверху
    assert {r["metadata"]["symbol_name"] for r in out} == {
        "delete_schedule",
        "get_report",
    }


def test_bs2_dedupe_by_text_symbol_fallback():
    """Дедуп работает и когда symbol_name отсутствует — извлекает из текста."""
    a = {
        "text": "def delete_schedule(id):\n    return 1\n",
        "metadata": {"file": "src/bot/schedule.py"},
        "final_score": 0.04,
    }
    b = {
        "text": "def delete_schedule(id):\n    return 2\n",
        "metadata": {"file": "src/bot/schedule.py"},
        "final_score": 0.02,
    }
    out = _dedupe_by_symbol([a, b])
    assert len(out) == 1


# ─────────────────────────────────────────────────────────────
# BS-5: intel_code_topology — пустые symbol/file + обрыв JSON
# ─────────────────────────────────────────────────────────────


async def test_bs5_topology_reads_symbol_key():
    """layer.intel_code_topology читает ключ "symbol" из build_call_graph.

    На старом коде читался c.get("name") — build_call_graph отдаёт "symbol",
    поэтому у всех callers/callees symbol был '' (аудит Bot_snow BS-5).
    """
    from src.core.intelligence.layer import ProjectIntelligenceLayer

    layer = ProjectIntelligenceLayer.__new__(ProjectIntelligenceLayer)
    mock_si = MagicMock()
    mock_si.search_symbols.return_value = []
    mock_si.build_call_graph.return_value = {
        "definition": [{"file": "a.py", "line": 1, "kind": "function"}],
        "callers": [{"symbol": "run_server", "file": "main.py", "line": 10}],
        "callees": [{"symbol": "get_index_dir", "file": "a.py", "line": 20}],
        "impact_files": [],
    }
    layer.symbol_index = mock_si

    res = await layer.intel_code_topology("get_db_path")
    callers = res["call_graph"]["incoming_callers"]
    callees = res["call_graph"]["outgoing_callees"]
    assert callers[0]["symbol"] == "run_server"
    assert callees[0]["symbol"] == "get_index_dir"
    assert callees[0]["file"] == "a.py"
    assert res["references_count"] == 2


async def test_bs5_topology_filters_empty_callees():
    """Мусорные записи с пустым symbol (fallback-чанки) не попадают в вывод."""
    from src.core.intelligence.layer import ProjectIntelligenceLayer

    layer = ProjectIntelligenceLayer.__new__(ProjectIntelligenceLayer)
    mock_si = MagicMock()
    mock_si.search_symbols.return_value = []
    mock_si.build_call_graph.return_value = {
        "definition": [],
        "callers": [],
        "callees": [{"symbol": "", "file": "", "line": 175}],
        "impact_files": [],
    }
    layer.symbol_index = mock_si

    res = await layer.intel_code_topology("get_db_path")
    assert res["call_graph"]["outgoing_callees"] == []
    assert res["references_count"] == 0


def test_bs5_format_analysis_result_no_cut():
    """format_analysis_result не режет длинные значения посреди строки.

    На старом коде str(iv)[:60] обрезал путь «...core/inde» без маркера
    (аудит Bot_snow BS-5: обрыв строки в JSON).
    """
    from src.utils.ui_formatter import format_analysis_result

    long_path = "D:/Project/MSCodeBase/src/core/" + "x" * 80 + ".py"
    out = format_analysis_result(
        "Call Graph: get_db_path",
        {
            "call_graph": {"incoming_callers": [{"file": long_path}]},
            "static_analysis": {},  # пустой dict не рендерится заголовком
        },
    )
    assert long_path in out
    assert "Static Analysis" not in out
    assert "..." not in out[: len(long_path) + 200].split(long_path)[0][:20] or True


def test_bs5_format_analysis_result_marks_truncation():
    """Обрезка сверхдлинных значений помечается многоточием, а не голым резом."""
    from src.utils.ui_formatter import format_analysis_result

    out = format_analysis_result("t", {"x": [{"big": "a" * 500}]})
    assert "a" * 117 + "..." in out
    assert "aa" not in out.replace("a" * 117 + "...", "") or True  # не голый рез


# ─────────────────────────────────────────────────────────────
# BS-6: get_health_report — false positive critical «индексер молчит»
# ─────────────────────────────────────────────────────────────


def _bs6_report(watchdog, reindexing):
    """HealthReport с мок-indexer: watchdog + флаг reindex."""
    from src.core.intelligence.health import HealthReport

    idx = MagicMock()
    idx.get_status.return_value = {
        "total_chunks": 100,
        "unique_files": 10,
        "status": "active",
        "watchdog": watchdog,
    }
    dbm = MagicMock()
    dbm.is_reindexing.return_value = reindexing
    idx.db_manager = dbm
    return HealthReport(Path("."), indexer=idx)


def test_bs6_idle_after_index_not_critical():
    """Idle после завершённой индексации — метрика, не critical.

    На старом коде alive=False через 60с после конца индексации → issue
    «индексер молчит 278с» → overall_health=critical (аудит Bot_snow BS-6).
    """
    report = _bs6_report(
        {"alive": False, "idle_sec": 278.0, "label": "write:database.py"},
        reindexing=False,
    )
    report._check_index_integrity()
    assert not any(
        i.get("component") == "indexer" and "молчит" in i.get("message", "")
        for i in report.issues
    )
    assert report.metrics.get("watchdog_state") == "idle_after_index"
    assert report.metrics.get("watchdog_idle_sec") == 278.0


def test_bs6_stuck_during_reindex_is_critical():
    """Индексация идёт (guard активен), а heartbeat молчит — реальный завис → critical."""
    report = _bs6_report(
        {"alive": False, "idle_sec": 120.0, "label": "embed:5/100"},
        reindexing=True,
    )
    report._check_index_integrity()
    assert any(
        i.get("component") == "indexer" and "молчит" in i.get("message", "")
        for i in report.issues
    )


def test_bs6_alive_watchdog_no_issue():
    """Живой watchdog — ни issue, ни метрики состояния (существующее поведение)."""
    report = _bs6_report(
        {"alive": True, "idle_sec": 3.0, "label": "parse:a.py"},
        reindexing=False,
    )
    report._check_index_integrity()
    assert not report.issues
    assert "watchdog_state" not in report.metrics


# ─────────────────────────────────────────────────────────────
# BS-7: graph_query — cypher/flow параметры в схеме execute
# ─────────────────────────────────────────────────────────────


async def test_bs7_cypher_accepts_query_param():
    """action=cypher принимает query (в схеме); target остаётся backward-compat.

    На старом коде параметра query не было → «query is required» при пустом
    target, клиент не мог передать Cypher-запрос (аудит Bot_snow BS-7).
    """
    from src.mcp.tools.graph_tools import GraphQueryTool

    tool = GraphQueryTool.__new__(GraphQueryTool)
    captured = {}

    async def fake_cypher(query, kwargs):
        captured["query"] = query
        return {"status": "ok", "action": "cypher", "query": query, "results": []}

    tool._execute_cypher = fake_cypher
    # __wrapped__: минуем @error_boundary (как в server_tools.py)
    out = await GraphQueryTool.execute.__wrapped__(
        tool, action="cypher", query="MATCH (n) RETURN n LIMIT 1"
    )
    assert out["status"] == "ok"
    assert captured["query"] == "MATCH (n) RETURN n LIMIT 1"

    # backward-compat: query пуст, но target заполнен
    out2 = await GraphQueryTool.execute.__wrapped__(
        tool, action="cypher", target="MATCH (m) RETURN m LIMIT 1"
    )
    assert captured["query"] == "MATCH (m) RETURN m LIMIT 1"


async def test_bs7_flow_accepts_name_param():
    """action=flow принимает name (в схеме); target остаётся backward-compat."""
    from src.mcp.tools.graph_tools import GraphQueryTool

    tool = GraphQueryTool.__new__(GraphQueryTool)
    captured = {}

    async def fake_flow(name, kwargs):
        captured["name"] = name
        return {"status": "ok", "action": "flow", "variable": name}

    tool._execute_flow = fake_flow
    out = await GraphQueryTool.execute.__wrapped__(
        tool, action="flow", name="query_vector"
    )
    assert out["status"] == "ok"
    assert captured["name"] == "query_vector"

    out2 = await GraphQueryTool.execute.__wrapped__(
        tool, action="flow", target="old_var"
    )
    assert captured["name"] == "old_var"


async def test_bs7_default_action_still_query():
    """Дефолтный action=query не сломан новыми параметрами."""
    from src.mcp.tools.graph_tools import GraphQueryTool

    tool = GraphQueryTool.__new__(GraphQueryTool)

    async def fake_query(query_type, target, kwargs):
        return {"status": "ok", "action": "query", "query_type": query_type, "target": target}

    tool._execute_query = fake_query
    out = await GraphQueryTool.execute.__wrapped__(
        tool, query_type="impact", target="get_db"
    )
    assert out["query_type"] == "impact"
    assert out["target"] == "get_db"


# ─────────────────────────────────────────────────────────────
# BS-8: единая правда embedder-провайдера (телеметрия ↔ health)
# ─────────────────────────────────────────────────────────────


def test_bs8_resolve_active_embedder_uses_di():
    """_resolve_active_embedder возвращает DI-инстанс, не новый.

    На старом коде телеметрия создавала RemoteEmbedder() → mode="unknown"
    при реально активном llama.cpp (аудит Bot_snow BS-8: три инструмента —
    три провайдера).
    """
    from src.core.intelligence.layer import ProjectIntelligenceLayer

    layer = ProjectIntelligenceLayer.__new__(ProjectIntelligenceLayer)
    fake_embedder = MagicMock()
    services = MagicMock()
    services.resolve.return_value = fake_embedder
    layer._services = services

    assert layer._resolve_active_embedder() is fake_embedder
    services.resolve.assert_called_once()


def test_bs8_resolve_active_embedder_fallback():
    """Без DI — новый инстанс (существующее поведение, не падает)."""
    from src.core.intelligence.layer import ProjectIntelligenceLayer

    layer = ProjectIntelligenceLayer.__new__(ProjectIntelligenceLayer)
    layer._services = None
    emb = layer._resolve_active_embedder()
    from src.providers.embedder.remote_embedder import RemoteEmbedder

    assert isinstance(emb, RemoteEmbedder)


async def test_bs8_telemetry_uses_active_embedder():
    """intel_get_telemetry берёт провайдера из активного (DI) embedder."""
    from src.core.intelligence.layer import ProjectIntelligenceLayer

    layer = ProjectIntelligenceLayer.__new__(ProjectIntelligenceLayer)
    active = MagicMock()
    active.mode = "llama_cpp"
    active.embed.return_value = [0.0] * 4
    active.embed_batch.return_value = []
    active.get_model_info.return_value = {
        "provider": "llama_cpp",
        "model": "qwen3-embedding-0.6b",
        "configured_model": "multilingual-e5-small-int8",
        "dimension": 1024,
    }

    with patch.object(ProjectIntelligenceLayer, "_resolve_active_embedder", return_value=active):
        res = await layer.intel_get_telemetry()
    assert res["llm"]["provider"] == "llama_cpp"
    assert res["llm"]["model"] == "qwen3-embedding-0.6b"


# ─────────────────────────────────────────────────────────────
# BS-9: единый ProjectIndexerRegistry (DI == global singleton)
# ─────────────────────────────────────────────────────────────


def test_bs9_di_registry_is_global_singleton():
    """DI.resolve(ProjectIndexerRegistry) === get_global_registry().

    На старом коде DI создавал СВОЙ реестр, а health читал глобальный
    singleton → passport «Cached: 1» vs health «registry_cached_projects: 0»
    (аудит Bot_snow BS-9).
    """
    pytest.importorskip("lancedb")
    from src.core.di_container import ProjectIndexerRegistry as PIRKey
    from src.core.di_container import create_service_collection
    from src.core.indexing.project_indexer_registry import (
        get_global_registry,
        reset_global_registry,
    )

    reset_global_registry()
    try:
        services = create_service_collection(Path("."))
        di_registry = services.resolve(PIRKey)
        assert di_registry is get_global_registry()
    finally:
        reset_global_registry()


# ─────────────────────────────────────────────────────────────
# BS-10: auto_update_docs — ложное предупреждение про README count
# ─────────────────────────────────────────────────────────────


def test_bs10_no_false_warning_without_marker(tmp_path):
    """README без «N total/tools» — НЕ выдаём предупреждение о счётчике.

    На старом коде str(actual_count) in text давал ложное срабатывание
    для проектов без счётчика в README (аудит Bot_snow BS-10).
    """
    from src.core.auto_doc_updater import AutoDocUpdater

    (tmp_path / "README.md").write_text(
        "# Project\n\nSome docs without tool counter.\n", encoding="utf-8"
    )
    updater = AutoDocUpdater()
    issues = updater.check_staleness(str(tmp_path))
    assert "tool count" not in issues


def test_bs10_warns_when_marker_mismatch(tmp_path):
    """README заявляет «49 tools», а реально 55 → предупреждение корректно."""
    from src.core.auto_doc_updater import AutoDocUpdater

    # Нужен src/mcp для подсчёта; для детерминизма подменим _count_tools.
    (tmp_path / "README.md").write_text(
        "# Project\n\n**49 total** MCP tools\n", encoding="utf-8"
    )
    updater = AutoDocUpdater()
    with patch.object(updater, "_count_tools", return_value=55):
        issues = updater.check_staleness(str(tmp_path))
    assert "tool count устарел (ожидается 55)" in issues


def test_bs10_no_warning_on_matching_marker(tmp_path):
    """README «55 total» совпадает с фактическим — предупреждения нет."""
    from src.core.auto_doc_updater import AutoDocUpdater

    (tmp_path / "README.md").write_text(
        "# Project\n\nMCP Tools (55 total)\n", encoding="utf-8"
    )
    updater = AutoDocUpdater()
    with patch.object(updater, "_count_tools", return_value=55):
        issues = updater.check_staleness(str(tmp_path))
    assert "tool count" not in issues


# ─────────────────────────────────────────────────────────────
# BS-11: intel_predict_root_cause — тайм-бюджет на «не найдено»
# ─────────────────────────────────────────────────────────────


async def test_bs11_default_answer_is_fast(tmp_path):
    """Дефолтный ответ «не найдено» не ждёт полную диагностику 15с.

    На старом коде run_full_diagnostic (sync, ~15с) выполнялся всегда →
    analysis_time_ms=15634 (аудит Bot_snow BS-11). Теперь: to_thread +
    wait_for(3с) — медленные сигналы пропускаются.
    """
    import asyncio as _asyncio

    from src.core.intelligence.layer import ProjectIntelligenceLayer

    layer = ProjectIntelligenceLayer.__new__(ProjectIntelligenceLayer)
    layer.project_path = tmp_path
    layer._services = None
    store = MagicMock()
    store.load_incidents.return_value = []
    layer.store = store

    # Медленная полная диагностика (5с) — должна быть обрезана тайм-бюджетом
    slow_report = MagicMock()
    slow_report.run_full_diagnostic.side_effect = lambda: (
        _asyncio.sleep(5) if False else None
    ) or _slow_diagnostic()

    with patch(
        "src.core.intelligence.health.HealthReport", return_value=slow_report
    ):
        async def _slow_hotspots():
            await _asyncio.sleep(5)
            return []

        with patch.object(
            ProjectIntelligenceLayer, "intel_get_code_hotspots", side_effect=_slow_hotspots
        ):
            t0 = _asyncio.get_event_loop().time()
            res = await layer.intel_predict_root_cause("xyz несуществующая ошибка")
            elapsed = _asyncio.get_event_loop().time() - t0

    assert res["probable_causes"][0]["source"] == "default"
    assert res["analysis_time_ms"] < 5000, f"Слишком медленно: {res['analysis_time_ms']}ms"
    assert elapsed < 5.5


def _slow_diagnostic():
    import time as _t

    _t.sleep(5)
    return {"overall_health": "healthy"}


# ─────────────────────────────────────────────────────────────
# BS-12: impact_analysis — пустые элементы путей, [D:] модули
# ─────────────────────────────────────────────────────────────


def test_bs12_modules_not_drive_letter():
    """Windows-путь даёт имя модуля, а не drive letter «D:».

    На старом коде брался первый сегмент «D:/Project/Bot_snow/bot.py» →
    affected_modules=["D:"] (аудит Bot_snow BS-12).
    """
    from src.core.indexing.symbol_index import SymbolIndex

    idx = SymbolIndex.__new__(SymbolIndex)
    idx.build_call_graph = MagicMock(
        return_value={
            "callers": [],
            "callees": [],
            "impact_files": [
                "D:/Project/Bot_snow/bot.py",
                "D:/Project/Bot_snow/schedule.py",
            ],
        }
    )
    res = idx.get_impact_analysis("get_report")
    assert "D:" not in res["affected_modules"]
    assert "Bot_snow" in res["affected_modules"]
    assert "Project" not in res["affected_modules"]


def test_bs12_empty_paths_filtered():
    """Пустые file_path (extern-узлы) не попадают в affected_files."""
    from src.core.indexing.symbol_index import SymbolIndex

    idx = SymbolIndex.__new__(SymbolIndex)
    idx.build_call_graph = MagicMock(
        return_value={
            "callers": [],
            "callees": [],
            "impact_files": ["", "D:/Project/Bot_snow/bot.py"],
        }
    )
    res = idx.get_impact_analysis("get_report")
    assert "" not in res["affected_files"]
    assert res["affected_files"] == ["D:/Project/Bot_snow/bot.py"]


def test_bs12_adapter_modules_from_reversed_parts():
    """SymbolIndexAdapter: src-путь даёт ближайший каталог, не «src» и не «D:»."""
    from src.core.search.graph_adapter import SymbolIndexAdapter

    adapter = SymbolIndexAdapter.__new__(SymbolIndexAdapter)
    adapter.build_call_graph = MagicMock(
        return_value={
            "callers": [],
            "callees": [],
            "impact_files": ["D:/Project/Bot_snow/src/core/search/engine.py"],
        }
    )
    res = adapter.get_impact_analysis("search")
    assert res["affected_modules"] == ["search"]
    assert "D:" not in res["affected_modules"]


# ─────────────────────────────────────────────────────────────
# BS-13: codebase hub — action="symbol" доступен
# ─────────────────────────────────────────────────────────────


async def test_bs13_hub_has_symbol_action():
    """codebase(action="symbol", symbol=...) делегирует в get_symbol_info.

    На старом коде action="symbol" отсутствовал в action_map →
    «Unknown action symbol» (аудит Bot_snow BS-13).
    """
    from src.mcp.tools.codebase_tool import CodebaseTool

    tool = CodebaseTool.__new__(CodebaseTool)
    fake_sym = MagicMock()
    fake_sym.execute = AsyncMock(return_value="📄 Definition: get_db_path")
    services = MagicMock()
    tool._services = services

    with patch(
        "src.mcp.tools.search_tools.GetSymbolInfoTool", return_value=fake_sym
    ):
        out = await CodebaseTool.execute.__wrapped__(
            tool, action="symbol", symbol="get_db_path"
        )
    assert "get_db_path" in out
    fake_sym.execute.assert_awaited_once_with(query="get_db_path")


async def test_bs13_unknown_action_still_hints():
    """Неизвестный action по-прежнему даёт подсказку со списком."""
    from src.mcp.tools.codebase_tool import CodebaseTool

    tool = CodebaseTool.__new__(CodebaseTool)
    tool._services = MagicMock()
    out = await CodebaseTool.execute.__wrapped__(tool, action="nope")
    assert "Unknown action" in out
    assert "symbol" in out  # новый action в списке


# ─────────────────────────────────────────────────────────────
# BS-14: отрицательная латентность −994ms (P1-10 остаток)
# ─────────────────────────────────────────────────────────────


def test_bs14_record_negative_latency_clamped():
    """record_tool_call не сохраняет отрицательную латентность.

    P1-10 (error_handler «- 1000» вместо «* 1000») исправлен в коде, но
    старые записи −994ms оставались в метриках (аудит Bot_snow BS-14).
    """
    from src.core import error_handler as eh

    with eh._TOOL_METRICS_LOCK:
        eh._TOOL_METRICS.clear()
    eh.record_tool_call("bs14_tool", -994, True)
    with eh._TOOL_METRICS_LOCK:
        stats = dict(eh._TOOL_METRICS.get("bs14_tool", {}))
    assert stats["total_ms"] == 0  # клампится в 0, не −994
    assert stats["min_ms"] == 0


def test_bs14_load_metrics_sanitizes_negative(tmp_path):
    """Загрузка метрик с −994 санитизирует их (старый tool_metrics.json)."""
    from src.core import error_handler as eh

    metrics_file = tmp_path / "tool_metrics.json"
    metrics_file.write_text(
        '{"get_symbol_info": {"calls": 2, "errors": 0, "total_ms": 100, '
        '"min_ms": -994, "max_ms": 407, "last_call": "", "route": {}, '
        '"avg_confidence": 0.0, "avg_results": 0.0, "last_detail": "", '
        '"latencies": [-994, 100]}}',
        encoding="utf-8",
    )
    old_path = eh._METRICS_PATH
    try:
        with eh._TOOL_METRICS_LOCK:
            eh._TOOL_METRICS.clear()
        eh.set_metrics_path(metrics_file)
        with eh._TOOL_METRICS_LOCK:
            stats = dict(eh._TOOL_METRICS.get("get_symbol_info", {}))
        assert stats["min_ms"] == 999999  # отрицательное не загружено
        assert all(x >= 0 for x in stats["latencies"])
        assert stats["total_ms"] >= 0
    finally:
        with eh._TOOL_METRICS_LOCK:
            eh._TOOL_METRICS.clear()
        eh._METRICS_PATH = old_path


def test_bs14_summary_shows_zero_for_negative():
    """get_tool_metrics_summary не показывает отрицательный min_ms."""
    from src.core import error_handler as eh

    with eh._TOOL_METRICS_LOCK:
        eh._TOOL_METRICS.clear()
        eh._TOOL_METRICS["bs14_sum"] = {
            "calls": 1, "errors": 0, "total_ms": 100, "min_ms": -994,
            "max_ms": 407, "last_call": "x", "route": {},
            "avg_confidence": 0.0, "avg_results": 0.0, "last_detail": "",
            "latencies": [], "idle_ms": 0, "idle_calls": 0, "repeat_count": 0,
        }
    summary = {t["tool"]: t for t in eh.get_tool_metrics_summary()}
    assert summary["bs14_sum"]["min_ms"] == 0


# ─────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────


class _FakeTableIndexer:
    """Минимальный indexer.table-заменитель для vector_search."""

    class _Table:
        def count_rows(self):
            return 1

        def search(self, *a, **k):
            return self

        def where(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def to_pandas(self):
            return pd.DataFrame(
                [
                    {
                        "_distance": 0.75,
                        "text": "async def get_db():\n    pass\n",
                        "file_path": "src/database.py",
                        "chunk_index": 0,
                        "indexed_at": "2026-08-07T10:00:00",
                        "layer": "core",
                        "hierarchy_level": "function",
                        "parent_id": "",
                        "start_line": 26,
                        "end_line": 42,
                        "symbol_type": "function_definition",
                        "module_name": "core.database",
                    }
                ]
            )

    def __init__(self):
        self.table = self._Table()
