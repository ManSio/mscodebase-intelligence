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


# ════════════════════════════════════════════════════════════════
# E17: TESTS-сигнал — покрывающие тесты в graph-stage под флагом
# ════════════════════════════════════════════════════════════════

class _NoTestsIndexer:
    """symbol_index без метода get_tests_for_symbol — старый контракт."""

    _symbol_index = None


def _make_searcher_with_flag(indexer, flag):
    class _FakeEmbedderNoCall:
        def embed(self, *a, **k):
            raise AssertionError("embedder не должен вызываться")

        def embed_batch_async(self, *a, **k):
            raise AssertionError("embedder не должен вызываться")

    s = Searcher(indexer, _FakeEmbedderNoCall())
    s._tests_signal = flag
    return s


@pytest.fixture
def searcher_with_tests(tmp_path):
    """Граф: функция + два теста, покрывающих её (TESTS-рёбра)."""
    db = tmp_path / "graph.db"
    pg = PropertyGraph(str(db))
    # Функция в src/
    pg.add_node(
        name="safe_mkdir", label="Function", qualified_name="D:.D:/Project/src/core/paths.py.safe_mkdir",
        file_path="D:/Project/src/core/paths.py",
        properties={"line": 42, "kind": "function"},
    )
    # Тесты, покрывающие функцию
    t1 = pg.add_node(
        name="test_safe_mkdir_creates", label="Test",
        qualified_name="D:.D:/Project/tests/test_paths.py.test_safe_mkdir_creates",
        file_path="D:/Project/tests/test_paths.py",
        properties={"line": 10},
    )
    t2 = pg.add_node(
        name="test_safe_mkdir_idempotent", label="Test",
        qualified_name="D:.D:/Project/tests/test_paths.py.test_safe_mkdir_idempotent",
        file_path="D:/Project/tests/test_paths.py",
        properties={"line": 20},
    )
    pg.add_edge(source_qname=t1.qualified_name, target_qname="D:.D:/Project/src/core/paths.py.safe_mkdir",
                type="TESTS", weight=1.0, properties={"trace": "dynamic_trace"})
    pg.add_edge(source_qname=t2.qualified_name, target_qname="D:.D:/Project/src/core/paths.py.safe_mkdir",
                type="TESTS", weight=1.0, properties={"trace": "dynamic_trace"})
    adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)

    class _Idx:
        _symbol_index = adapter

    s = _make_searcher_with_flag(_Idx(), flag=True)
    yield s, adapter, pg
    pg.close()


def test_tests_signal_adds_covering_tests(searcher_with_tests):
    """К определению функции добавляются покрывающие тесты."""
    s, adapter, _ = searcher_with_tests
    results = s._graph_stage("safe_mkdir", limit=5)
    test_refs = [r for r in results if r["metadata"].get("tests_signal")]
    assert len(test_refs) >= 1, f"TESTS-сигнал не сработал: {results}"
    any(
        t["metadata"]["symbol"].startswith("test_safe_mkdir")
        for t in test_refs
    ), f"ожидался тест safe_mkdir: {test_refs}"
    for t in test_refs:
        assert t["metadata"]["chunk_index"] < -10_000_000  # отдельный sentinel-диапазон
        assert t["metadata"]["is_definition"] is False
        assert t["metadata"]["covers"] == "safe_mkdir"
        assert t["metadata"]["kind"] == "test"


def test_tests_signal_def_first_then_tests(searcher_with_tests):
    """Функция-определение стоит ДО тестов (тесты не вытесняют)."""
    s, _, _ = searcher_with_tests
    results = s._graph_stage("safe_mkdir", limit=5)
    assert results[0]["metadata"]["symbol"] == "safe_mkdir"
    assert results[0]["metadata"]["is_definition"] is True
    r0_score = results[0]["graph_score"]
    for t in results[1:]:
        if t["metadata"].get("tests_signal"):
            assert t["graph_score"] < r0_score


def test_tests_signal_flag_off_unchanged(searcher_with_tests):
    """Флаг off → тесты НЕ добавляются (поведение флага по умолчанию)."""
    s, adapter, _ = searcher_with_tests
    s._tests_signal = False
    results = s._graph_stage("safe_mkdir", limit=5)
    assert all(not r["metadata"].get("tests_signal") for r in results)
    assert results[0]["metadata"]["symbol"] == "safe_mkdir"


def test_tests_signal_no_method_fallback():
    """symbol_index без get_tests_for_symbol → результаты без изменений."""
    s = _make_searcher_with_flag(_NoTestsIndexer(), flag=True)
    # _graph_stage с пустым индексом вернёт [] — это graceful degradation, без падения
    assert s._graph_stage("anything", limit=5) == []


def test_get_tests_for_symbol_hit(searcher_with_tests):
    """Адаптер напрямую: возвращает покрывающие тесты."""
    s, adapter, _ = searcher_with_tests
    refs = adapter.get_tests_for_symbol("safe_mkdir", "D:/Project/src/core/paths.py", limit=3)
    names = {r.symbol for r in refs}
    assert "test_safe_mkdir_creates" in names
    assert "test_safe_mkdir_idempotent" in names
    for r in refs:
        assert r.kind == "test"
        assert r.is_definition is True


def test_get_tests_for_symbol_miss(searcher_with_tests):
    """Неизвестный символ → []."""
    s, adapter, _ = searcher_with_tests
    assert adapter.get_tests_for_symbol("nonexistent_xyz", "D:/Project/src/core/paths.py") == []
