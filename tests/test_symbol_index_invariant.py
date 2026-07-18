"""Invariant tests for SymbolIndex — SYM-INDEX-PARTIAL.

Проверяет, что после любой записи в индекс _definitions и _references
для одного symbol_id остаются консистентными.

Ключевой инвариант:
    - Если символ есть в _definitions → find_definitions() не пуст
    - Если символ есть в _references → find_references() не пуст
    - После remove_file + re-add инварианты сохраняются
    - search_symbols возвращает консистентные результаты
"""

import gc
import pytest
from src.core.indexing.symbol_index import SymbolIndex


# ─── Helper: типовой вывод парсера ─────────────────────────────


def make_symbols(names, kind="function", start_line=1):
    """Генерирует список словарей, аналогичный выхлопу парсера."""
    return [
        {"name": name, "line": start_line + i, "kind": kind}
        for i, name in enumerate(names)
    ]


def make_calls(pairs, start_line=1):
    """Генерирует список вызовов, аналогичный extract_calls().

    pairs: список (caller, callee)
    """
    return [
        {"caller": caller, "callee": callee, "line": start_line + i}
        for i, (caller, callee) in enumerate(pairs)
    ]


# ─── Инвариант: после add_definitions + add_references ─────────


class TestDefinitionsReferencesConsistency:
    """Ядро SYM-INDEX-PARTIAL: консистентность _definitions и _references."""

    def _assert_index_invariants(self, index: SymbolIndex):
        """Проверяет фундаментальные инварианты SymbolIndex.

        Вызывается после любой операции записи.
        """
        with index._lock:
            for sym in index._definitions:
                assert index.find_definitions(sym), (
                    f"SYM-INDEX-PARTIAL: символ '{sym}' есть в _definitions, "
                    f"но find_definitions() вернул пусто"
                )
            for sym in index._references:
                assert index.find_references(sym), (
                    f"SYM-INDEX-PARTIAL: символ '{sym}' есть в _references, "
                    f"но find_references() вернул пусто"
                )

    def test_simple_add(self):
        """Базовый сценарий: добавили определения + вызовы."""
        idx = SymbolIndex()

        # Добавляем файл A с функцией foo
        idx.add_definitions("/project/a.py", make_symbols(["foo"]))
        # Добавляем файл B с функцией bar, который вызывает foo
        idx.add_definitions("/project/b.py", make_symbols(["bar"]))
        idx.add_references("/project/b.py", make_calls([("bar", "foo")]))

        self._assert_index_invariants(idx)

        assert len(idx.find_definitions("foo")) == 1
        assert len(idx.find_definitions("bar")) == 1
        assert len(idx.find_references("foo")) == 1
        assert idx.find_references("bar") == []

    def test_multiple_files_same_symbol(self):
        """Символ определён в нескольких файлах (например, протокол/ABC)."""
        idx = SymbolIndex()

        idx.add_definitions("/project/impl_a.py", make_symbols(["run"]))
        idx.add_definitions("/project/impl_b.py", make_symbols(["run"]))
        idx.add_references("/project/main.py", make_calls([("main", "run")]))

        self._assert_index_invariants(idx)

        defs = idx.find_definitions("run")
        assert len(defs) == 2, f"Ожидалось 2 определения 'run', получено {len(defs)}"

    def test_references_without_definitions(self):
        """Ситуация SYM-INDEX-PARTIAL: символ есть в _references, но не в _definitions.

        Это может случиться при частичной переиндексации или если
        add_references вызван до add_definitions для этого символа.
        """
        idx = SymbolIndex()

        # Добавляем ТОЛЬКО references для call_main (callee), без definition
        idx.add_definitions("/project/a.py", make_symbols(["call_main"]))
        idx.add_references("/project/a.py", make_calls([("call_main", "nonexistent_func")]))

        self._assert_index_invariants(idx)

        # nonexistent_func — есть в _references, нет в _definitions
        refs = idx.find_references("nonexistent_func")
        assert len(refs) == 1, (
            f"SYM-INDEX-PARTIAL: nonexistent_func есть в _references, "
            f"но find_references() вернул {len(refs)}"
        )

        defs = idx.find_definitions("nonexistent_func")
        assert len(defs) == 0, (
            f"nonexistent_func не должен иметь определений"
        )

    # ─── Инвариант: после remove_file + re-add ────────────


    def test_reindex_preserves_invariants(self):
        """Симуляция переиндексации файла: remove + re-add."""
        idx = SymbolIndex()

        # Первоначальная индексация
        idx.add_definitions("/project/a.py", make_symbols(["foo", "bar"]))
        idx.add_definitions("/project/b.py", make_symbols(["baz"]))
        idx.add_references("/project/b.py", make_calls([("baz", "foo")]))

        self._assert_index_invariants(idx)

        # Удаляем файл a.py (симуляция переиндексации)
        idx.remove_file("/project/a.py")

        self._assert_index_invariants(idx)

        # После удаления: foo и bar должны исчезнуть из _definitions
        assert idx.find_definitions("foo") == [], (
            "После remove_file определения foo должны быть пусты"
        )
        assert idx.find_definitions("bar") == [], (
            "После remove_file определения bar должны быть пусты"
        )
        # Ссылка baz → foo должна исчезнуть (foo больше не существует)
        # Но сам baz должен остаться
        assert len(idx.find_definitions("baz")) == 1

        # Re-add файла a.py (симуляция повторной индексации)
        idx.add_definitions("/project/a.py", make_symbols(["foo", "bar"]))

        self._assert_index_invariants(idx)

        assert len(idx.find_definitions("foo")) == 1, (
            f"После re-add: find_definitions('foo') должен содержать 1 элемент, "
            f"получено {len(idx.find_definitions('foo'))}"
        )

    def test_reindex_without_remove(self):
        """CAS-1 (SYM-INDEX-PARTIAL): двойной add_definitions без remove_file.

        В реальном пайплайне файл может индексироваться дважды без remove_file
        (например, при частичной переиндексации). Должны избежать дублирования.
        """
        idx = SymbolIndex()

        idx.add_definitions("/project/a.py", make_symbols(["foo"]))
        idx.add_definitions("/project/a.py", make_symbols(["foo"]))  # повторно

        self._assert_index_invariants(idx)

        defs = idx.find_definitions("foo")
        assert len(defs) == 1, (
            f"После двойного add_definitions должно быть 1 определение 'foo', "
            f"получено {len(defs)}"
        )

    def test_add_references_twice(self):
        """CAS-2: двойной add_references тех же call-ов — без дублирования."""
        idx = SymbolIndex()

        idx.add_definitions("/project/a.py", make_symbols(["foo", "bar"]))
        idx.add_references("/project/a.py", make_calls([("foo", "bar")]))
        idx.add_references("/project/a.py", make_calls([("foo", "bar")]))  # повторно

        self._assert_index_invariants(idx)

        refs = idx.find_references("bar")
        assert len(refs) == 1, (
            f"После двойного add_references должно быть 1 reference для 'bar', "
            f"получено {len(refs)}"
        )

    # ─── Инвариант: search_symbols vs find_definitions/find_references ───


    def test_search_symbols_consistency(self):
        """search_symbols не должен возвращать символы, отсутствующие в индексе."""
        idx = SymbolIndex()

        idx.add_definitions("/project/a.py", make_symbols(["validate", "process"]))
        idx.add_references("/project/a.py", make_calls([("process", "validate")]))
        idx.add_definitions("/project/b.py", make_symbols(["transform"]))

        self._assert_index_invariants(idx)

        # Поиск 'val' должен найти validate
        results = idx.search_symbols("val", top_k=5)
        names = {r.symbol for r in results}
        assert "validate" in names, f"search_symbols('val') не нашёл 'validate': {names}"

        # Каждый результат search_symbols должен быть либо в _definitions,
        # либо в _references
        with idx._lock:
            all_defined = set(idx._definitions.keys())
            all_referenced = set(idx._references.keys())

        for r in results:
            assert r.symbol in all_defined or r.symbol in all_referenced, (
                f"search_symbols вернул '{r.symbol}', которого нет ни в "
                f"_definitions, ни в _references"
            )

    # ─── Edge cases ─────────────────────────────────────


    def test_empty_index(self):
        """Пустой индекс не должен падать."""
        idx = SymbolIndex()
        self._assert_index_invariants(idx)
        assert idx.find_definitions("anything") == []
        assert idx.find_references("anything") == []

    def test_remove_nonexistent_file(self):
        """remove_file несуществующего файла не должен падать."""
        idx = SymbolIndex()
        idx.add_definitions("/project/a.py", make_symbols(["foo"]))

        self._assert_index_invariants(idx)

        idx.remove_file("/project/nonexistent.py")

        self._assert_index_invariants(idx)
        assert len(idx.find_definitions("foo")) == 1, (
            "remove_file несуществующего файла не должен влиять на существующие"
        )

    def test_large_batch_consistency(self):
        """Массовое добавление 100 символов с перекрёстными ссылками."""
        idx = SymbolIndex()
        n = 100

        # Генерируем функции func_0 .. func_99 в одном файле
        func_names = [f"func_{i}" for i in range(n)]
        idx.add_definitions("/project/all.py", make_symbols(func_names))

        # Генерируем цепочку вызовов func_0 → func_1 → func_2 → ...
        calls = []
        for i in range(n - 1):
            calls.append({"caller": f"func_{i}", "callee": f"func_{i+1}", "line": 100 + i})
        idx.add_references("/project/all.py", calls)

        self._assert_index_invariants(idx)

        # Выборочная проверка
        for i in range(n):
            sym = f"func_{i}"
            defs = idx.find_definitions(sym)
            assert len(defs) == 1, f"{sym}: ожидалось 1 def, получено {len(defs)}"
            if i < n - 1:
                # func_i вызывается func_{i-1} (если i > 0)
                # и вызывает func_{i+1}
                pass  # references проверены в _assert_index_invariants

    def test_gc_pressure(self):
        """Проверка что SymbolIndex переживает GC (нет слабых ссылок)."""
        idx = SymbolIndex()
        idx.add_definitions("/project/a.py", make_symbols(["foo"]))
        idx.add_definitions("/project/b.py", make_symbols(["bar"]))
        idx.add_references("/project/b.py", make_calls([("bar", "foo")]))

        gc.collect()
        gc.collect()  # принудительный GC

        self._assert_index_invariants(idx)
        assert len(idx.find_definitions("foo")) == 1
        assert len(idx.find_references("foo")) == 1


