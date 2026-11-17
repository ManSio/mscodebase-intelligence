"""Issue #150, дефект 2: неизвестный action не должен уходить в GraphRAG.

Репро: `graph_query {"action":"callers","target":"compositeLink"}` — 90 с без
ответа. Инструмент молча трактовал неизвестный action как query, а синхронный
engine.query_impact() блокировал event loop, поэтому таймаут декоратора не
срабатывал.

error_boundary оборачивает ответ в конверт {"ok": bool, "data"|"error": ...},
поэтому тесты читают его через _ok/_err.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.core.di_container import ServiceCollection
from src.mcp.tools.graph_tools import GraphQueryTool


def _tool() -> GraphQueryTool:
    return GraphQueryTool(ServiceCollection())


def _payload(raw):
    """error_boundary сериализует ответ в JSON-строку."""
    return json.loads(raw) if isinstance(raw, str) else raw


def _ok(raw) -> dict:
    payload = _payload(raw)
    if payload.get("ok") is True:
        return payload.get("data") or {}
    return payload


def _err(raw) -> dict:
    payload = _payload(raw)
    assert payload.get("ok") is False, payload
    return payload.get("error") or {}


def test_unknown_action_is_rejected_and_names_the_alternatives(monkeypatch):
    tool = _tool()
    called: list = []

    async def _fake_query(*_args, **_kwargs):
        called.append(1)
        return {"status": "ok"}

    monkeypatch.setattr(tool, "_execute_query", _fake_query)
    error = _err(asyncio.run(tool.execute(action="callers", target="compositeLink")))

    assert error["code"] == "VALIDATION_FAILED"
    assert "callers" in error["message"]
    assert "query" in error["details"]["allowed_actions"]
    assert called == [], "неизвестный action не должен запускать GraphRAG"


def test_unknown_action_points_to_get_symbol_info(monkeypatch):
    tool = _tool()

    async def _fake_query(*_args, **_kwargs):
        return {"status": "ok"}

    monkeypatch.setattr(tool, "_execute_query", _fake_query)
    error = _err(asyncio.run(tool.execute(action="nope")))

    assert "get_symbol_info" in error["details"]["next_step"]


def test_query_action_still_routes_to_graphrag(monkeypatch):
    tool = _tool()
    seen: dict = {}

    async def _fake_query(query_type, target, kwargs=None, project_root=""):
        seen.update(query_type=query_type, target=target)
        return {"status": "ok", "query_type": query_type}

    monkeypatch.setattr(tool, "_execute_query", _fake_query)
    raw = asyncio.run(tool.execute(action="query", target="widget"))

    # Успешный ответ — человекочитаемый текст (не JSON-конверт).
    assert "Completed" in raw, raw
    assert seen == {"query_type": "impact", "target": "widget"}


def test_impact_call_runs_through_a_thread(monkeypatch, tmp_path: Path):
    """Синхронный engine больше не блокирует loop: вызов идёт через to_thread."""
    import threading

    import src.core.graph_rag as graph_rag

    seen_thread: dict = {}

    class _Engine:
        def query_impact(self, target):
            seen_thread["name"] = threading.current_thread().name
            return {"risk_score": 1, "direct_impact": [], "tests_to_run": []}

    monkeypatch.setattr(graph_rag, "GraphRAGQueryEngine", lambda *a, **k: _Engine())
    tool = _tool()
    monkeypatch.setattr(tool, "resolve_indexer",
                        lambda **kw: type("I", (), {"project_path": tmp_path})())
    monkeypatch.setattr(tool, "resolve_symbol_index", lambda **kw: None)

    data = _ok(asyncio.run(tool._execute_query("impact", "widget")))

    assert data["status"] == "ok"
    assert data["risk_score"] == 1
    # Синхронный вызов шёл бы в главном потоке; to_thread — в рабочем.
    assert seen_thread["name"] != threading.main_thread().name, seen_thread
