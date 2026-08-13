"""Задача 5/5 «Граф в центре»: регрессионные тесты.

Проверяет 4 фикса, сделанных для включения PropertyGraph во ВСЕ режимы
поиска (fast/auto-simple), а не только quality/deep:

- Fix A (parser.py): CALLS-рёбра из методов квалифицируются классом
  ("Class.method"). Без этого ребро не находит узел определения
  (узлы хранятся с qualified name) и молча дропается add_edge() —
  в графе было 0 CALLS-рёбер в методы.
- Fix B (graph_adapter_pure._pure_add_references): suffix-поиск callee
  ("%.bar") при exact-промахе — методы резолвятся в реальные узлы,
  а не в __extern__-заглушки.
- Fix C (graph_adapter_pure._find_nodes_flexible): find_references /
  get_call_chain / find_definitions находят qualified-узлы по голому имени.
- Fix D (engine): _expand_graph_context обогащает metadata["callers"];
  fast-путь search_with_mode(mode="fast") применяет граф-обогащение.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def pg():
    """PropertyGraph с временной SQLite БД."""
    from src.core.graph import PropertyGraph

    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    graph = PropertyGraph(tmp)
    _ = graph._get_conn()  # форсируем инициализацию SQLite
    yield graph
    graph.close()
    Path(tmp).unlink(missing_ok=True)


@pytest.fixture
def adapter(pg):
    """SymbolIndexAdapter в PURE mode (как в Indexer.__init__)."""
    from src.core.search.graph_adapter import SymbolIndexAdapter

    return SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)


class TestGraphCenter:
    """Fix A: квалификация методов классом при извлечении CALLS."""

    def test_parser_method_calls_qualified_by_class(self, tmp_path):
        """Метод, вызывающий другой метод, эмитит caller 'Class.method'."""
        pytest.importorskip("tree_sitter")
        from src.core.indexing.parser import CodeParser

        src = tmp_path / "calc.py"
        src.write_text(
            "class Calculator:\n"
            "    def add(self, a, b):\n"
            "        return a + b\n"
            "\n"
            "    def double(self, x):\n"
            "        return self.add(x, x)\n",
            encoding="utf-8",
        )

        calls = CodeParser().extract_calls(src)
        qualified = [c for c in calls if c["caller"] == "Calculator.double"]
        assert qualified, (
            f"caller должен быть квалифицирован классом ('Calculator.double'), "
            f"получено: {calls}"
        )
        assert qualified[0]["callee"] == "add"

    def test_parser_top_level_function_stays_bare(self, tmp_path):
        """Top-level функция НЕ должна получать класс — регрессия Fix A."""
        pytest.importorskip("tree_sitter")
        from src.core.indexing.parser import CodeParser

        src = tmp_path / "module.py"
        src.write_text(
            "def helper():\n"
            "    return 1\n"
            "\n"
            "def main():\n"
            "    return helper()\n",
            encoding="utf-8",
        )

        calls = CodeParser().extract_calls(src)
        main_calls = [c for c in calls if c["caller"] == "main"]
        assert main_calls, f"top-level caller 'main' не найден: {calls}"
        assert main_calls[0]["callee"] == "helper"

    """Fix B: callee-методы резолвятся в реальные узлы, не __extern__."""

    def test_method_ref_resolves_to_real_node_not_extern(self, adapter):
        """add_references(caller='Class.method', callee='bare') → ребро
        в реальный узел Class.method, а не __extern__-заглушку."""
        adapter.add_definitions("/project/a.py", [
            {"name": "Calculator.add", "line": 10, "kind": "method"},
            {"name": "Calculator.double", "line": 20, "kind": "method"},
        ])
        adapter.add_references("/project/a.py", [
            {"caller": "Calculator.double", "callee": "add", "line": 15}
        ])

        refs = adapter.find_references("add")
        assert len(refs) == 1, f"должно быть 1 reference, получено: {refs}"
        assert refs[0].symbol == "Calculator.double"

        # Реальный узел существует (qualified), extern-заглушки нет
        nodes = adapter._graph.find_nodes(name_pattern="%.add")
        assert any(n.qualified_name.endswith("Calculator.add") for n in nodes), (
            f"узел Calculator.add не найден: {nodes}"
        )
        externs = adapter._graph.find_nodes(name_pattern="__extern__")
        assert not any("add" in n.name for n in externs), (
            f"callee 'add' ошибочно стал __extern__ заглушкой: {externs}"
        )

    """Fix C: suffix-поиск qualified-узлов по голому имени."""

    def test_find_references_by_bare_name_finds_qualified_method(self, adapter):
        """find_references('search_with_mode') находит узел
        'Searcher.search_with_mode' (как в реальном graph.db)."""
        adapter.add_definitions("/project/a.py", [
            {"name": "Searcher.search_with_mode", "line": 706, "kind": "method"}
        ])
        adapter.add_definitions("/project/b.py", [
            {"name": "search_code", "line": 1, "kind": "function"}
        ])
        adapter.add_references("/project/b.py", [
            {"caller": "search_code", "callee": "search_with_mode", "line": 42}
        ])

        refs = adapter.find_references("search_with_mode")
        assert len(refs) == 1, (
            f"bare name должен находить qualified узел: {refs}"
        )
        assert refs[0].symbol == "search_code"

    def test_find_definitions_and_call_chain_suffix(self, adapter):
        """find_definitions / get_call_chain находят qualified-узлы."""
        adapter.add_definitions("/project/a.py", [
            {"name": "Calculator.add", "line": 10, "kind": "method"},
            {"name": "Calculator.double", "line": 20, "kind": "method"},
        ])
        adapter.add_references("/project/a.py", [
            {"caller": "Calculator.double", "callee": "add", "line": 25}
        ])

        defs = adapter.find_definitions("add")
        assert any(d.symbol == "Calculator.add" for d in defs), (
            f"find_definitions('add') не вернул qualified узел: {defs}"
        )

        chain = adapter.get_call_chain("add", direction="up", max_depth=2)
        caller_names = [c["symbol"] for c in chain["callers_chain"]]
        assert "Calculator.double" in caller_names, (
            f"callers_chain не содержит Calculator.double: {chain}"
        )

    """Fix D: граф-обогащение в каждом режиме поиска."""

    def _build_searcher_with_graph(self, adapter):
        """Searcher с реальным SymbolIndexAdapter как indexer._symbol_index.

        Важно: MagicMock indexer без _symbol_index вернул бы truthy MagicMock
        и _expand_graph_context ушёл бы в fallback-ветку — здесь реальный
        адаптер на tmp-графе.
        """
        from src.core.search.engine import Searcher

        indexer = MagicMock()
        indexer.db_manager = None  # без БД → reindex fast-fail не срабатывает
        indexer._symbol_index = adapter
        embedder = MagicMock()
        embedder.embed.return_value = [0.1] * 32
        return Searcher(indexer, embedder)

    def test_expand_graph_context_adds_callers_metadata(self, adapter):
        """_expand_graph_context обогащает metadata['callers']."""
        adapter.add_definitions("/project/a.py", [
            {"name": "Calculator.add", "line": 10, "kind": "method"},
            {"name": "Calculator.double", "line": 20, "kind": "method"},
        ])
        adapter.add_references("/project/a.py", [
            {"caller": "Calculator.double", "callee": "add", "line": 15}
        ])

        searcher = self._build_searcher_with_graph(adapter)
        results = [
            {"metadata": {"file": "a.py", "chunk_index": 0},
             "text": "def add(self, a, b):\n    return a + b\n",
             "final_score": 0.9}
        ]
        out = searcher._expand_graph_context(results, "add method")
        callers = out[0]["metadata"].get("callers")
        assert callers, "metadata должен быть обогащён callers"
        assert callers[0]["symbol"] == "Calculator.double"

    def test_fast_search_applies_graph_expansion(self, adapter):
        """search_with_mode(mode='fast') обогащает результаты графом."""
        adapter.add_definitions("/project/a.py", [
            {"name": "Calculator.add", "line": 10, "kind": "method"},
            {"name": "Calculator.double", "line": 20, "kind": "method"},
        ])
        adapter.add_references("/project/a.py", [
            {"caller": "Calculator.double", "callee": "add", "line": 15}
        ])

        searcher = self._build_searcher_with_graph(adapter)
        fake_results = [
            {"metadata": {"file": "a.py", "chunk_index": 0},
             "text": "def add(self, a, b):\n    return a + b\n",
             "final_score": 0.9}
        ]
        with patch.object(searcher, "vector_search", return_value=fake_results):
            with patch.object(searcher, "_fts5_search", return_value=None):
                resp = searcher.search_with_mode("add", limit=5, mode="fast")

        assert resp["results"], "fast-путь должен вернуть результаты"
        callers = resp["results"][0]["metadata"].get("callers")
        assert callers, f"fast-путь должен обогатить callers: {resp['results'][0]}"
        assert callers[0]["symbol"] == "Calculator.double"
        assert "graph_expansion_ms" in resp["timing_ms"], (
            "fast-путь должен замерить graph_expansion_ms"
        )

    def test_expand_graph_context_no_symbol_index_is_noop(self):
        """Без SymbolIndex (indexer без _symbol_index) — no-op, не crash."""
        from src.core.search.engine import Searcher

        indexer = MagicMock()
        del indexer._symbol_index  # убираем truthy MagicMock
        searcher = Searcher(indexer, MagicMock())
        results = [
            {"metadata": {"file": "a.py", "chunk_index": 0},
             "text": "def foo():\n    pass\n",
             "final_score": 0.9}
        ]
        out = searcher._expand_graph_context(results, "foo")
        assert out == results, "noop должен вернуть результаты как есть"
