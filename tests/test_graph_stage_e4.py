"""Регрессионный тест Symbol Graph Path (Вариант А, Step 2 / E4.1).

Проверяет, что граф-стадия:
1. Возвращает детерминированные symbol-указатели (file:line) для идентификатор-запросов.
2. Возвращает [] для неизвестных символов и при отсутствии индекса (graceful degradation).
3. Short-circuit в hybrid_search_async отдаёт граф-результат БЕЗ вызова embedder
   (доказывает отказ от тяжёлого векторного поиска ~3600ms).
"""
import asyncio
import pytest

from src.core.graph import PropertyGraph
from src.core.search.engine import Searcher
from src.core.search.graph_adapter import SymbolIndexAdapter


class _FakeEmbedder:
    """embed БРОСАЕТ — чтобы доказать, что граф-short-circuit не доходит до вектора."""

    def embed(self, *a, **k):
        raise AssertionError("embedder не должен вызываться при graph short-circuit")

    def embed_batch_async(self, *a, **k):
        raise AssertionError("embedder не должен вызываться при graph short-circuit")


def _make_searcher(symbol_index):
    class _FakeIndexer:
        _symbol_index = symbol_index

    return Searcher(_FakeIndexer(), _FakeEmbedder())


@pytest.fixture
def searcher_with_graph(tmp_path):
    db = tmp_path / "graph.db"
    pg = PropertyGraph(str(db))
    pg.add_node(
        name="save_symbol_index", label="Function", qualified_name="save_symbol_index",
        file_path="src/core/indexing/index_guard.py",
        properties={"line": 353, "kind": "function"},
    )
    pg.add_node(
        name="resolve_indexer", label="Function", qualified_name="resolve_indexer",
        file_path="src/mcp/tools/base.py",
        properties={"line": 245, "kind": "function"},
    )
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    s = _make_searcher(adapter)
    yield s
    pg.close()


def test_graph_stage_returns_symbol_pointers(searcher_with_graph):
    results = searcher_with_graph._graph_stage("save_symbol_index", limit=5)
    assert len(results) >= 1
    r = results[0]
    assert r["metadata"]["symbol"] == "save_symbol_index"
    assert r["metadata"]["symbol_name"] == "save_symbol_index"
    assert r["metadata"]["is_symbol_ref"] is True
    assert r["metadata"]["graph_stage"] is True
    assert "index_guard.py" in r["metadata"]["file"]
    assert r["metadata"]["layer"] == "core"
    # sentinel chunk_index — отрицательный (уникален vs реальных чанков)
    assert r["metadata"]["chunk_index"] < 0
    assert "📍" in r["text"]


def test_graph_stage_unknown_empty(searcher_with_graph):
    assert searcher_with_graph._graph_stage("nonexistent_xyz_123", limit=5) == []


def test_graph_stage_no_index():
    s = _make_searcher(None)
    assert s._graph_stage("anything", limit=5) == []


def test_graph_stage_layer_filter(searcher_with_graph):
    # layer="mcp" не совпадает с core → пусто (защита от смешивания слоёв)
    assert searcher_with_graph._graph_stage("save_symbol_index", limit=5, layer="mcp") == []
    # layer=None или "core" → находит
    assert len(searcher_with_graph._graph_stage("save_symbol_index", limit=5, layer="core")) >= 1


def test_short_circuit_identifier_no_embedder(searcher_with_graph):
    """Идентификатор-запрос → граф-short-circuit, embedder НЕ вызывается."""
    results = asyncio.run(
        searcher_with_graph.hybrid_search_async("save_symbol_index", limit=5)
    )
    assert len(results) >= 1
    assert results[0]["metadata"]["graph_stage"] is True
    assert "index_guard.py" in results[0]["metadata"]["file"]
