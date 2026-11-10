"""Guards for the MCP live-audit fixes (2026-11-09).

Every test here pins a defect found by real calls against the running server:
project switching, readiness waiting, cross-project reads, Russian docs routing,
test/doc ranking and the CRLF temp-shadow leak.
"""

import asyncio
import inspect
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.indexing.index_parser import IndexParser
from src.core.indexing.parser import CodeParser
from src.core.runtime_coordinator import RuntimeCoordinator
from src.core.search.engine import Searcher
from src.mcp.tools.codebase_tool import CodebaseTool
from src.mcp.tools.graph_tools import GraphQueryTool
from src.mcp.tools.grep_tool import GrepCodeTool
from src.mcp.tools.indexing_tools import NotifyChangeTool, SetProjectTool
from src.mcp.tools.investigate_tool import (
    InvestigateTool,
    _bucket_penalty,
    _merge,
)
from src.mcp.tools.predict_tools import PredictChangeTool
from src.mcp.tools.search_tools import (
    GetSymbolInfoTool,
    ImpactAnalysisTool,
    SearchCodeTool,
)
from src.mcp.tools.system_tools import (
    GetHealthReportTool,
    GetIndexStatusTool,
    ReadLiveFileTool,
)
from src.mcp.tools.write_tools import WriteTool
from src.sources.local_fs.windows import SafePathManager


class _DummyServices:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def resolve(self, key):
        return self.mapping[key]


@pytest.fixture
def preserve_project_env():
    keys = ("MSCODEBASE_PROJECT_PATH", "PROJECT_PATH")
    saved = {k: os.environ.get(k) for k in keys}
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    from src.core.project_resolution import reset_project_root_cache

    reset_project_root_cache()


def test_set_project_actually_changes_resolution(tmp_path, preserve_project_env):
    from src.core.project_resolution import resolve_project_root

    os.environ.pop("MSCODEBASE_PROJECT_PATH", None)
    os.environ.pop("PROJECT_PATH", None)
    target = tmp_path / "other-project"
    target.mkdir()

    tool = SetProjectTool(_DummyServices())
    answer = asyncio.run(tool.execute(project_root=str(target)))

    assert "switched" in answer.lower()
    # The regression: the tool returned success while CWD kept winning.
    assert resolve_project_root() == target.resolve()
    assert Path(os.environ["MSCODEBASE_PROJECT_PATH"]) == target.resolve()


def _coordinator(registry, factory):
    from src.core.di_container import IndexerFactoryKey, ProjectIndexerRegistry

    services = _DummyServices(
        {ProjectIndexerRegistry: registry, IndexerFactoryKey: factory}
    )
    return RuntimeCoordinator(services)


def test_can_execute_initializes_uninitialized_project_without_5s_wait(tmp_path):
    from src.core.indexing.project_indexer_registry import ProjectState

    target = tmp_path / "proj"
    target.mkdir()
    seen = {"state": ProjectState.UNINITIALIZED}

    class Registry:
        def get_state(self, path):
            return seen["state"]

        def get_indexer(self, path, factory=None):
            seen["state"] = ProjectState.READY
            return object()

    def factory(path):
        return object()

    started = time.perf_counter()
    verdict = asyncio.run(
        _coordinator(Registry(), factory).can_execute(target, timeout=5.0)
    )
    elapsed = time.perf_counter() - started

    assert verdict.ok is True
    assert elapsed < 1.0, f"readiness still slept: {elapsed:.2f}s"


def test_can_execute_fails_fast_when_project_cannot_be_opened(tmp_path):
    target = tmp_path / "broken"
    target.mkdir()

    class Registry:
        def get_state(self, path):
            from src.core.indexing.project_indexer_registry import ProjectState

            return ProjectState.UNINITIALIZED

        def get_indexer(self, path, factory=None):
            raise RuntimeError("db is corrupt")

    started = time.perf_counter()
    verdict = asyncio.run(_coordinator(Registry(), lambda p: object()).can_execute(target))
    elapsed = time.perf_counter() - started

    assert verdict.ok is False
    assert "index_project_dir" in verdict.detail
    assert elapsed < 1.0, f"failure still slept: {elapsed:.2f}s"


