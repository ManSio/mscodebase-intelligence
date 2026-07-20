"""
Тест: search_code показывает маркер источника (fts5/bm25/dense).

Доказывает, что пользователь видит, КАКОЙ движок нашёл результат
(AGENTS.md: видимость FTS5). Раньше metadata.source терялся при
конвертации в ui_items -> маркер не показывался.
"""
from src.utils.ui_formatter import format_search_code
from src.mcp.tools.search_tools import SearchCodeTool


def _ui_items_with_sources():
    """Результаты с разными источниками (как из hybrid_search_async)."""
    return [
        {
            "file_path": "src/core/search/engine.py",
            "start_line": 287,
            "text": "async def hybrid_search_async(...):",
            "layer": "core",
            "score": 0.9,
            "source": "fts5_hybrid",
        },
        {
            "file_path": "src/core/search/fts5_mixin.py",
            "start_line": 6,
            "text": "def _fts5_search(...):",
            "layer": "core",
            "score": 0.8,
            "source": "bm25",
        },
        {
            "file_path": "src/core/search/engine.py",
            "start_line": 14,
            "text": "async def ask_async(...):",
            "layer": "core",
            "score": 0.7,
            "source": "",
        },
    ]


def test_format_search_code_shows_fts5_marker():
    out = format_search_code("def hybrid_search_async", _ui_items_with_sources(), 4317, "quality")
    assert "🔍`fts5`" in out, "FTS5-маркер должен быть в выдаче"
    assert "🔤`bm25`" in out, "BM25-маркер должен быть в выдаче"
    # результат без source -> без маркера
    assert "ask_async" in out


def test_search_tool_converts_metadata_source():
    """_format_results прокидывает metadata.source в ui_items."""
    raw = {
        "results": [
            {
                "text": "x",
                "metadata": {"file": "a.py", "chunk_index": 0, "source": "fts5_hybrid"},
                "final_score": 0.9,
            }
        ],
        "timing_ms": {"total_ms": 100},
        "query": "q",
    }
    out = SearchCodeTool._format_results(raw, "quality")
    assert "🔍`fts5`" in out, "metadata.source должен попасть в выдачу"
