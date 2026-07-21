"""Integration tests for SYM-INDEX-PARTIAL: SymbolIndexAdapter + PropertyGraph.

Воспроизводит баг из indexer.py _parse_file_only: прямой вызов pg.remove_file(rel_path)
вместо self._symbol_index.remove_file(abs_path).

Основные проверки:
1. adapter.remove_file правильно очищает и definitions, и references
2. Прямой pg.remove_file с относительным путём НЕ очищает (path mismatch)
3. После re-index (remove + add) консистентность сохраняется
"""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def pg():
    """PropertyGraph с временной SQLite БД."""
    from src.core.graph import PropertyGraph

    tmp = tempfile.mktemp(suffix=".db")
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


class TestSymIndexPartial:
    """SYM-INDEX-PARTIAL: консистентность find_definitions / find_references."""

    # ─── Базовые инварианты ─────────────────────────────

    def test_add_and_find(self, adapter):
        """Базовый сценарий: add → find."""
        adapter.add_definitions("/project/a.py", [
            {"name": "foo", "line": 10, "kind": "function"}
        ])
        adapter.add_references("/project/a.py", [
            {"caller": "foo", "callee": "bar", "line": 20}
        ])

        defs = adapter.find_definitions("foo")
        assert len(defs) == 1, f"find_definitions('foo') = {len(defs)}"
        refs = adapter.find_references("bar")
        assert len(refs) == 1, f"find_references('bar') = {len(refs)}"

    # ─── remove_file через адаптер (правильный путь) ────

    def test_adapter_remove_cleans_defs_and_refs(self, adapter):
        """adapter.remove_file должен очищать и defs и refs для этого файла."""
        adapter.add_definitions("/project/a.py", [
            {"name": "foo", "line": 10, "kind": "function"}
        ])
        adapter.add_references("/project/a.py", [
            {"caller": "foo", "callee": "bar", "line": 20}
        ])

        adapter.remove_file("/project/a.py")

        # После удаления файла: foo не должен быть найден
        assert len(adapter.find_definitions("foo")) == 0, (
            "После adapter.remove_file find_definitions('foo') должен быть пуст"
        )
        # bar — это callee из другого файла, но т.к. единственная ссылка
        # была из a.py, её тоже не должно быть (каскадное удаление edges)
        refs = adapter.find_references("bar")
        # Примечание: может остаться placeholder для bar, это нормально
        # Проверяем что нет реальных references
        real_refs = [r for r in refs if r.file_path]
        assert len(real_refs) == 0, (
            f"После remove_file остались reference с file_path: {real_refs}"
        )

    # ─── remove_file через pg (неправильно: относительный путь) ──

    def test_pg_remove_file_wrong_path_leaves_orphans(self, adapter, pg):
        """Прямой pg.remove_file(rel_path) — path mismatch.

        В indexer.py строка 336:
            pg.remove_file(rel_path_str.replace("\\", "/"))

        Это НЕ удаляет узлы, потому что в БД file_path — абсолютный.
        """
        adapter.add_definitions("/project/src/a.py", [
            {"name": "foo", "line": 10, "kind": "function"}
        ])

        # Прямой pg.remove_file с относительным путём (как в баге)
        deleted = pg.remove_file("src/a.py")
        assert deleted == 0, (
            f"pg.remove_file('src/a.py') удалил {deleted} nodes, "
            f"хотя в БД file_path = '/project/src/a.py'. "
            f"Это path mismatch — bug!"
        )

    # ─── Re-index симуляция ─────────────────────────────

    def test_reindex_consistency(self, adapter):
        """После remove + add (reindex) инварианты сохраняются."""
        adapter.add_definitions("/project/mod.py", [
            {"name": "process", "line": 5, "kind": "function"}
        ])
        assert len(adapter.find_definitions("process")) == 1

        # Удаляем
        adapter.remove_file("/project/mod.py")
        assert len(adapter.find_definitions("process")) == 0

        # Добавляем снова (симуляция переиндексации)
        adapter.add_definitions("/project/mod.py", [
            {"name": "process", "line": 5, "kind": "function"},
        ])
        assert len(adapter.find_definitions("process")) == 1, (
            "После reindex process должен быть найден"
        )

    def test_reindex_with_cross_file_refs(self, adapter):
        """Переиндексация с перекрёстными ссылками между файлами."""
        adapter.add_definitions("/project/a.py", [
            {"name": "helper", "line": 1, "kind": "function"}
        ])
        adapter.add_definitions("/project/b.py", [
            {"name": "main", "line": 10, "kind": "function"}
        ])
        adapter.add_references("/project/b.py", [
            {"caller": "main", "callee": "helper", "line": 15}
        ])

        assert len(adapter.find_definitions("helper")) == 1
        assert len(adapter.find_references("helper")) == 1

        # Переиндексация b.py
        adapter.remove_file("/project/b.py")
        adapter.add_definitions("/project/b.py", [
            {"name": "main", "line": 10, "kind": "function"}
        ])
        adapter.add_references("/project/b.py", [
            {"caller": "main", "callee": "helper", "line": 15}
        ])

        # helper должен быть найден (определён в a.py, не удалялся)
        assert len(adapter.find_definitions("helper")) == 1, (
            "helper определён в a.py, после переиндексации b.py должен быть найден"
        )
        # reference от main → helper должен сохраниться
        refs = adapter.find_references("helper")
        b_refs = [r for r in refs if "b.py" in r.file_path]
        assert len(b_refs) == 1, (
            f"После переиндексации b.py должно быть 1 reference от b.py к helper, "
            f"найдено {len(b_refs)}: {b_refs}"
        )

    # ─── Множественные определения ──────────────────────

    def test_multiple_definitions_same_symbol(self, adapter):
        """Символ, определённый в нескольких файлах (protocol/ABC)."""
        adapter.add_definitions("/project/impl_a.py", [
            {"name": "run", "line": 5, "kind": "method"}
        ])
        adapter.add_definitions("/project/impl_b.py", [
            {"name": "run", "line": 10, "kind": "method"}
        ])

        defs = adapter.find_definitions("run")
        assert len(defs) == 2, f"Ожидалось 2 определения 'run', получено {len(defs)}"

        # Удаляем один файл — остаётся одно определение
        adapter.remove_file("/project/impl_a.py")
        defs_after = adapter.find_definitions("run")
        assert len(defs_after) == 1, (
            f"После удаления impl_a.py должно остаться 1 определение 'run', "
            f"получено {len(defs_after)}"
        )

    # ─── Символ только в references ─────────────────────

    def test_references_only_symbol(self, adapter):
        """Ситуация: символ есть в _references, но не в _definitions.

        Это нормально для внешних символов (библиотек).
        """
        adapter.add_definitions("/project/main.py", [
            {"name": "main", "line": 1, "kind": "function"}
        ])
        adapter.add_references("/project/main.py", [
            {"caller": "main", "callee": "os_path_join", "line": 5}
        ])

        # os_path_join — external, не определён в проекте
        adapter.find_definitions("os_path_join")
        # Должен вернуть пусто или placeholder (но не crash)
        refs = adapter.find_references("os_path_join")
        assert len(refs) >= 1, (
            "os_path_join должен иметь минимум 1 reference (от main)"
        )