# ─── Инвариант: атомарность add_definitions + add_references ──


class TestAtomicWriteInvariants:
    """Проверка что SymbolIndex не остаётся в половинчатом состоянии."""

    def test_symbol_in_defs_but_not_refs(self):
        """Символ в _definitions может не иметь references — это норм."""
        idx = SymbolIndex()
        idx.add_definitions("/project/a.py", make_symbols(["orphan_func"]))
        # Не добавляем references

        with idx._lock:
            assert "orphan_func" in idx._definitions
            assert "orphan_func" not in idx._references  # может и не быть

        defs = idx.find_definitions("orphan_func")
        assert len(defs) == 1

    def test_parallel_safety(self):
        """Базовый тест на thread-safety: add_definitions + add_references.

        Проверяет что под RLock два вызова не создают гонку.
        """
        import threading

        idx = SymbolIndex()
        errors = []

        def writer():
            for i in range(20):
                try:
                    idx.add_definitions(
                        f"/project/file_{i}.py",
                        make_symbols([f"sym_{i}"])
                    )
                    idx.add_references(
                        f"/project/file_{i}.py",
                        make_calls([(f"sym_{i}", f"sym_{i-1}" if i > 0 else "root")])
                    )
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        # После всех записей инварианты должны быть целы
        with idx._lock:
            for sym in idx._definitions:
                assert idx.find_definitions(sym), f"Thread-safety: {sym} lost"
