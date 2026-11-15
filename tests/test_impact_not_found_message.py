"""Guard: impact_analysis различает «символ не тот» и «символьный слой пуст».

Замер 2026-11-16: у 4 из 7 реальных проектов `graph.db` пуст (0 узлов) при живых
чанках. Инструмент отвечал «Symbol 'X' not found in index» — пользователь
проверял имя символа, хотя нужно было переиндексировать проект.
"""
from __future__ import annotations

from src.mcp.tools.search_tools import _impact_not_found_payload


def test_empty_symbol_layer_points_to_reindex():
    payload = _impact_not_found_payload("as_dict", 0)

    assert payload["status"] == "warning"
    assert "Символьный слой пуст" in payload["message"]
    assert "as_dict" in payload["message"]
    assert "codebase(action='index'" in payload["next_step"]


def test_known_symbol_layer_points_to_name_lookup():
    payload = _impact_not_found_payload("as_dict", 3018)

    assert "not found in index" in payload["message"]
    assert "search_code" in payload["next_step"]


def test_unknown_symbol_count_does_not_claim_the_layer_is_empty():
    """Если счётчик недоступен (-1), нельзя утверждать, что слой пуст."""
    payload = _impact_not_found_payload("as_dict", -1)
    assert "Символьный слой пуст" not in payload["message"]
