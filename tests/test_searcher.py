"""Тесты основного пути Searcher (src/core/search/engine.py).

Заменяет stub (B11, KNOWN_ISSUES.md): вместо `assert True` — реальные
проверки поискового движка без обращения к БД (мок indexer/embedder).

Не дублирует test_searcher_hardening.py (bucket weights, cache isolation,
async edge cases уже покрыты там) — здесь основной sync-путь.
"""

from unittest.mock import MagicMock

import pandas as pd

from src.core.search.engine import Searcher

_DIM = 768


def _chunk(file: str, score: float = 0.9) -> dict:
    return {
        "text": "def foo():\n    return 1",
        "text_full": "def foo():\n    return 1",
        "score": score,
        "final_score": score,
        "metadata": {
            "file": file,
            "chunk_index": 0,
            "indexed_at": "2026-07-31T00:00:00",
            "layer": "core",
            "hierarchy_level": "",
            "parent_id": "",
        },
    }


def _make_searcher():
    """Searcher без БД: indexer.table = None → vector_search возвращает []."""
    indexer = MagicMock()
    indexer.table = None
    embedder = MagicMock()
    searcher = Searcher(indexer, embedder)
    searcher._multi_reranker = None
    searcher._multi_reranker_initialized = True
    return searcher, indexer, embedder


# ─────────────────────────────────────────────────────────────
# vector_search
# ─────────────────────────────────────────────────────────────


def test_vector_search_no_table_returns_empty():
    """Нет таблицы (table=None) → пустой результат без исключений."""
    searcher, indexer, _ = _make_searcher()
    assert searcher.vector_search([0.0] * _DIM) == []


def test_vector_search_empty_index_returns_empty():
    """count_rows() == 0 → пустой результат (индекс пуст)."""
    searcher, indexer, _ = _make_searcher()
    indexer.table = MagicMock()
    indexer.table.count_rows.return_value = 0
    assert searcher.vector_search([0.0] * _DIM) == []


def test_vector_search_formats_rows():
    """Строки LanceDB превращаются в dict-результаты с метаданными."""
    searcher, indexer, _ = _make_searcher()
    df = pd.DataFrame(
        [
            {
                "_distance": 0.75,
                "text": "def foo(): return 1",
                "file_path": "src/a.py",
                "chunk_index": 2,
                "indexed_at": "2026-07-31T10:00:00",
                "layer": "core",
                "hierarchy_level": "function",
                "parent_id": "md5:parent",
            }
        ]
    )
    search_obj = MagicMock()
    search_obj.where.return_value = search_obj
    search_obj.limit.return_value = search_obj
    search_obj.to_pandas.return_value = df
    indexer.table = MagicMock()
    indexer.table.count_rows.return_value = 1
    indexer.table.search.return_value = search_obj

    results = searcher.vector_search([0.0] * _DIM, limit=5, filter_expr="layer = 'core'")

    assert len(results) == 1
    assert results[0]["text"] == "def foo(): return 1"
    assert results[0]["metadata"]["file"] == "src/a.py"
    assert results[0]["metadata"]["chunk_index"] == 2
    assert results[0]["metadata"]["layer"] == "core"


def test_vector_search_never_calls_db_limit_below_one():
    """limit <= 0 не должен ломать запрос (LanceDB требует limit >= 1)."""
    searcher, indexer, _ = _make_searcher()
    indexer.table = MagicMock()
    indexer.table.count_rows.return_value = 5
    search_obj = MagicMock()
    search_obj.where.return_value = search_obj
    search_obj.limit.return_value = search_obj
    search_obj.to_pandas.return_value = pd.DataFrame(
        columns=["_distance", "text", "file_path", "chunk_index"]
    )
    indexer.table.search.return_value = search_obj
    # Не должно падать с исключением — просто вернуть []
    assert searcher.vector_search([0.0] * _DIM, limit=0) == []


# ─────────────────────────────────────────────────────────────
# search (публичный markdown-вывод)
# ─────────────────────────────────────────────────────────────


