"""Контракт поверхности: скрыт из списка ≠ недоступен, схемы по запросу.

Размеры печатает `python scripts/mcp_surface_size.py` (не хардкодим:
любая правка описания их сдвигает). Остальные инструменты остаются
зарегистрированными и вызываемыми, схема — через tool_help(<name>).
"""
from __future__ import annotations

import asyncio

try:  # mcp 2.x: MCPServer; 1.x: FastMCP
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # pragma: no cover - откатная линия 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from src.core.di_container import ServiceCollection
from src.mcp import server_tools as st
from src.mcp.tools.help_tool import ToolHelpTool


def _destructive(ann):
    """destructiveHint (1.x) / destructive_hint (2.x) — одно и то же поле."""
    value = getattr(ann, "destructiveHint", None)
    return getattr(ann, "destructive_hint", None) if value is None else value


def _mcp_with(names):
    mcp = _Server("surface-test")
    for name in names:
        def _fn() -> str:  # noqa: ANN202
            return f"ok:{name}"

        _fn.__name__ = name
        mcp.tool(name)(_fn)
    return mcp


def test_hidden_tool_is_still_callable(monkeypatch):
    monkeypatch.delenv("MSCODEBASE_MCP_PROFILE", raising=False)
    mcp = _mcp_with(["search_code", "structural_search"])
    st._apply_tool_profile(mcp)

    listed = {t.name for t in mcp._tool_manager.list_tools()}  # noqa: SLF001
    assert "structural_search" not in listed, "скрытый не должен быть в списке"

    result = asyncio.run(mcp.call_tool("structural_search", {}))
    content = getattr(result, "content", None)
    if content:
        text = content[0].text
    else:
        # mcp 2.x returns (list[TextContent], metadata); 1.x returned an object
        # with `.content` or a bare tuple. Read the first block, not the tuple slot.
        first = result[0] if isinstance(result, tuple) and result else result
        if isinstance(first, list) and first and hasattr(first[0], "text"):
            text = first[0].text
        else:
            text = str(result)
    assert "ok:structural_search" in str(text)


def test_annotations_are_present_for_every_registered_tool(monkeypatch):
    monkeypatch.delenv("MSCODEBASE_MCP_PROFILE", raising=False)
    mcp = _mcp_with(["search_code", "codebase", "intel_reset_index"])
    st._apply_tool_profile(mcp)

    for name, tool in mcp._tool_manager._tools.items():  # noqa: SLF001
        assert tool.annotations is not None, name
        assert isinstance(_destructive(tool.annotations), bool), name
    assert _destructive(mcp._tool_manager._tools["search_code"].annotations) is False  # noqa: SLF001
    assert _destructive(mcp._tool_manager._tools["codebase"].annotations) is True  # noqa: SLF001


def test_tool_help_returns_schema_for_hidden_tool(monkeypatch):
    monkeypatch.delenv("MSCODEBASE_MCP_PROFILE", raising=False)
    mcp = _mcp_with(["search_code", "structural_search"])
    st._apply_tool_profile(mcp)

    tool = ToolHelpTool(ServiceCollection())
    out = asyncio.run(tool.execute(query="structural_search"))

    assert "inputSchema" in out, out[:200]
    assert "structural_search" in out
    assert "скрыт из tools/list" in out


def test_fixture_surface_is_smaller_than_registry(monkeypatch):
    monkeypatch.delenv("MSCODEBASE_MCP_PROFILE", raising=False)
    mcp = _mcp_with(list(st.CORE_PROFILE) + ["structural_search", "intel_reset_index"])
    st._apply_tool_profile(mcp)

    listed = mcp._tool_manager.list_tools()  # noqa: SLF001
    assert {t.name for t in listed} == set(st.CORE_PROFILE)
    assert len(mcp._tool_manager._tools) > len(listed)  # noqa: SLF001
    # Схемы доступны для всех зарегистрированных, а не только видимых.
    assert set(st._TOOL_SCHEMAS) >= set(mcp._tool_manager._tools)  # noqa: SLF001


