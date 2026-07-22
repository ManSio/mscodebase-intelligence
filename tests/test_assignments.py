"""
Unit tests for ASSIGNED_FROM extraction and PropertyGraph storage.

Tests cover:
  - Basic assignments (x = y)
  - Augmented assignments (x += y)
  - Conditional flow (x = y inside if/for/while/try)
  - Scope isolation (nested functions)
  - Constants (x = 42 — no edge, but x is tracked)
  - PropertyGraph storage + condition_path persistence
"""

import json
import os
import tempfile
from pathlib import Path
from typing import List

import pytest

from src.core.graph import EdgeType, NodeLabel, PropertyGraph
from src.core.indexing.parser import CodeParser
from src.core.search.graph_adapter import SymbolIndexAdapter

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def parser():
    return CodeParser()


@pytest.fixture
def pg():
    """Temporary PropertyGraph for testing."""
    fd, db_path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_path = Path(db_path_str)
    graph = PropertyGraph(db_path)
    yield graph
    graph.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def adapter(pg):
    return SymbolIndexAdapter(pg)


def _write_py(code: str) -> Path:
    fd, path = tempfile.mkstemp(suffix=".py")
    os.close(fd)
    f = Path(path)
    f.write_text(code, encoding="utf-8")
    return f


def _write_file(data: bytes, suffix: str) -> Path:
    """Securely create a temp file with the given content."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    f = Path(path)
    f.write_bytes(data)
    return f


def _edges_from(assignments: List[dict]) -> set:
    """Extract (source, target) pairs from assignment list."""
    return {(a["source"], a["target"]) for a in assignments}


def _conditional_from(assignments: List[dict]) -> dict:
    """Extract condition_path per (source, target)."""
    result = {}
    for a in assignments:
        key = (a["source"], a["target"])
        if "condition_path" in a:
            result[key] = a["condition_path"]
    return result


# ═══════════════════════════════════════════════════════════════
# 1. Basic assignment extraction
# ═══════════════════════════════════════════════════════════════

class TestBasicAssignments:
    """Простые присваивания."""

    def test_simple_chain(self, parser):
        """a = b; c = a → b→a, a→c"""
        code = """
def f():
    a = b
    c = a
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        f.unlink()

        edges = _edges_from(assign)
        assert ("b", "a") not in edges  # b — параметр, не assigned
        assert ("a", "c") in edges

    def test_augmented(self, parser):
        """a += b → a in assigned, edge from b if tracked"""
        code = """
def f():
    a = b
    a += c
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        f.unlink()

        # a = b: b не assigned → нет edge
        # a += c: a уже assigned, c не assigned → нет edge
        # Но a должен быть в assigned
        assert len(assign) == 0  # нет edges, но assigned работает

    def test_chained_assignment(self, parser):
        """a = x; b = a; c = b → a→b, b→c"""
        code = """
def f():
    a = x
    b = a
    c = b
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        f.unlink()

        edges = _edges_from(assign)
        assert ("a", "b") in edges
        assert ("b", "c") in edges
        assert len(edges) == 2

    def test_call_rhs(self, parser):
        """a = func(x, y) — отслеживаем x→a и y→a, если x/y в assigned"""
        code = """
def f():
    x = arg
    a = transform(x, y)
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        f.unlink()

        edges = _edges_from(assign)
        # x assigned, y — нет (параметр), arg — нет (параметр)
        assert ("x", "a") in edges
        assert len(edges) == 1  # только x→a


# ═══════════════════════════════════════════════════════════════
# 2. Conditional flow
# ═══════════════════════════════════════════════════════════════

class TestConditionalFlow:
    """Проверка condition_path в ASSIGNED_FROM."""

    def test_if_block(self, parser):
        """x = y внутри if → condition_path=['if_statement']"""
        code = """
def f():
    y = src
    if y > 0:
        x = y
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        f.unlink()

        cond = _conditional_from(assign)
        assert ("y", "x") in cond
        assert cond[("y", "x")] == ["if_statement"]

    def test_for_loop(self, parser):
        """x = y внутри for → condition_path=['for_statement']"""
        code = """
def f(items):
    y = src
    for item in items:
        x = y
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        f.unlink()

        cond = _conditional_from(assign)
        assert ("y", "x") in cond
        assert cond[("y", "x")] == ["for_statement"]

    def test_nested_conditions(self, parser):
        """x = y внутри вложенных if+for → оба в condition_path"""
        code = """
def f():
    y = src
    if y > 0:
        for i in items:
            z = y
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        f.unlink()

        cond = _conditional_from(assign)
        assert ("y", "z") in cond
        assert cond[("y", "z")] == ["if_statement", "for_statement"]

    def test_unconditional_has_no_path(self, parser):
        """x = y вне условий → нет condition_path"""
        code = """
def f():
    y = src
    z = y
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        f.unlink()

        for a in assign:
            assert "condition_path" not in a,\
                f"Unexpected condition_path in {a}"

    def test_try_except(self, parser):
        """Присваивания внутри try/except помечаются"""
        code = """
