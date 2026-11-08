"""Tool surface profile: one entry per intent instead of 68 tools.

2026-11-08: the client saw 54 tools (6 LSP variants, 16 intel_*, 3 search
flavours). The model cannot choose reliably from that. `core` exposes the
intents in `CORE_PROFILE`; everything else stays registered but hidden until
`MSCODEBASE_MCP_PROFILE=full`, and `tool_help` lists what is hidden.
"""

from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

from src.core.di_container import ServiceCollection
from src.mcp import server_tools as st
from src.mcp.tools.help_tool import ToolHelpTool


def _mcp_with(names) -> FastMCP:
    mcp = FastMCP("profile-test")
    for name in names:
        def _fn() -> str:  # noqa: ANN202 — минимальная заглушка
            return "ok"

        _fn.__name__ = name
        mcp.tool(name)(_fn)
    return mcp


def _visible(mcp: FastMCP) -> set[str]:
    return set(mcp._tool_manager._tools)  # noqa: SLF001 — единственный синхронный список


def test_core_profile_hides_everything_else(monkeypatch):
    monkeypatch.delenv("MSCODEBASE_MCP_PROFILE", raising=False)
    names = list(st.CORE_PROFILE) + ["lsp_find_definition", "intel_get_hotspots"]
    mcp = _mcp_with(names)

    st._apply_tool_profile(mcp)

    assert _visible(mcp) == set(st.CORE_PROFILE)
    assert "lsp_find_definition" in st._FULL_CATALOG


def test_full_profile_keeps_everything(monkeypatch):
    monkeypatch.setenv("MSCODEBASE_MCP_PROFILE", "full")
    names = ["search_code", "lsp_find_definition"]
    mcp = _mcp_with(names)

    st._apply_tool_profile(mcp)

    assert _visible(mcp) == set(names)


def test_tool_help_reports_hidden_tools(monkeypatch):
    monkeypatch.delenv("MSCODEBASE_MCP_PROFILE", raising=False)
    mcp = _mcp_with(["search_code", "lsp_find_definition", "intel_get_hotspots"])
    st._apply_tool_profile(mcp)

    tool = ToolHelpTool(ServiceCollection())
    out = asyncio.run(tool.execute())

    assert "profile: core" in out
    assert "search_code" in out
    assert "lsp_find_definition" in out      # скрыт, но перечислен
    assert "MSCODEBASE_MCP_PROFILE=full" in out


def test_core_profile_registers_full_registry_then_hides(monkeypatch):
    """Runtime-контракт профиля: регистрируются ВСЕ, наружу — 17.

    Регрессия 2026-11-08: ручной default-allowlist резал регистрацию (56 вместо
    69), а `_apply_tool_profile` вызывался до dev-тулов — `_FULL_CATALOG`
    снимался с неполного реестра, и tool_help показывал неверный список
    скрытых. Тест ловит оба дефекта: количество зарегистрированных и размер
    каталога для tool_help.
    """
    from unittest.mock import MagicMock

    monkeypatch.delenv("MSCODEBASE_MCP_PROFILE", raising=False)
    monkeypatch.delenv("MSCODEBASE_MCP_TOOLS", raising=False)

    app = FastMCP("profile-runtime")
    st.register_all_tools(app, MagicMock())

    visible = set(app._tool_manager._tools)  # noqa: SLF001
    catalog = set(st._FULL_CATALOG)

    # Профиль не должен выпускать наружу ничего вне CORE_PROFILE.
    assert visible <= set(st.CORE_PROFILE), sorted(visible - set(st.CORE_PROFILE))
    # Каталог снимается с полного реестра ДО фильтрации, поэтому он шире поверхности.
    assert visible <= catalog
    assert len(catalog) > len(visible), (len(catalog), len(visible))
    # Ядро интентов регистрируется всегда (intel-слой может быть заблокирован
    # self-indexing guard'ом в CI — это не повод падать).
    always = {
        "investigate", "search_code", "grep_code", "get_symbol_info",
        "impact_analysis", "graph_query", "codebase", "read_live_file",
        "notify_change", "get_health_report", "predict_change", "tool_help",
        "generate_docs", "bump_version", "auto_update_docs", "install_git_hooks",
    }
    assert always <= visible, sorted(always - visible)
    # Скрытые инструменты действительно перечислены в каталоге.
    assert "debug_runtime_passport" in catalog
    assert "debug_runtime_passport" not in visible

