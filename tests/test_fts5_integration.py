"""
Тесты интеграции FTS5 в hybrid_search_async (этап Б).

Покрывают (AGENTS.md §5.13 — корректность содержимого, не только "не упало"):
1. FTS5-результаты попадают в выдачу search_with_mode с source="fts5_hybrid".
2. Правильный вход -> правильный выход (символ из FTS5 совпадает с запросом).
3. Защита от таймаута: _fts5_search_async, превышающий 2s, не ломает основной поиск.
4. 3-way RRF корректно объединяет bm25 + dense + fts5 (ключи file:chunk_index).
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.core.search.engine import Searcher
from src.core.search.scoring import reciprocal_rank_fusion_3way
from src.core.search.fts5_index import FTS5IndexManager


def _make_searcher_with_fts5(chunks):
    """Searcher с предзаполненным FTS5-индексом (без реального LanceDB)."""
    searcher = Searcher(MagicMock(), MagicMock())
    # Отключаем reindex-guard: у MagicMock db_manager.is_reindexing() иначе truthy
    searcher.indexer.db_manager.is_reindexing = MagicMock(return_value=False)
    mgr = FTS5IndexManager(in_memory=True)
    mgr.build_index(chunks)
    searcher._fts5 = mgr
    return searcher


def _sample_chunks():
    return [
        {
            "file_path": "src/core/search/engine.py",
            "chunk_index": 7,
            "text": "class Searcher(BM25Mixin, FTS5Mixin):\n    def hybrid_search(self): ...",
            "symbol_name": "hybrid_search",
            "symbol_kind": "function",
            "docstring": "Гибридный поиск по кодовой базе.",
            "layer": "core",
        },
        {
            "file_path": "src/core/search/fts5_index.py",
            "chunk_index": 3,
            "text": "class FTS5IndexManager:\n    def build_index(self): ...",
            "symbol_name": "build_index",
            "symbol_kind": "function",
            "docstring": "Build all 3 FTS5 indexes.",
            "layer": "core",
        },
    ]


def test_fts5_results_present_in_search_with_mode():
    """FTS5-результаты реально участвуют в выдаче search_with_mode."""
    searcher = _make_searcher_with_fts5(_sample_chunks())
    # Мокаем bm25/dense, чтобы изолировать FTS5-вклад
    searcher._bm25_search_async = MagicMock(return_value=asyncio.sleep(0, result=[]))
    searcher._vector_search_async = MagicMock(return_value=asyncio.sleep(0, result=[]))
    searcher._ensure_multi_reranker_async = MagicMock(return_value=asyncio.sleep(0, result=None))
    searcher._apply_multi_reranker_async = MagicMock(
        side_effect=lambda q, res, lim: asyncio.sleep(0, result=res)
    )

    res = searcher.search_with_mode("hybrid_search", mode="quality", limit=6)
    results = res.get("results", [])
    assert results, "ожидались результаты от FTS5"

    fts5 = [r for r in results if r.get("metadata", {}).get("source") == "fts5_hybrid"]
    assert fts5, "ни один результат не помечен source=fts5_hybrid"
    # Корректность: запрос 'hybrid_search' -> символ hybrid_search присутствует
    assert any(
        r["metadata"].get("symbol_name") == "hybrid_search" for r in fts5
    )


def test_fts5_correctness_no_cross_contamination():
    """Правильный запрос -> правильный символ (без перемешивания векторов)."""
    searcher = _make_searcher_with_fts5(_sample_chunks())
    searcher._bm25_search_async = MagicMock(return_value=asyncio.sleep(0, result=[]))
    searcher._vector_search_async = MagicMock(return_value=asyncio.sleep(0, result=[]))
    searcher._ensure_multi_reranker_async = MagicMock(return_value=asyncio.sleep(0, result=None))
    searcher._apply_multi_reranker_async = MagicMock(
        side_effect=lambda q, res, lim: asyncio.sleep(0, result=res)
    )

    res = searcher.search_with_mode("build_index", mode="quality", limit=6)
    results = res.get("results", [])
    fts5 = [r for r in results if r.get("metadata", {}).get("source") == "fts5_hybrid"]
    assert fts5
    # Запрос build_index НЕ должен возвращать hybrid_search как fts5-результат
    assert all(r["metadata"].get("symbol_name") == "build_index" for r in fts5)


def test_fts5_timeout_does_not_break_search():
    """Если FTS5 тормозит >2s, основной поиск продолжается (degraded)."""
    searcher = _make_searcher_with_fts5(_sample_chunks())

    async def _slow_fts5(*a, **k):
        await asyncio.sleep(5)  # имитируем зависание
        return []

    searcher._fts5_search_async = _slow_fts5
    # bm25 возвращает реальный результат, чтобы проверить, что поиск жив
    searcher._bm25_search_async = MagicMock(
        return_value=asyncio.sleep(
            0,
            result=[
                {
                    "text": "x",
                    "metadata": {"file": "a.py", "chunk_index": 0},
                    "bm25_score": 1.0,
                    "dense_score": 0.0,
                    "final_score": 1.0,
                }
            ],
        )
    )
    searcher._vector_search_async = MagicMock(return_value=asyncio.sleep(0, result=[]))
    searcher._ensure_multi_reranker_async = MagicMock(return_value=asyncio.sleep(0, result=None))
    searcher._apply_multi_reranker_async = MagicMock(
        side_effect=lambda q, res, lim: asyncio.sleep(0, result=res)
    )

    res = searcher.search_with_mode("anything", mode="quality", limit=6)
    results = res.get("results", [])
    # Основной поиск (bm25) жив, несмотря на зависший FTS5
    assert any(r["metadata"].get("file") == "a.py" for r in results)


def test_rrf_3way_merges_three_sources():
    """3-way RRF объединяет bm25 + dense + fts5 по ключу file:chunk_index."""
    bm25 = [{"text": "t", "metadata": {"file": "f.py", "chunk_index": 0}, "bm25_score": 1.0, "dense_score": 0.0, "final_score": 1.0}]
    dense = [{"text": "t", "metadata": {"file": "g.py", "chunk_index": 1}, "bm25_score": 0.0, "dense_score": 1.0, "final_score": 1.0}]
    fts5 = [{"text": "t", "metadata": {"file": "h.py", "chunk_index": 2, "source": "fts5_hybrid"}, "bm25_score": 0.0, "dense_score": 0.0, "fts5_score": 1.0, "final_score": 1.0}]

    merged = reciprocal_rank_fusion_3way(bm25, dense, fts5, limit=10)
    files = {r["metadata"]["file"] for r in merged}
    assert {"f.py", "g.py", "h.py"} <= files
    # fts5-результат сохраняет свой source
    assert any(r["metadata"].get("source") == "fts5_hybrid" for r in merged)