def test_full_profile_lists_everything(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_MCP_PROFILE", "full")
    names = ["search_code", "structural_search", "intel_reset_index"]
    mcp = _mcp_with(names)
    st._apply_tool_profile(mcp)

    listed = {t.name for t in mcp._tool_manager.list_tools()}  # noqa: SLF001
    assert listed == set(names)


def test_explicit_allowlist_overrides_the_profile(monkeypatch):
    """MSCODEBASE_MCP_TOOLS режет ВЕСЬ реестр, а не только core-группу.

    Ревью №4: при allowlist профиль принудительно становился full, и
    `MSCODEBASE_MCP_TOOLS=search_code,structural_search` давал 35 инструментов
    вместо 2 (intel/inline/dev регистрируются мимо allowlist-фильтра).
    """
    monkeypatch.delenv("MSCODEBASE_MCP_PROFILE", raising=False)
    monkeypatch.setenv("MSCODEBASE_MCP_TOOLS", "search_code")
    names = ["search_code", "structural_search"]
    mcp = _mcp_with(names)
    st._apply_tool_profile(mcp)

    listed = {t.name for t in mcp._tool_manager.list_tools()}  # noqa: SLF001
    assert listed == {"search_code"}
    # Скрытые остаются вызываемыми по имени (вызов проверен отдельным тестом).
    assert "structural_search" in st._HIDDEN_NAMES


def test_switching_to_full_restores_the_list(monkeypatch):
    names = ["search_code", "structural_search"]
    mcp = _mcp_with(names)

    monkeypatch.delenv("MSCODEBASE_MCP_PROFILE", raising=False)
    st._apply_tool_profile(mcp)
    assert {t.name for t in mcp._tool_manager.list_tools()} == {"search_code"}

    monkeypatch.setenv("MSCODEBASE_MCP_PROFILE", "full")
    st._apply_tool_profile(mcp)
    assert {t.name for t in mcp._tool_manager.list_tools()} == set(names)


def test_tool_help_under_allowlist_counts_the_listing(monkeypatch):
    """Под allowlist tool_help обязан считать видимыми именно разрешённые.

    Ревью №5, major 4: раньше видимое бралось из CORE_PROFILE, и tool_help
    печатал 13 инструментов, которых в реестре этого режима не было.
    """
    monkeypatch.setenv("MSCODEBASE_MCP_TOOLS", "search_code")
    monkeypatch.delenv("MSCODEBASE_MCP_PROFILE", raising=False)
    catalog = {"search_code": "ranked search", "grep_code": "regex", "codebase": "hub"}
    monkeypatch.setattr(st, "_FULL_CATALOG", dict(catalog), raising=False)
    monkeypatch.setattr(
        st, "_TOOL_SCHEMAS", {name: {"type": "object"} for name in catalog}, raising=False
    )

    tool = ToolHelpTool(ServiceCollection())
    out = asyncio.run(tool.execute())

    assert "allowlist — 1 exposed" in out, out.splitlines()[:3]
    head = out.split("🔒")[0]
    assert "`search_code`" in head or "• search_code" in head
    assert "• grep_code" not in head


def test_execute_script_is_destructive_when_enabled(monkeypatch):
    """70-й инструмент (RCE) не должен выглядеть безопасным (ревью №5, major 2)."""
    monkeypatch.setenv("MSCODEBASE_EXECUTE_SCRIPT_ENABLED", "true")
    monkeypatch.delenv("MSCODEBASE_MCP_TOOLS", raising=False)
    mcp = _mcp_with(["search_code", "execute_script"])
    st._apply_tool_profile(mcp)

    assert _destructive(mcp._tool_manager._tools["execute_script"].annotations) is True  # noqa: SLF001
    assert _destructive(mcp._tool_manager._tools["search_code"].annotations) is False  # noqa: SLF001