def test_search_formats_results():
    """search() форматирует результаты в markdown с файлом и чанком."""
    searcher, _, _ = _make_searcher()
    searcher.hybrid_search = MagicMock(return_value=[_chunk("src/a.py")])
    out = searcher.search("query", limit=5)
    assert "Найдено 1" in out
    assert "src/a.py" in out
    assert "Чанк #0" in out


def test_search_empty_results_message():
    """Пустой результат → понятное сообщение, не exception."""
    searcher, _, _ = _make_searcher()
    searcher.hybrid_search = MagicMock(return_value=[])
    out = searcher.search("nothing here")
    assert "ничего не найдено" in out


def test_search_error_graceful():
    """Ошибка внутри поиска → '❌', а не propagation."""
    searcher, _, _ = _make_searcher()
    searcher.hybrid_search = MagicMock(side_effect=RuntimeError("boom"))
    out = searcher.search("query")
    assert out.startswith("❌")


def test_invalidate_cache_clears_entries():
    """invalidate_cache() очищает кэш результатов (P2-5)."""
    searcher, _, _ = _make_searcher()
    searcher._cache["fast:q:5::"] = (1.0, [])
    searcher.invalidate_cache()
    assert "fast:q:5::" not in searcher._cache


# ─────────────────────────────────────────────────────────────
# search_with_mode (fast)
# ─────────────────────────────────────────────────────────────


def test_search_with_mode_fast_calls_embed_and_vector():
    """fast-режим: embed → vector_search → bucket weights → результат."""
    searcher, _, embedder = _make_searcher()
    embedder.embed.return_value = [0.0] * _DIM
    searcher.vector_search = MagicMock(return_value=[_chunk("src/a.py")])
    searcher._fts5_search = MagicMock(return_value=[])

    res = searcher.search_with_mode("q", mode="fast", limit=5)

    assert res["mode"] == "fast"
    assert res["cache_hit"] is False
    assert len(res["results"]) == 1
    assert res["results"][0]["metadata"]["file"] == "src/a.py"
    searcher.vector_search.assert_called_once()


def test_search_with_mode_fast_sorts_distance_ascending():
    """fast-режим: сортировка по _distance ПО ВОЗРАСТАНИЮ (меньше = ближе).

    Регрессия v3.4.1: было sort(reverse=True) при cosine-семантике
    (_distance = 1 − cos_sim) → топ результатов инвертирован (худшие сверху).
    Проверено экспериментом lancedb 0.34.0: сам вектор = 0.0, близкий мал,
    ортогональный = 1.0; LanceDB сортирует ASC.
    """
    searcher, _, embedder = _make_searcher()
    embedder.embed.return_value = [0.0] * _DIM
    searcher.vector_search = MagicMock(
        return_value=[
            _chunk("far.py", score=1.9),
            _chunk("self.py", score=0.1),
            _chunk("near.py", score=1.0),
        ]
    )
    searcher._fts5_search = MagicMock(return_value=[])

    res = searcher.search_with_mode("q", mode="fast", limit=5)

    distances = [r["final_score"] for r in res["results"]]
    assert distances == sorted(distances), (
        f"fast-режим должен сортировать по возрастанию _distance, получено: {distances}"
    )
    assert res["results"][0]["metadata"]["file"] == "self.py"


def test_search_with_mode_fast_empty_embedding():
    """Пустой вектор эмбеддера → пустые результаты без поиска по БД."""
    searcher, _, embedder = _make_searcher()
    embedder.embed.return_value = []
    searcher.vector_search = MagicMock(return_value=[_chunk("src/a.py")])

    res = searcher.search_with_mode("q", mode="fast", limit=5)

    assert res["results"] == []
    searcher.vector_search.assert_not_called()


def test_search_with_mode_cache_hit_on_second_call():
    """Второй вызов с тем же ключом в пределах TTL → cache_hit=True."""
    searcher, _, embedder = _make_searcher()
    embedder.embed.return_value = [0.0] * _DIM
    searcher.vector_search = MagicMock(return_value=[_chunk("src/a.py")])
    searcher._fts5_search = MagicMock(return_value=[])

    first = searcher.search_with_mode("q", mode="fast", limit=5, layer="core")
    second = searcher.search_with_mode("q", mode="fast", limit=5, layer="core")

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["results"] == first["results"]
    searcher.vector_search.assert_called_once()
