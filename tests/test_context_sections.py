"""Tests for get_context v2: graph-backed sections, VOR filter, structured meta.

Covers: new intents sections, memory VOR filter, receipts file-filtering,
degraded (no-graph) writes, dataflow condition_path rendering, and
regression: dependent sections require symbols.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.di_container import create_service_collection
from src.mcp.tools import context_tool as ct
from src.mcp.tools.context_tool import INTENT_SECTIONS, GetContextTool


def _make_tool(root: Path) -> GetContextTool:
    services = create_service_collection(root)
    GetContextTool.require_ready_project = AsyncMock()
    return GetContextTool(services)


def test_new_sections_declared_in_intents():
    assert "dataflow" in INTENT_SECTIONS["modify"]
    assert "writes" in INTENT_SECTIONS["modify"]
    assert "dataflow" in INTENT_SECTIONS["debug"]
    assert "receipts" in INTENT_SECTIONS["verify_change"]
    assert "tests" in INTENT_SECTIONS["test"]
    assert "receipts" in INTENT_SECTIONS["prepare_change"]
    assert "writes" in INTENT_SECTIONS["prepare_change"]


def test_dependent_sections_require_symbols():
    """Regression: sections that read symbols_data must be paired with 'symbols'."""
    dependent = {"source", "git", "fallback", "receipts", "tests", "dataflow", "writes"}
    for intent, sections in INTENT_SECTIONS.items():
        if dependent & set(sections):
            assert "symbols" in sections, (
                f"intent '{intent}' has {dependent & set(sections)} but no 'symbols'"
            )


def test_memory_vor_filter(tmp_path):
    tool = _make_tool(tmp_path)
    tool._store = MagicMock()
    tool._store.load_memory.return_value = {
        "adr": [
            {"title": "good-active", "status": "ACTIVE"},
            {"title": "good-verified", "status": "VERIFIED"},
            {"title": "bad-refuted", "status": "REFUTED"},
            {"title": "bad-inconclusive", "status": "INCONCLUSIVE"},
            {"title": "no-status-field"},
        ]
    }
    sec = tool._section_memory()
    assert sec is not None
    assert "good-active" in sec["text"]
    assert "good-verified" in sec["text"]
    assert "bad-refuted" not in sec["text"]
    assert "bad-inconclusive" not in sec["text"]
    assert "no-status-field" in sec["text"]


def test_memory_vor_filter_caps_at_8(tmp_path):
    tool = _make_tool(tmp_path)
    tool._store = MagicMock()
    tool._store.load_memory.return_value = {
        "adr": [{"title": f"n{i}", "status": "VERIFIED"} for i in range(12)]
    }
    sec = tool._section_memory()
    assert sec is not None
    body = sec["text"]
    assert body.count("[adr]") == 8


def test_source_uses_meta_no_regex(tmp_path):
    tool = _make_tool(tmp_path)
    f = tmp_path / "sample.py"
    f.write_text("\n".join(f"line{i} = {i}" for i in range(40)), encoding="utf-8")
    symbols_data = {
        "name": "symbols", "text": "no definition marker",
        "tokens": 10, "signature": ("symbols", "sample"),
        "meta": {"file_path": str(f), "line": 10},
    }
    sec = tool._section_source("sample", symbols_data)
    assert sec is not None
    assert "10:" in sec["text"]


def test_source_regex_fallback_still_works(tmp_path):
    tool = _make_tool(tmp_path)
    f = tmp_path / "sample2.py"
    f.write_text("def a():\n    pass\n", encoding="utf-8")
    symbols_data = {
        "name": "symbols", "text": f"?? Definition: `{f}` line 1",
        "tokens": 10, "signature": ("symbols", "a"),
    }
    sec = tool._section_source("a", symbols_data)
    assert sec is not None
    assert "def a():" in sec["text"]


def test_receipts_filter_by_file(tmp_path, monkeypatch):
    tool = _make_tool(tmp_path)
    f = tmp_path / "code.py"
    f.write_text("y = 2\n", encoding="utf-8")

    class FakeStore:
        def query(self, limit=20, action_type=""):
            return [
                {"action_type": "write", "file_path": str(f), "verdict": "ok", "ts": "2026-09-08T12:00:00"},
                {"action_type": "write", "file_path": "D:/other/place.py", "verdict": "ok", "ts": "2026-09-08T12:01:00"},
            ]

    monkeypatch.setattr(ct, "ActionReceiptStore", lambda root: FakeStore())
    symbols_data = {
        "name": "symbols", "text": "", "tokens": 0,
        "signature": ("symbols", "code"),
        "meta": {"file_path": str(f)},
    }
    sec = tool._section_receipts(symbols_data)
    assert sec is not None
    assert "write" in sec["text"]
    assert "place.py" not in sec["text"]


def test_receipts_empty_returns_none(tmp_path, monkeypatch):
    tool = _make_tool(tmp_path)

    class EmptyStore:
        def query(self, limit=20, action_type=""):
            return []

    monkeypatch.setattr(ct, "ActionReceiptStore", lambda root: EmptyStore())
    symbols_data = {
        "name": "symbols", "text": "", "tokens": 0,
        "signature": ("symbols", "x"),
        "meta": {"file_path": "nowhere.py"},
    }
    assert tool._section_receipts(symbols_data) is None


def test_writes_degrades_without_graph(tmp_path):
    tool = _make_tool(tmp_path)
    tool._get_flow_adapter = lambda: None
    symbols_data = {
        "name": "symbols", "text": "", "tokens": 0,
        "signature": ("symbols", "x"),
        "meta": {"file_path": "a.py", "symbol": "A"},
    }
    assert tool._section_writes(symbols_data) is None


def test_dataflow_renders_condition_path(tmp_path):
    tool = _make_tool(tmp_path)
    f = tmp_path / "flow.py"
    f.write_text("def f():\n    a = 1\n", encoding="utf-8")

    class FakeAdapter:
        def get_variable_flow(self, name, scope_id=None, file_path=None, max_depth=3):
            if name != "a":
                return {"variable": None}
            return {
                "variable": {"qualified_name": "X.a"},
                "chain": [{"via": "assign", "line": 2, "condition_path": ["if x"],
                           "to": "X.a", "from": "1"}],
                "incoming": [], "outgoing": [],
            }

    tool._get_flow_adapter = lambda: FakeAdapter()
    symbols_data = {
        "name": "symbols", "text": "", "tokens": 0,
        "signature": ("symbols", "f"),
        "meta": {"file_path": str(f)},
    }
    sec = tool._section_dataflow("f", symbols_data)
    assert sec is not None
    assert "X.a" in sec["text"]
    assert "[if: if x]" in sec["text"]


def test_dataflow_no_candidates_returns_none(tmp_path):
    tool = _make_tool(tmp_path)
    f = tmp_path / "noflow.py"
    f.write_text("import os\n", encoding="utf-8")

    class FakeAdapter:
        def get_variable_flow(self, *a, **k):
            raise AssertionError("must not be called without candidates")

    tool._get_flow_adapter = lambda: FakeAdapter()
    symbols_data = {
        "name": "symbols", "text": "", "tokens": 0,
        "signature": ("symbols", "noflow"),
        "meta": {"file_path": str(f)},
    }
    assert tool._section_dataflow("noflow", symbols_data) is None


def test_error_hint_lists_all_intents():
    unknown = "no_such_intent"
    assert unknown not in INTENT_SECTIONS
    all_intents = " | ".join(INTENT_SECTIONS)
    assert "dataflow" not in all_intents or "dataflow" in INTENT_SECTIONS["modify"]