def test_read_live_file_uses_explicit_project_root(tmp_path):
    active = tmp_path / "active"
    target = tmp_path / "target"
    active.mkdir()
    target.mkdir()
    (active / "same.txt").write_text("ACTIVE\n", encoding="utf-8")
    (target / "same.txt").write_text("TARGET\n", encoding="utf-8")

    tool = ReadLiveFileTool(_DummyServices())

    def fake_resolve(self, explicit_project_root=None):
        root = Path(explicit_project_root) if explicit_project_root else active
        return SimpleNamespace(project_path=root)

    tool.resolve_indexer = fake_resolve.__get__(tool, ReadLiveFileTool)  # type: ignore[method-assign]

    explicit = asyncio.run(
        tool.execute(file_path="same.txt", project_root=str(target))
    )
    implicit = asyncio.run(tool.execute(file_path="same.txt"))

    assert "TARGET" in explicit
    assert "ACTIVE" in implicit


def test_notify_change_root_prefers_explicit_project_root(tmp_path, monkeypatch):
    active = tmp_path / "active"
    target = tmp_path / "target"
    active.mkdir()
    target.mkdir()
    monkeypatch.setattr(
        "src.core.project_resolution.resolve_project_root", lambda *a, **k: active
    )
    tool = NotifyChangeTool.__new__(NotifyChangeTool)

    assert tool._get_project_root(str(target)) == target.resolve()
    assert tool._get_project_root("") == active.resolve()


def test_status_dispatch_passes_project_root(monkeypatch):
    seen = {}

    async def fake_execute(self, project_root="", kwargs=None):
        seen["project_root"] = project_root
        return "ok"

    monkeypatch.setattr(GetIndexStatusTool, "execute", fake_execute)
    tool = CodebaseTool(_DummyServices())

    answer = asyncio.run(
        tool._action_index(
            action="index", path="status", project_root="D:\\other", file_path=""
        )
    )

    assert answer == "ok"
    assert seen["project_root"] == "D:\\other"


def test_bucket_penalty_demotes_tests_and_history_docs():
    assert _bucket_penalty("tests/test_x.py", "where is X defined") < 0
    assert _bucket_penalty("tests/data/cases/x.py", "where is X defined") < 0
    assert _bucket_penalty("docs/archive/old.md", "where is X defined") < 0
    assert _bucket_penalty("docs/en/GUIDE.md", "where is X defined") < 0
    assert _bucket_penalty("AGENT_DIARY.md", "where is X defined") < 0
    assert _bucket_penalty("src/core/x.py", "where is X defined") == 0
    # A question ABOUT tests/docs keeps them at full weight.
    assert _bucket_penalty("tests/test_x.py", "where are the tests for X") == 0
    assert _bucket_penalty("docs/archive/old.md", "readme about X") == 0


def test_merge_prefers_implementation_over_tests_for_code_question():
    items = [
        {"file": "tests/test_x.py", "line": 1, "text": "t", "score": 0.0,
         "weight": 2.5, "channels": {"symbol"}},
        {"file": "src/x.py", "line": 2, "text": "s", "score": 0.0,
         "weight": 2.5, "channels": {"symbol"}},
    ]

    code_first = _merge(items, 5, root=None, query="where is X defined")
    tests_first = _merge(items, 5, root=None, query="where are the tests for X")

    assert code_first[0]["file"] == "src/x.py"
    assert tests_first[0]["file"] == "tests/test_x.py"


class _DocsStore:
    def search(self, query, limit=1000):
        return [
            {"metadata": {"file": "docs/ru/README.md"}, "final_score": 9.0},
            {"metadata": {"file": "src/core/x.py"}, "final_score": 1.0},
        ]


