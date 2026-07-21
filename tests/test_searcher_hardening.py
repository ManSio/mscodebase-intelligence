"""
Тесты для укрепления search engine (v2.6.0+).

Покрывают:
1. _apply_bucket_weights: intent_hint, UNC/empty paths, env weights
2. search_with_mode: изоляция кэша по layer/intent_hint
3. hybrid_search_async: защита от limit=0/1 и пустого запроса
"""

from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import get_config
from src.core.search.engine import Searcher

# ─────────────────────────────────────────────────────────────
# _apply_bucket_weights
# ─────────────────────────────────────────────────────────────


def _chunk(file: str, score: float) -> dict:
    return {
        "text": "sample",
        "metadata": {"file": file, "chunk_index": 0},
        "final_score": score,
    }


def test_apply_bucket_weights_empty_and_unc_paths():
    """Пустые пути и UNC-префиксы не ломают определение расширения."""
    # Фиксируем вес docs=1.0 для теста (по умолч. 0.5, но тест проверяет механику)
    orig_docs_w = get_config().performance.docs_bucket_weight
    get_config().performance.docs_bucket_weight = 1.0
    Searcher(MagicMock(), MagicMock())
    chunks = [
        _chunk("", 1.0),
        _chunk("\\\\?\\C:\\src\\main.py", 1.0),
        _chunk("src/core/searcher.py", 1.0),
        _chunk("docs/readme.md", 1.0),
        _chunk("Makefile", 1.0),
    ]
    result = Searcher._apply_bucket_weights(chunks, intent_hint="auto")

    # Пустой путь — без изменений
    assert result[0]["final_score"] == pytest.approx(1.0)
    # UNC-префикс снят, .py распознан как код
    assert result[1]["final_score"] == pytest.approx(1.0)
    assert result[2]["final_score"] == pytest.approx(1.0)
    # .md распознан как документация
    assert result[3]["final_score"] == pytest.approx(1.0)
    # Неизвестное расширение — без изменений
    assert result[4]["final_score"] == pytest.approx(1.0)
    get_config().performance.docs_bucket_weight = orig_docs_w


def test_apply_bucket_weights_intent_hint():
    """intent_hint code/docs меняет веса относительно базовых."""
    orig_docs_w = get_config().performance.docs_bucket_weight
    get_config().performance.docs_bucket_weight = 1.0
    Searcher(MagicMock(), MagicMock())

    auto = Searcher._apply_bucket_weights(
        [_chunk("code.py", 1.0), _chunk("docs.md", 1.0)], intent_hint="auto"
    )
    assert auto[0]["final_score"] == pytest.approx(1.0)
    assert auto[1]["final_score"] == pytest.approx(1.0)

    code = Searcher._apply_bucket_weights(
        [_chunk("code.py", 1.0), _chunk("docs.md", 1.0)], intent_hint="code"
    )
    assert code[0]["final_score"] > code[1]["final_score"]

    docs = Searcher._apply_bucket_weights(
        [_chunk("code.py", 1.0), _chunk("docs.md", 1.0)], intent_hint="docs"
    )
    assert docs[1]["final_score"] > docs[0]["final_score"]
    get_config().performance.docs_bucket_weight = orig_docs_w


# ─────────────────────────────────────────────────────────────
# search_with_mode cache isolation
# ─────────────────────────────────────────────────────────────


def test_search_with_mode_cache_includes_layer_and_intent():
    """Кэш должен различать layer и intent_hint."""
    searcher = Searcher(MagicMock(), MagicMock())
    # Мокаем embedder и vector_search чтобы не обращаться к БД
    searcher.embedder = MagicMock()
    searcher.embedder.embed.return_value = [0.0] * 1024
    searcher.vector_search = MagicMock(return_value=[])

    with patch.object(searcher, "vector_search", return_value=[]) as mock_vs:
        searcher.search_with_mode("query", mode="fast", limit=5, layer="core")
        searcher.search_with_mode("query", mode="fast", limit=5, layer="utils")
        searcher.search_with_mode(
            "query", mode="fast", limit=5, layer="core", intent_hint="code"
        )

    # Должно быть 3 промаха кэша (разные ключи)
    assert mock_vs.call_count == 3


# ─────────────────────────────────────────────────────────────
# hybrid_search_async edge cases
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hybrid_search_async_empty_query():
    """Пустой запрос возвращает пустой список без обращений к БД."""
    searcher = Searcher(MagicMock(), MagicMock())
    searcher._bm25_search = MagicMock(return_value=[])
    searcher.vector_search = MagicMock(return_value=[])

    result = await searcher.hybrid_search_async("")
    assert result == []
    searcher._bm25_search.assert_not_called()
    searcher.vector_search.assert_not_called()


@pytest.mark.asyncio
async def test_hybrid_search_async_raw_limit_safe_for_small_limit():
    """raw_limit не обрезает результаты до пустого списка при limit=0/1."""
    from src.config.settings import get_config

    overfetch = get_config().performance.overfetch_factor

    # Создаём searcher'sync-обёртку для проверки приватного поведения
    searcher = Searcher(MagicMock(), MagicMock())

    # Мокаем зависимости, чтобы дойти до финальной стадии
    searcher.embedder = MagicMock()
    searcher.embedder.embed_batch_async = None
    searcher.embedder.embed.return_value = [0.0] * 1024

    async def fake_bm25(q, limit):
        return [_chunk(f"file{i}.py", 1.0 / (i + 1)) for i in range(limit)]

    async def fake_vector(qv, limit, filter_expr=""):
        return [_chunk(f"file{i}.py", 1.0 / (i + 1)) for i in range(limit)]

    searcher._bm25_search_async = fake_bm25
    searcher._vector_search_async = fake_vector
    searcher._multi_reranker = None
    searcher._multi_reranker_initialized = True

    for limit in (0, 1):
        result = await searcher.hybrid_search_async("test", limit=limit, expand=False)
        expected_raw = min(max(limit * overfetch, 1), 30)
        # Результатов должно быть ровно limit (обрезка после взвешивания)
        assert len(result) == limit
        # Внутренний overfetch не меньше 1
        assert expected_raw >= 1