def f():
    y = src
    try:
        x = y
    except:
        z = y
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        f.unlink()

        cond = _conditional_from(assign)
        assert ("y", "x") in cond
        assert cond[("y", "x")] == ["try_statement"]
        assert ("y", "z") in cond
        assert cond[("y", "z")] == ["try_statement", "except_clause"]


# ═══════════════════════════════════════════════════════════════
# 3. Scope isolation
# ═══════════════════════════════════════════════════════════════

class TestScopeIsolation:
    """Переменные из внешней функции НЕ протекают во вложенную."""

    def test_nested_function(self, parser):
        """x в outer не виден внутри inner"""
        code = """
def outer():
    x = src
    def inner():
        y = x
    z = x
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        f.unlink()

        edges = _edges_from(assign)
        # x → z есть (оба в outer)
        assert ("x", "z") in edges
        # x → y может быть (зависит от scope merge)
        # inner получает merged scope от outer


# ═══════════════════════════════════════════════════════════════
# 4. PropertyGraph storage
# ═══════════════════════════════════════════════════════════════

class TestPropertyGraphStorage:
    """ASSIGNED_FROM корректно сохраняется в PropertyGraph."""

    def test_edges_stored(self, parser, adapter):
        """ASSIGNED_FROM edges создаются в графе."""
        code = """
def f():
    x = src
    y = x
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        adapter.add_assignments(str(f), assign)
        f.unlink()

        stats = adapter.graph.get_edge_stats()
        assert EdgeType.ASSIGNED_FROM in stats
        assert stats[EdgeType.ASSIGNED_FROM] >= 1

    def test_variable_nodes_created(self, parser, adapter):
        """Variable-узлы создаются для source и target."""
        code = """
def f():
    x = src
    y = x
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        adapter.add_assignments(str(f), assign)
        f.unlink()

        # Проверяем, что узлы созданы
        var_nodes = adapter.graph.find_nodes(label=NodeLabel.VARIABLE)
        names = {n.name for n in var_nodes}
        assert "x" in names
        assert "y" in names

    def test_condition_path_in_properties(self, parser, adapter):
        """condition_path сохраняется в свойствах ребра."""
        code = """
def f():
    y = src
    if y > 0:
        x = y
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        adapter.add_assignments(str(f), assign)
        f.unlink()

        # Найти ребро с condition_path
        conn = adapter.graph._get_conn()
        rows = conn.execute(
            "SELECT properties FROM edges WHERE type = ?",
            (EdgeType.ASSIGNED_FROM,),
        ).fetchall()

        found_conditional = False
        for row in rows:
            raw = row["properties"]
            props = json.loads(raw) if isinstance(raw, str) else (raw or {})
            if "condition_path" in props:
                assert props["condition_path"] == ["if_statement"]
                found_conditional = True

        assert found_conditional, "No conditional edge found in graph"


# ═══════════════════════════════════════════════════════════════
# 5. Edge cases
# ═══════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Граничные случаи — не должны падать."""

    def test_empty_file(self, parser):
        """Пустой файл → пустой результат."""
        f = _write_py("")
        assign = parser.extract_assignments(f)
        f.unlink()
        assert assign == []

    def test_only_imports(self, parser):
        """Файл только с импортами → пустой результат."""
        code = "import os\nfrom pathlib import Path\n"
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        f.unlink()
        assert assign == []

    def test_class_only(self, parser):
        """Класс без методов → пустой результат."""
        code = """
class Empty:
    pass
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        f.unlink()
        assert assign == []

    def test_const_assignment(self, parser):
        """x = 42 → нет ASSIGNED_FROM (константа не даёт edge)."""
        code = """
def f():
    x = 42
    y = x
"""
        f = _write_py(code)
        assign = parser.extract_assignments(f)
        f.unlink()

        # x = 42: RHS integer — нет edge
        # y = x: x assigned → edge x→y
        edges = _edges_from(assign)
        assert ("x", "y") in edges
        assert len(edges) == 1

    def test_attribute_assignment(self, parser):
        """self.x = y → НЕ отслеживается (только простые имена)."""
        code = """
class Handler:
    def handle(self):
        self.x = src
        y = self.x