def test_prefers_docs_does_not_route_russian_code_question_to_docs():
    searcher = Searcher.__new__(Searcher)
    searcher._chunk_store = _DocsStore()
    searcher._docs_margin = 0.0

    assert searcher.prefers_docs("где решается включать ли реранк") is False
    assert searcher.prefers_docs("документация по установке") is True
    assert searcher.prefers_docs("where is the rerank flag") is True


def _parser(tmp_path) -> IndexParser:
    cfg = tmp_path / ".mscodebase"
    cfg.mkdir(exist_ok=True)
    return IndexParser(
        parser=CodeParser(),
        path_manager=SafePathManager(cfg),
        project_path=tmp_path,
    )


def test_crlf_only_difference_does_not_create_a_shadow(tmp_path, monkeypatch):
    """The normalized compare must skip the shadow entirely, not merely clean it."""
    import src.core.indexing.index_parser as ip

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    target = tests_dir / "test_sample.py"
    body = "def widget():\n    return 1\n"
    target.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))

    def boom(*args, **kwargs):
        raise AssertionError("a temp shadow was created for a CRLF-only difference")

    monkeypatch.setattr(ip.tempfile, "mkstemp", boom)

    parsed = _parser(tmp_path).parse_file(
        target, "tests/test_sample.py", content=body
    )

    assert parsed is not None
    # AST chunks, not the line fallback: a shadow would raise inside the parse
    # try-block and silently drop to fallback chunks with no symbol_type.
    assert any(
        meta.get("symbol_type") for meta in parsed["chunk_metadatas"]
    ), parsed["chunk_metadatas"]


def test_crlf_file_is_not_parsed_through_a_temp_shadow(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    target = tests_dir / "test_sample.py"
    body = "def widget():\n    return 1\n"
    target.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))

    parsed = _parser(tmp_path).parse_file(
        target,
        "tests/test_sample.py",
        content=body,  # normalized text, exactly what decode_source_bytes yields
    )

    assert parsed is not None
    blob = " ".join(parsed["chunk_texts"] + parsed["chunk_texts_full"])
    # A shadow file is `%TEMP%\tmpXXXX.py`; the real project path may live under
    # Temp too (pytest), so match the flat shadow name, not the word "temp".
    assert not re.search(r"[\\/]Temp[\\/]tmp[^\\/]*\.\w+", blob)
    assert all(
        "temp" not in str(meta.get("module_name", "")).lower()
        for meta in parsed["chunk_metadatas"]
    )
    # The shadow path also broke layer detection: tests/ became root.
    assert any(meta.get("layer") == "tests" for meta in parsed["chunk_metadatas"])


def test_notify_change_refuses_system_project_root(tmp_path):
    sysdir = tmp_path / ".git"
    sysdir.mkdir()
    tool = NotifyChangeTool.__new__(NotifyChangeTool)
    tool.rate_limiter = SimpleNamespace(acquire=lambda *a, **k: True)

    answer = asyncio.run(
        tool.execute(file_path="config", project_root=str(sysdir))
    )

    assert "Refusing" in answer


def test_restricted_read_rejects_absolute_path_with_unknown_root(monkeypatch, tmp_path):
    from src.core.di_container import ProjectIndexerRegistry

    monkeypatch.setenv("MSCODEBASE_RESTRICTED_READ", "1")
    allowed = tmp_path / "allowed"
    other = tmp_path / "other"
    allowed.mkdir()
    other.mkdir()
    (allowed / "secret.txt").write_text("ALLOWED\n", encoding="utf-8")
    (other / "secret.txt").write_text("LEAK\n", encoding="utf-8")

    class Registry:
        def get_all_paths(self):
            return [allowed]

    tool = ReadLiveFileTool(_DummyServices({ProjectIndexerRegistry: Registry()}))

    denied = asyncio.run(
        tool.execute(
            absolute_path=str(other / "secret.txt"), project_root=str(other)
        )
    )
    passed = asyncio.run(
        tool.execute(
            absolute_path=str(allowed / "secret.txt"), project_root=str(allowed)
        )
    )

    assert "Restricted read" in str(denied)
    assert "ALLOWED" in str(passed)


