"""MCP-контракт: артефакт соответствует реестру, у каждого инструмента есть annotations."""
from __future__ import annotations

import json
import os

import pytest

from scripts.export_mcp_contract import ARTIFACT, build_contract, render


@pytest.fixture(scope="module")
def contract() -> dict:
    return build_contract()


def test_artifact_matches_registry(contract):
    assert ARTIFACT.exists(), "docs/MCP_CONTRACT.json отсутствует"
    assert ARTIFACT.read_text(encoding="utf-8") == render(contract), (
        "контракт устарел: python scripts/export_mcp_contract.py"
    )


def test_contract_is_deterministic(contract):
    again = build_contract()
    assert again["sha256"] == contract["sha256"]


def test_every_tool_declares_side_effects(contract):
    """destructiveHint есть у всех: клиент должен знать, изменит ли вызов код.

    readOnlyHint мы намеренно не ставим: hot-reload индекса делает пишущим
    почти любой поисковый инструмент, и ложный readOnly уже был найден
    (search_code, hotspots) — см. комментарий в server_tools.py.
    """
    missing = [
        t["name"] for t in contract["tools"]
        if not isinstance(t["annotations"].get("destructiveHint"), bool)
    ]
    assert not missing, f"без destructiveHint: {missing}"
    assert not [t for t in contract["tools"] if "readOnlyHint" in t["annotations"]]


def test_write_tools_are_destructive(contract):
    tools = {t["name"]: t for t in contract["tools"]}
    # Статический список плюс мутаторы, которые регистрационная догадка
    # помечала как чтение (ревью 2026-11-17, blocker 1).
    # Только то, что меняет исходники или память проекта. Индекс/кэш/телеметрия
    # и фоновые задачи — производное состояние (см. test_derived_state_tools...).
    for name in (
        "codebase",
        "intel_add_memory_node",
        "intel_retract_memory_node",
        "intel_supersede_memory_node",
        "intel_restore_memory_node",
        "intel_log_incident",
        "intel_auto_collect_adrs",
        "set_project",
        "generate_docs",
        "bump_version",
        "install_git_hooks",
    ):
        assert tools[name]["annotations"]["destructiveHint"] is True, name


def test_derived_state_tools_are_not_destructive(contract):
    """Индекс/кэш/телеметрия — производное состояние, не порча исходников."""
    tools = {t["name"]: t for t in contract["tools"]}
    for name in (
        "search_code",
        "grep_code",
        "investigate",
        "graph_query",
        "scan_changes",
        "notify_change",
        "intel_get_telemetry",
        "intel_reset_index",
    ):
        assert tools[name]["annotations"]["destructiveHint"] is False, name


def test_catalog_has_no_duplicate_names(contract):
    names = [t["name"] for t in contract["tools"]]
    assert len(names) == len(set(names))
    assert json.loads(render(contract))["tool_count"] == len(names)


def test_export_restores_the_process_env(monkeypatch):
    """Экспорт не должен оставлять процессу чужой профиль/режим (ревью №2)."""
    monkeypatch.setenv("MSCODEBASE_MCP_PROFILE", "core")
    monkeypatch.setenv("MSCODEBASE_MCP_TOOLS", "search_code")
    monkeypatch.delenv("MSCODEBASE_DENSE_OFF", raising=False)
    monkeypatch.delenv("LLAMA_CPP_ENABLED", raising=False)

    build_contract()

    assert os.environ["MSCODEBASE_MCP_PROFILE"] == "core"
    assert os.environ["MSCODEBASE_MCP_TOOLS"] == "search_code"
    assert "MSCODEBASE_DENSE_OFF" not in os.environ
    assert "LLAMA_CPP_ENABLED" not in os.environ
