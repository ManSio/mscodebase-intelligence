"""Регресс-тест KNOWN_ISSUES#2026-08-11: кэш-хит эмбеддинга не должен
пропускать dense-поиск (vector-тир молча исчезал при повторном запросе).

Покрывает (AGENTS.md §5.13 — корректность содержимого, не только "не упало"):
1. Кэш-хит: _vector_search_async ВЫЗЫВАЕТСЯ, embedder НЕ вызывается,
   dense-результат попадает в выдачу.
2. Контроль cache-miss: свежий эмбеддинг тоже даёт dense-результаты.
3. Провал эмбеддинга (query_vector=None) не роняет поиск.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.core.search.engine import Searcher, _cache_key


def _make_searcher():
    searcher = Searcher(MagicMock(), MagicMock())
    searcher._bm25_search_async = AsyncMock(return_value=[])
    searcher._fts5_search_async = AsyncMock(return_value=[])
    searcher._ensure_multi_reranker_async = AsyncMock(return_value=None)
    searcher._apply_multi_reranker_async = AsyncMock(
        side_effect=lambda q, res, lim: res
    )
    return searcher


def _dense_result(file="cache_hit.py"):
    return {
        "text": "dense result",
        "metadata": {"file": file, "chunk_index": 0},
        "dense_score": 0.9,
        "final_score": 0.9,
    }


def test_cache_hit_runs_dense_search_and_keeps_results():
    """Кэш-хит эмбеддинга НЕ должен молча терять vector-тир."""
    searcher = _make_searcher()
    query = "аутентификация и права"
    # Предзаполняем кэш — повторный запрос с тем же текстом = кэш-хит
    searcher._embedding_cache[_cache_key(query)] = [0.1, 0.2, 0.3]

    dense = _dense_result()
    searcher._vector_search_async = AsyncMock(return_value=[dense])

    results = asyncio.run(searcher.hybrid_search_async(query, limit=5))

    # 1) dense-поиск реально выполнен при кэш-хите
    searcher._vector_search_async.assert_awaited_once()
    # 2) эмбеддер не вызывался (вектор взят из кэша)
    searcher.embedder.embed_batch_async.assert_not_called()
    searcher.embedder.embed.assert_not_called()
    # 3) корректность содержимого: dense-результат присутствует в выдаче
    assert any(
        r["metadata"].get("file") == "cache_hit.py" for r in results
    ), "dense-результат пропал из выдачи при кэш-хите"


def test_cache_miss_also_runs_dense_search():
    """Контроль: свежий эмбеддинг (cache miss) даёт dense-результаты."""
    searcher = _make_searcher()
    query = "свежий запрос"

    async def fake_embed_batch(texts, is_query=True):
        return [[0.5, 0.6, 0.7] for _ in texts]

    searcher.embedder.embed_batch_async = fake_embed_batch
    dense = _dense_result(file="cache_miss.py")
    searcher._vector_search_async = AsyncMock(return_value=[dense])

    results = asyncio.run(searcher.hybrid_search_async(query, limit=5))

    searcher._vector_search_async.assert_awaited_once()
    assert any(r["metadata"].get("file") == "cache_miss.py" for r in results)


def test_embed_failure_does_not_break_search():
    """Провал эмбеддинга (query_vector=None) не роняет поиск."""
    searcher = _make_searcher()
    searcher.embedder.embed_batch_async = AsyncMock(return_value=[])
    searcher._vector_search_async = AsyncMock(return_value=[])

    results = asyncio.run(
        searcher.hybrid_search_async("не эмбеддится", limit=5)
    )

    # dense не вызван с None (guard is not None), поиск вернул пусто без исключений
    assert results == []


def test_two_identical_queries_both_keep_dense_results():
    """Guard из KNOWN_ISSUES/WISDOM: два подряд одинаковых запроса → оба с dense."""
    searcher = _make_searcher()
    query = "повторный запрос"
    dense_a = _dense_result(file="first_call.py")
    dense_b = _dense_result(file="second_call.py")
    searcher._vector_search_async = AsyncMock(
        side_effect=[[dense_a], [dense_b]]
    )

    async def fake_embed_batch(texts, is_query=True):
        return [[0.5, 0.6, 0.7] for _ in texts]

    searcher.embedder.embed_batch_async = fake_embed_batch

    first = asyncio.run(searcher.hybrid_search_async(query, limit=5))
    second = asyncio.run(searcher.hybrid_search_async(query, limit=5))

    # Первый вызов — кэш-мисс (свежий эмбеддинг), второй — кэш-хит
    assert any(r["metadata"].get("file") == "first_call.py" for r in first)
    assert any(r["metadata"].get("file") == "second_call.py" for r in second)