def test_health_report_uses_the_explicit_project_indexer(monkeypatch, tmp_path):
    import src.core.intelligence.health as health_mod

    active = tmp_path / "active"
    other = tmp_path / "other"
    active.mkdir()
    other.mkdir()
    captured: dict = {}

    class FakeReport:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run_full_diagnostic(self):
            return {"ok": True}

    monkeypatch.setattr(health_mod, "HealthReport", FakeReport)
    tool = GetHealthReportTool(_DummyServices())
    active_indexer = SimpleNamespace(project_path=active)
    explicit_indexer = SimpleNamespace(project_path=other)
    tool.resolve_indexer = lambda explicit_project_root=None: (
        explicit_indexer if explicit_project_root else active_indexer
    )
    tool.resolve_symbol_index = lambda explicit_project_root=None: object()
    tool.resolve_embedder = lambda: object()

    asyncio.run(tool.execute(project_root=str(other)))

    assert captured["indexer"] is explicit_indexer
    assert captured["project_path"] == other


def test_notify_change_reports_the_explicit_project(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    source = target / "x.py"
    source.write_text("x = 1\n", encoding="utf-8")

    tool = NotifyChangeTool.__new__(NotifyChangeTool)
    tool.rate_limiter = SimpleNamespace(acquire=lambda *a, **k: True)
    tool._services = SimpleNamespace()
    tool.resolve_indexer = lambda explicit_project_root=None: SimpleNamespace(
        _index_single_file=lambda *a, **k: True,
        bm25_batch=None,
        searcher=None,
    )

    async def fake_content(rel_path):
        return ("x = 1\n", "filesystem")

    tool._get_content = fake_content
    tool._project_header = lambda explicit=None, prefix="": f"HEADER:{explicit}"

    answer = asyncio.run(
        tool.execute(file_path=str(source), project_root=str(target))
    )

    assert f"HEADER:{target.resolve()}" in answer


class _DemoteStore:
    """Docs first, code second: exactly the shape the default path returned."""

    def count(self):
        return 2

    def search(self, query, limit):
        return [
            {
                "text": "docs",
                "text_full": "docs",
                "final_score": 10.0,
                "metadata": {"file": "docs/x.md", "chunk_index": 0},
            },
            {
                "text": "code",
                "text_full": "code",
                "final_score": 9.0,
                "metadata": {"file": "src/x.py", "chunk_index": 1},
            },
        ]


def _demote_searcher(enabled: bool) -> Searcher:
    searcher = Searcher.__new__(Searcher)
    searcher._ondemand_rerank = False
    searcher._ondemand_rerank_top_n = 10
    searcher._ondemand_rerank_max_chars = 1600
    searcher._demote_non_code = enabled
    searcher._demote_intent_aware = True
    searcher._chunk_store = _DemoteStore()
    searcher._last_rerank_timing = {}
    return searcher


def test_sqlite_path_demotes_docs_when_enabled():
    rows = asyncio.run(
        _demote_searcher(True)._sqlite_hybrid_search_async(
            "plain words", 5, rerank=False
        )
    )

    assert rows[0]["metadata"]["file"] == "src/x.py"


def test_sqlite_path_keeps_docs_when_demotion_is_off():
    rows = asyncio.run(
        _demote_searcher(False)._sqlite_hybrid_search_async(
            "plain words", 5, rerank=False
        )
    )

    assert rows[0]["metadata"]["file"] == "docs/x.md"


def test_project_scoped_tools_expose_project_root():
    """The live schema must expose every parameter the class accepts.

    This class of defect (inline wrapper with its own signature) shipped twice:
    read_live_file/notify_change dropped project_root, predict_change never had
    it. The sweep of `tools/list` vs these signatures found predict_change; the
    test keeps the whole set honest.
    """
    classes = [
        SearchCodeTool,
        GetSymbolInfoTool,
        ImpactAnalysisTool,
        GrepCodeTool,
        InvestigateTool,
        CodebaseTool,
        GraphQueryTool,
        PredictChangeTool,
        ReadLiveFileTool,
        NotifyChangeTool,
        GetHealthReportTool,
        WriteTool,
    ]
    missing = []
    for cls in classes:
        fn = getattr(cls.execute, "__wrapped__", cls.execute)
        if "project_root" not in inspect.signature(fn).parameters:
            missing.append(cls.__name__)

    assert missing == []


def test_inline_tool_wrappers_forward_project_root():
    source = (
        Path(__file__).resolve().parents[1] / "src/mcp/server_tools.py"
    ).read_text(encoding="utf-8")

    for name in ("read_live_file", "notify_change"):
        start = source.index(f"async def {name}(")
        block = source[start:start + 1200]
        signature = block[:block.index(") ->")]
        assert "project_root" in signature, name
        assert "project_root=project_root" in block, name


def test_predict_change_uses_the_explicit_project(tmp_path, monkeypatch):
    from src.core import change_preview

    seen = {}
    monkeypatch.setattr(
        change_preview,
        "static_predict",
        lambda repo, base: seen.update(repo=repo, base=base)
        or {"changed": [], "note": "nothing"},
    )
    tool = PredictChangeTool(_DummyServices())

    asyncio.run(tool.execute(project_root=str(tmp_path)))

    assert seen["repo"] == tmp_path.resolve()


def test_write_tool_uses_explicit_project_for_contract(tmp_path):
    tool = WriteTool(_DummyServices())
    seen = {}

    def fake_resolve(explicit_project_root=None):
        seen["root"] = explicit_project_root
        return SimpleNamespace(project_path=tmp_path)

    tool.resolve_indexer = fake_resolve  # type: ignore[method-assign]
    tool._write_project_root = str(tmp_path)

    assert tool._contract_project_root() == str(tmp_path)
    assert seen["root"] == str(tmp_path)


def test_write_hub_forwards_project_root(monkeypatch):
    seen = {}

    async def fake_execute(self, **kwargs):
        seen.update(kwargs)
        return "ok"

    monkeypatch.setattr(WriteTool, "execute", fake_execute)
    tool = CodebaseTool(_DummyServices())

    answer = asyncio.run(
        tool._action_write(
            action="replace",
            symbol="render",
            new_code="def render(): pass",
            apply=False,
            project_root="D:\\other",
        )
    )

    assert answer == "ok"
    assert seen["project_root"] == "D:\\other"


def test_cyrillic_question_without_identifier_asks_for_rewrite():
    from src.mcp.tools.investigate_tool import (
        _identifiers,
        _needs_identifier_rewrite,
    )

    query = "Где ключ подписи Corpus Hub?"
    answer = _needs_identifier_rewrite(query, _identifiers(query))

    assert answer is not None
    assert "verdict: ask_rewrite" in answer
    assert "идентификатора кода" in answer
    assert "file:" not in answer


def test_cyrillic_question_with_a_real_term_is_not_blocked():
    from src.mcp.tools.investigate_tool import (
        _identifiers,
        _needs_identifier_rewrite,
    )

    query = "где используется rerank"
    assert _needs_identifier_rewrite(query, _identifiers(query)) is None


def test_cyrillic_backticked_class_name_passes():
    from src.mcp.tools.investigate_tool import (
        _identifiers,
        _needs_identifier_rewrite,
    )

    query = "Где определён `Indexer`?"
    assert _needs_identifier_rewrite(query, _identifiers(query)) is None


def test_cyrillic_filename_passes():
    """`progress.json` is a code token even though it has no underscore."""
    from src.mcp.tools.investigate_tool import (
        _identifiers,
        _needs_identifier_rewrite,
    )

    query = "Где вычисляется путь `progress.json` вне проекта?"
    assert _needs_identifier_rewrite(query, _identifiers(query)) is None


def test_cyrillic_filename_passes_without_backticks():
    """`progress.json` is a code token even with no backticks and no underscore."""
    from src.mcp.tools.investigate_tool import (
        _identifiers,
        _needs_identifier_rewrite,
    )

    query = "Где вычисляется progress.json вне проекта?"
    assert _needs_identifier_rewrite(query, _identifiers(query)) is None


def test_backticked_cyrillic_prose_is_still_gated():
    """Backticks around Russian words are emphasis, not a code reference."""
    from src.mcp.tools.investigate_tool import (
        _identifiers,
        _needs_identifier_rewrite,
    )

    query = "Где описан контракт `артефакты вне проекта`?"
    assert _needs_identifier_rewrite(query, _identifiers(query)) is not None


def test_rewrite_gate_control_switch(monkeypatch):
    from src.mcp.tools.investigate_tool import _rewrite_gate_mode

    monkeypatch.delenv("MSCODEBASE_ASK_REWRITE", raising=False)
    assert _rewrite_gate_mode() == "smart"
    monkeypatch.setenv("MSCODEBASE_ASK_REWRITE", "0")
    assert _rewrite_gate_mode() == "off"
    monkeypatch.setenv("MSCODEBASE_ASK_REWRITE", "1")
    assert _rewrite_gate_mode() == "on"
    monkeypatch.setenv("MSCODEBASE_ASK_REWRITE", "smart")
    assert _rewrite_gate_mode() == "smart"


def test_smart_mode_gates_only_proper_noun_questions(monkeypatch):
    from src.mcp.tools.investigate_tool import _asks_for_identifier

    monkeypatch.setenv("MSCODEBASE_ASK_REWRITE", "smart")

    assert _asks_for_identifier("Где ключ подписи Corpus Hub?") is not None
    assert _asks_for_identifier("Где описан контракт «артефакты вне проекта»?") is None
    assert _asks_for_identifier("Где LSP-инструмент отправляет за ссылками?") is None
    assert _asks_for_identifier("где переключается проект") is None

    # The default is smart: a proper noun is the only thing that gates.
    monkeypatch.delenv("MSCODEBASE_ASK_REWRITE", raising=False)
    assert _asks_for_identifier("Где ключ подписи Corpus Hub?") is not None
    assert _asks_for_identifier("Где описан контракт «артефакты вне проекта»?") is None

    # Explicit `on` restores the broad 2026-11-09 rule.
    monkeypatch.setenv("MSCODEBASE_ASK_REWRITE", "1")
    assert _asks_for_identifier("Где описан контракт «артефакты вне проекта»?") is not None


def test_english_question_is_never_rewrite_gated():
    from src.mcp.tools.investigate_tool import (
        _identifiers,
        _needs_identifier_rewrite,
    )

    query = "where is the project state machine"
    assert _needs_identifier_rewrite(query, _identifiers(query)) is None


def test_modification_guard_does_not_block_ack():
    from src.core.modification_guard import modification_guard

    calls = []

    @modification_guard()
    async def fake(self, action: str, file_path: str = ""):
        calls.append(action)
        return "ok"

    assert asyncio.run(fake(object(), action="ack", file_path="x.py")) == "ok"
    assert calls == ["ack"]


def test_render_explain_keeps_stages_and_chunks():
    from src.mcp.tools.search_tools import _render_explain

    text = _render_explain(
        {
            "stage_timing_ms": {"docs_route_ms": 12.4, "total_ms": 12.4},
            "chunks": [
                {
                    "file_path": "docs/en/X.md",
                    "final_position": 1,
                    "final_score": 1.2345,
                    "bm25_rank": 2,
                }
            ],
        },
        3,
    )

    assert "Explain Trace" in text
    assert "docs_route_ms" in text
    assert "docs/en/X.md" in text
    assert "BM25 rank=2" in text


def test_render_explain_handles_missing_fields():
    from src.mcp.tools.search_tools import _render_explain

    text = _render_explain({"stage_timing_ms": {"total_ms": "n/a"}}, 3)

    assert "total_ms" in text


def test_set_project_refuses_system_directory(preserve_project_env):
    tool = SetProjectTool(_DummyServices())
    # Windows has drive roots ("C:\"); POSIX has "/". Both must be refused.
    root = "C:\\" if os.name == "nt" else "/"

    answer = asyncio.run(tool.execute(project_root=root))

    assert "Refusing" in answer
    assert os.environ.get("MSCODEBASE_PROJECT_PATH") != root


def test_restricted_read_rejects_unknown_project_root(monkeypatch, tmp_path):
    from src.core.di_container import ProjectIndexerRegistry

    monkeypatch.setenv("MSCODEBASE_RESTRICTED_READ", "1")
    allowed = tmp_path / "allowed"
    other = tmp_path / "other"
    allowed.mkdir()
    other.mkdir()
    (allowed / "x.txt").write_text("ALLOWED\n", encoding="utf-8")
    (other / "x.txt").write_text("OTHER\n", encoding="utf-8")

    class Registry:
        def get_all_paths(self):
            return [allowed]

    tool = ReadLiveFileTool(_DummyServices({ProjectIndexerRegistry: Registry()}))
    tool.resolve_indexer = lambda explicit_project_root=None: SimpleNamespace(
        project_path=Path(explicit_project_root) if explicit_project_root else allowed
    )

    denied = asyncio.run(tool.execute(file_path="x.txt", project_root=str(other)))
    passed = asyncio.run(tool.execute(file_path="x.txt", project_root=str(allowed)))

    assert "Restricted read" in str(denied)
    assert "ALLOWED" in str(passed)


def test_index_project_dir_returns_a_job_and_finishes(tmp_path, monkeypatch):
    from src.config.settings import reload_config
    from src.core.di_container import create_service_collection
    from src.mcp.tools.indexing_tools import IndexProjectDirTool, get_index_job

    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")

    # CI has no embedder; text-only indexing is the supported path there.
    with monkeypatch.context() as mp:
        mp.setenv("MSCODEBASE_DENSE_OFF", "true")
        reload_config()
        services = create_service_collection(tmp_path)
        tool = IndexProjectDirTool(services)

        answer = asyncio.run(tool.execute(path=str(tmp_path)))

        assert "запущена" in answer.lower()
        assert str(tmp_path.resolve()) in answer

        job = None
        deadline = time.time() + 120
        while time.time() < deadline:
            job = get_index_job(str(tmp_path))
            if job and job.get("state") in ("done", "error"):
                break
            time.sleep(0.2)
    reload_config()

    assert job is not None
    assert job["state"] == "done", job
    assert job["files"] >= 1


def test_name_variants_builds_compound_identifiers():
    from src.mcp.tools.investigate_tool import _name_variants, _name_words

    words = _name_words("where is the default line length defined")
    variants = _name_variants(words)

    assert words == ["default", "line", "length"]
    assert "DEFAULT_LINE_LENGTH" in variants
    assert "LINE_LENGTH" in variants


def test_grep_search_counts_two_patterns_in_one_walk(tmp_path):
    from src.mcp.tools.grep_tool import GrepCodeTool

    (tmp_path / "a.py").write_text("alpha beta\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("beta\n", encoding="utf-8")
    tool = GrepCodeTool(_DummyServices())

    result = tool._search(  # noqa: SLF001
        tmp_path,
        None,
        re.compile(b"alpha"),
        "all",
        10,
        0,
        extra_patterns=[re.compile(b"beta")],
    )

    assert result["total"] == 1
    assert result["extra_totals"] == [2]
    assert {m["file"] for m in result["matches"]} == {"a.py", "b.py"}


def test_live_buffer_shadow_keeps_the_real_path_and_layer(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    target = tests_dir / "test_live.py"
    target.write_bytes(b"def old():\n    return 0\n")
    live = "def widget():\n    return 2\n"  # differs from disk -> shadow is used

    parsed = _parser(tmp_path).parse_file(target, "tests/test_live.py", content=live)

    assert parsed is not None
    blob = " ".join(parsed["chunk_texts"] + parsed["chunk_texts_full"])
    assert not re.search(r"[\\/]Temp[\\/]tmp[^\\/]*\.\w+", blob)
    assert all(meta.get("layer") == "tests" for meta in parsed["chunk_metadatas"])
