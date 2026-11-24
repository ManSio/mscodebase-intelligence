"""Регрессионный гейт «чужой корпус»: index → health → search → второй index.

Помечен `slow` (в дефолтный прогон не входит): запускать явно
`pytest tests/test_corpus_smoke.py -m slow` или отдельным CI-джобом.

Зачем: три дефекта 2026-11-17 (status=0 при записи, symbols=0 при 49 558
чанках, read-only без issues) всплыли только на реальном корпусе. Этот тест
проходит полный цикл и падает, если любая из этих метрик снова начнёт врать.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


def _write_project(root: Path) -> None:
    (root / "pyproject.toml").write_text("[project]\nname='smoke'\nversion='0.1.0'\n",
                                        encoding="utf-8")
    for i in range(6):
        (root / f"mod_{i}.py").write_text(
            f"def corpus_symbol_{i}(value):\n    return value + {i}\n", encoding="utf-8"
        )


def _text(msg: dict) -> str:
    res = msg.get("result", {})
    return " ".join("".join(b.get("text", "") for b in res.get("content", [])
                            if isinstance(b, dict)).split())


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MSCODEBASE_DENSE_OFF", "true")
    monkeypatch.setenv("LLAMA_CPP_ENABLED", "false")
    monkeypatch.delenv("MSCODEBASE_MCP_PROFILE", raising=False)
    monkeypatch.delenv("MSCODEBASE_MCP_TOOLS", raising=False)

    from src.mcp.server_factory import create_mcp_server

    mcp = create_mcp_server()
    assert mcp is not None
    yield mcp, tmp_path


def _call(mcp, name: str, args: dict) -> str:
    """FastMCP возвращает либо (content, meta), либо dict/str — приводим к тексту."""
    result = asyncio.run(mcp._tool_manager.call_tool(name, args))  # noqa: SLF001
    if isinstance(result, tuple):
        blocks = result[0]
        return "".join(getattr(block, "text", "") for block in blocks)
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)
    return str(result)


def test_real_corpus_index_health_and_search(server, tmp_path):
    mcp, _ = server
    project = tmp_path / "proj"
    project.mkdir()
    _write_project(project)
    root = str(project)

    _call(mcp, "codebase", {"action": "index", "path": "project_dir", "project_root": root})

    health = {}
    for _ in range(30):
        raw = _call(mcp, "get_health_report", {"project_root": root})
        try:
            health = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            health = {}
        metrics = health.get("metrics") or {}
        if metrics.get("total_chunks") and metrics.get("total_symbols"):
            break
        asyncio.run(asyncio.sleep(1))

    metrics = health.get("metrics") or {}
    assert metrics.get("total_chunks", 0) > 0, health
    assert metrics.get("total_symbols", 0) > 0, health
    assert metrics.get("write_capable") is True, health

    found = _call(mcp, "search_code", {"query": "corpus_symbol_3", "project_root": root,
                                       "limit": 3})
    assert "mod_3.py" in found, found
    symbol = _call(mcp, "get_symbol_info", {"query": "corpus_symbol_3", "project_root": root})
    assert "1 defs" in symbol, symbol