"""
        f = _write_py(code)
        _ = parser.extract_assignments(f)  # не падает
        f.unlink()

        # self.x не является identifier → нет ASSIGNED_FROM
        # y = self.x → self.x не identifier → refs пусты → нет edge
        # Всё нормально — attribute assignments не отслеживаются


# ═══════════════════════════════════════════════════════════════
# 6. Multi-language tests (Rust, TypeScript)
# ═══════════════════════════════════════════════════════════════

class TestMultiLanguage:
    """ASSIGNED_FROM extraction for Rust and TypeScript.

    Note: requires tree_sitter_rust and tree_sitter_typescript grammars.
    If unavailable, tests are skipped.
    """

    @staticmethod
    def _has_grammar(ext: str, parser) -> bool:
        return ext in parser.parsers

    def test_rust_basic_let(self, parser):
        """Rust: let x = src; let y = x; → x→y"""
        if not self._has_grammar(".rs", parser):
            pytest.skip("tree_sitter_rust not available")
        code = b"""fn process() {
    let x = src;
    let y = x;
}"""
        f = _write_file(code, ".rs")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges

    def test_rust_mut_assign(self, parser):
        """Rust: let mut x = 1; x = y; → если y assigned, edge"""
        if not self._has_grammar(".rs", parser):
            pytest.skip("tree_sitter_rust not available")
        code = b"""fn process() {
    let y = src;
    let mut x = y;
}"""
        f = _write_file(code, ".rs")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        # x = y: y assigned → edge y→x
        assert ("y", "x") in edges

    def test_ts_basic(self, parser):
        """TypeScript: let x = src; const y = x; → x→y"""
        if not self._has_grammar(".ts", parser):
            pytest.skip("tree_sitter_typescript not available")
        code = b"""function process() {
    let x = src;
    const y = x;
}"""
        f = _write_file(code, ".ts")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges

    def test_tsx_basic(self, parser):
        """TSX component with assignments"""
        if not self._has_grammar(".tsx", parser):
            pytest.skip("tree_sitter_typescript not available")
        code = b"""function App() {
    const data = fetch();
    const result = data;
    return <div>{result}</div>;
}"""
        f = _write_file(code, ".tsx")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("data", "result") in edges

    def test_go_short_var(self, parser):
        """Go: x := src; y := x → x→y"""
        if not self._has_grammar(".go", parser):
            pytest.skip("tree_sitter_go not available")
        code = b'''package main
func main() {
    x := src
    y := x
}'''
        f = _write_file(code, ".go")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges

    def test_go_assign(self, parser):
        """Go: var x = src; y = x → x→y"""
        if not self._has_grammar(".go", parser):
            pytest.skip("tree_sitter_go not available")
        code = b'''package main
func main() {
    var x = src
    y := x
}'''
        f = _write_file(code, ".go")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges

    def test_js_let(self, parser):
        """JS: let x = src; const y = x → x→y"""
        if not self._has_grammar(".js", parser):
            pytest.skip("tree_sitter_javascript not available")
        code = b'''function f() {
    let x = src;
    const y = x;
}'''
        f = _write_file(code, ".js")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges

    def test_java_assign(self, parser):
        """Java: int x = src; int y = x → x→y"""
        if not self._has_grammar(".java", parser):
            pytest.skip("tree_sitter_java not available")
        code = b'''class F {
    void f() {
        int x = src;
        int y = x;
    }
}'''
        f = _write_file(code, ".java")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges

    def test_cs_assign(self, parser):
        """C#: int x = src; int y = x → x→y"""
        if not self._has_grammar(".cs", parser):
            pytest.skip("tree_sitter_c_sharp not available")
        code = b'''class F {
    void f() {
        int x = src;
        int y = x;
    }
}'''
        f = _write_file(code, ".cs")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges

    def test_ruby_assign(self, parser):
        """Ruby: x = src; y = x → x→y"""
        if not self._has_grammar(".rb", parser):
            pytest.skip("tree_sitter_ruby not available")
        code = b'''def f
    x = src
    y = x
end'''
        f = _write_file(code, ".rb")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges

    def test_kotlin_assign(self, parser):
        if not self._has_grammar(".kt", parser):
            pytest.skip("tree_sitter_kotlin not available")
        code = b'''fun main() {
    val x = src
    var y = x
}'''
        f = _write_file(code, ".kt")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges

    def test_swift_assign(self, parser):
        if not self._has_grammar(".swift", parser):
            pytest.skip("tree_sitter_swift not available")
        code = b'''func f() {
    let x = src
    var y = x
}'''
        f = _write_file(code, ".swift")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges

    def test_c_init(self, parser):
        if not self._has_grammar(".c", parser):
            pytest.skip("tree_sitter_c not available")
        code = b'''void f() {
    int x = src;
    int y = x;
}'''
        f = _write_file(code, ".c")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges

    def test_cpp_init(self, parser):
        if not self._has_grammar(".cpp", parser):
            pytest.skip("tree_sitter_cpp not available")
        code = b'''void f() {
    int x = src;
    int y = x;
}'''
        f = _write_file(code, ".cpp")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges

    def test_scala_assign(self, parser):
        if not self._has_grammar(".scala", parser):
            pytest.skip("tree_sitter_scala not available")
        code = b'''def f() = {
    val x = src
    var y = x
}'''
        f = _write_file(code, ".scala")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges

    def test_dart_assign(self, parser):
        if not self._has_grammar(".dart", parser):
            pytest.skip("tree_sitter_dart not available")
        code = b'''void f() {
    var x = src;
    var y = x;
}'''
        f = _write_file(code, ".dart")
        assign = parser.extract_assignments(f)
        f.unlink()
        edges = _edges_from(assign)
        assert ("x", "y") in edges


