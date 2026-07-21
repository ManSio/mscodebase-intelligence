"""
Тесты для RepoRank — PageRank на графе вызовов.
"""

from src.core.indexing.symbol_index import SymbolRef, SymbolIndex


class TestRepoRank:
    """Тесты compute_repo_rank."""

    def test_empty_graph(self):
        """Пустой граф — пустой результат."""
        index = SymbolIndex()
        ranks = index.compute_repo_rank()
        assert ranks == {}

    def test_single_symbol(self):
        """Один символ без связей."""
        index = SymbolIndex()
        index.add_definitions("test.py", [
            {"name": "foo", "line": 1, "kind": "function"},
        ])
        ranks = index.compute_repo_rank()
        assert "foo" in ranks
        assert ranks["foo"] == 1.0  # Нормализован

    def test_two_symbols_with_call(self):
        """Два символа с вызовом."""
        index = SymbolIndex()
        index.add_definitions("test.py", [
            {"name": "main", "line": 1, "kind": "function"},
            {"name": "helper", "line": 5, "kind": "function"},
        ])
        index.add_references("test.py", [
            {"caller": "main", "callee": "helper", "line": 2, "file": "test.py"},
        ])

        ranks = index.compute_repo_rank()
        assert "main" in ranks
        assert "helper" in ranks

        # helper должен иметь более высокий rank (его вызывают)
        # main — менее высокий (он вызывает, но его не вызывают)
        # Но в PageRank важна структура графа
        assert len(ranks) == 2

    def test_popular_symbol_has_higher_rank(self):
        """Популярный символ имеет более высокий rank."""
        index = SymbolIndex()

        # Символ A вызывается всеми
        index.add_definitions("a.py", [{"name": "A", "line": 1, "kind": "function"}])
        index.add_definitions("b.py", [{"name": "B", "line": 1, "kind": "function"}])
        index.add_definitions("c.py", [{"name": "C", "line": 1, "kind": "function"}])
        index.add_definitions("d.py", [{"name": "D", "line": 1, "kind": "function"}])

        # B, C, D все вызывают A
        index.add_references("b.py", [{"caller": "B", "callee": "A", "line": 2, "file": "b.py"}])
        index.add_references("c.py", [{"caller": "C", "callee": "A", "line": 2, "file": "c.py"}])
        index.add_references("d.py", [{"caller": "D", "callee": "A", "line": 2, "file": "d.py"}])

        ranks = index.compute_repo_rank()

        # A должен иметь самый высокий rank
        assert ranks["A"] >= ranks["B"]
        assert ranks["A"] >= ranks["C"]
        assert ranks["A"] >= ranks["D"]

    def test_scores_normalized(self):
        """Все скоры нормализованы (максимальный = 1.0)."""
        index = SymbolIndex()
        index.add_definitions("test.py", [
            {"name": "a", "line": 1, "kind": "function"},
            {"name": "b", "line": 5, "kind": "function"},
            {"name": "c", "line": 10, "kind": "function"},
        ])
        index.add_references("test.py", [
            {"caller": "a", "callee": "b", "line": 2, "file": "test.py"},
            {"caller": "b", "callee": "c", "line": 6, "file": "test.py"},
        ])

        ranks = index.compute_repo_rank()

        # Максимальный score должен быть 1.0
        assert max(ranks.values()) == 1.0

        # Все score > 0
        assert all(v > 0 for v in ranks.values())

    def test_different_damping_factors(self):
        """Разные коэффициенты затухания."""
        index = SymbolIndex()
        index.add_definitions("test.py", [
            {"name": "a", "line": 1, "kind": "function"},
            {"name": "b", "line": 5, "kind": "function"},
        ])
        index.add_references("test.py", [
            {"caller": "a", "callee": "b", "line": 2, "file": "test.py"},
        ])

        ranks_85 = index.compute_repo_rank(damping=0.85)
        ranks_50 = index.compute_repo_rank(damping=0.50)

        # Оба должны работать
        assert len(ranks_85) == 2
        assert len(ranks_50) == 2

    def test_large_graph(self):
        """Большой граф символов."""
        index = SymbolIndex()

        # Создаём 10 символов
        symbols = [f"func_{i}" for i in range(10)]
        index.add_definitions("main.py", [
            {"name": sym, "line": i * 10, "kind": "function"}
            for i, sym in enumerate(symbols)
        ])

        # Создаём связи: каждый вызывает следующий
        for i in range(9):
            index.add_references("main.py", [
                {"caller": symbols[i], "callee": symbols[i + 1], "line": i * 10 + 1, "file": "main.py"}
            ])

        ranks = index.compute_repo_rank()

        assert len(ranks) == 10
        # Все score > 0
        assert all(v > 0 for v in ranks.values())
