"""Совпадение имени в теле чанка, а не в E26-шапке; валидация graph related.

Аудит engraphis 2026-11-18:
- `investigate("where is the recall engine implemented")` показывал 4 строки
  `[name]` с именем `RecallEngine`, которое в `core/recall.py` объявлено один
  раз, а в остальных чанках присутствует только в `SYMBOLS:`-префиксе.
- `graph_query(action="related", target="intent_recall")` отвечал
  `✅ Completed … related_files: []`, хотя `related` работает по файлам.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.core.indexing.chunk_augment import (
    build_file_prefix,
    strip_file_prefix,
)
from src.mcp.tools.graph_tools import GraphQueryTool
from src.mcp.tools.investigate_tool import body_contains, name_rows

CLASS_BODY = "class RecallEngine:\n    pass\n"
PREFIX = build_file_prefix("engraphis/core/recall.py", CLASS_BODY)
HEADER_ONLY = PREFIX + "class Other:\n    pass\n"


def test_prefix_is_stripped_exactly_once():
    assert strip_file_prefix(HEADER_ONLY).startswith("class Other")
    plain = "class Other:\n    pass\n"
    assert strip_file_prefix(plain) == plain


def test_name_in_prefix_only_is_not_a_body_match():
    """`RecallEngine` в шапке чанка — не доказательство, что он здесь объявлен."""
    assert "RecallEngine" in HEADER_ONLY
    assert body_contains(HEADER_ONLY, "RecallEngine") is False
    assert body_contains(HEADER_ONLY, "Other") is True
    # Тот чанк, где класс реально объявлен, совпадение даёт.
    assert body_contains(PREFIX + CLASS_BODY, "RecallEngine") is True


def test_empty_needle_never_matches():
    assert body_contains(HEADER_ONLY, "") is False


def _row(text: str, symbol: str, line: int) -> dict:
    return {"text_full": text,
            "metadata": {"file": "f.py", "symbol_name": symbol, "start_line": line,
                         "symbol_kind": "class_definition" if symbol else ""}}


def test_definition_chunk_beats_context_chunks():
    """Методы класса (`// Context: X`) не вытесняют единственное объявление."""
    rows = [
        _row("// Scope: function | d:x.py | Context: RecallEngine\ndef f(): ...",
             "f", 842),
        _row("// Scope: function | d:x.py | Context: RecallEngine\ndef g(): ...",
             "g", 1271),
        _row("// Scope: class | d:x.py\nclass RecallEngine:", "RecallEngine", 185),
    ]
    picked = name_rows(rows, "RecallEngine")
    assert len(picked) == 1, picked
    assert picked[0]["is_definition"] is True
    assert picked[0]["line"] == 185


def test_context_rows_are_capped_without_a_definition():
    rows = [
        _row("x = 'RecallEngine'\n", "some_var", 10),
        _row("y = 'RecallEngine'\n", "other_var", 20),
        _row("z = 'RecallEngine'\n", "third_var", 30),
    ]
    picked = name_rows(rows, "RecallEngine")
    assert len(picked) == 2, picked
    assert all(not p["is_definition"] for p in picked)


def test_prefix_only_rows_are_dropped():
    header_only = PREFIX.replace("class RecallEngine:\n    pass\n", "") \
        + "class Other:\n    pass\n"
    rows = [_row(header_only, "Other", 5)]
    assert name_rows(rows, "RecallEngine") == []


@pytest.mark.asyncio
async def test_related_rejects_a_symbol_instead_of_zero_results():
    tool = GraphQueryTool(MagicMock())
    result = await tool.execute(action="related", target="intent_recall")
    text = result if isinstance(result, str) else str(result)
    assert "VALIDATION_FAILED" in text
    assert "works on files" in text
    assert "related" in text


@pytest.mark.asyncio
async def test_related_accepts_a_file_path(tmp_path):
    """С файловым путём валидация пропускает дальше (пустой результат — ок)."""
    tool = GraphQueryTool(MagicMock())
    result = await tool.execute(action="related", target="src/core/mod.py",
                                project_root=str(tmp_path))
    text = result if isinstance(result, str) else str(result)
    assert "VALIDATION_FAILED" not in text
    assert "related" in text
