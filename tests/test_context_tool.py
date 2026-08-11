"""Test for B-scheme GetContextTool."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.di_container import create_service_collection
from src.mcp.tools.context_tool import GetContextTool


async def test_collect_sections():
    ROOT = Path(__file__).parent.parent
    services = create_service_collection(ROOT)

    # Mock readiness check
    GetContextTool.require_ready_project = AsyncMock()

    tool = GetContextTool(services)

    # Mock the underlying tools
    from src.mcp.tools.search_tools import GetSymbolInfoTool

    symbol_tool = GetSymbolInfoTool(services)
    impact_tool = MagicMock()
    impact_tool.execute = AsyncMock(
        return_value={
            "status": "ok",
            "symbol": "build_call_graph",
            "depth": 3,
            "direct_callers": 2,
            "transitive_callers": 5,
            "direct_callees": 3,
            "transitive_callees": 1,
            "affected_files": ["src/core/indexing/symbol_index.py"],
            "risk_level": "low",
            "risk_score": 12,
        }
    )
    search_tool = MagicMock()
    search_tool.execute = AsyncMock(return_value="search fallback result")

    # Mock symbol_tool.execute
    symbol_tool = GetSymbolInfoTool(services)
    symbol_tool.execute = AsyncMock(
        return_value=(
            "🔍 **build_call_graph** — 1 defs, 2 callers, 3 callees\n\n"
            "📄 Definition: `src/core/indexing/symbol_index.py` line 480\n\n"
            "⬆️ **Called from:**\n"
            "   • `SymbolIndex.get_impact_analysis`\n"
            "   • `SymbolIndex.get_callees`"
        )
    )

    # Test _collect_sections
    sections = await tool._collect_sections(
        "build_call_graph",
        ["source", "symbols", "git"],
        symbol_tool,
        impact_tool,
        search_tool,
    )

    print(f"Sections: {len(sections)}")
    for s in sections:
        print(f"  {s['name']}: {s['tokens']} tokens")
        if s["text"]:
            print(f"    Preview: {s['text'][:100]}")

    assert len(sections) >= 3, f"Expected at least 3 sections, got {len(sections)}"
    section_names = {s["name"] for s in sections}
    assert "symbols" in section_names, "Missing symbols section"
    assert "source" in section_names, "Missing source section"
    assert "git" in section_names, "Missing git section"

    print("\n✅ All tests passed!")


if __name__ == "__main__":
    asyncio.run(test_collect_sections())

