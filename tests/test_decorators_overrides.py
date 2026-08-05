"""
Unit tests for DECORATES/OVERRIDES extraction and PropertyGraph storage.

Класс рёбер перенят из таксономии DeusData/codebase-memory-mcp (audit.md п.11):
  - DECORATES: (TYPE:decorator) --[DECORATES]--> (Function|Class|Method)
  - OVERRIDES: (Method:Child.m) --[OVERRIDES]--> (Method:Base.m), same-file v1

Tests cover:
  - Python decorators: методы, классы, с аргументами (@app.route), цепочки (@a.b)
  - Undecorated файлы → пусто
  - Overrides: same-file иерархия, multi-level, не-оверрайды не помечаются
  - Хранение в PropertyGraph + Cypher-запросы
"""

import os
import tempfile
from pathlib import Path

import pytest

from src.core.graph import EdgeType, NodeLabel, PropertyGraph
from src.core.indexing.parser import CodeParser
from src.core.search.graph_adapter import SymbolIndexAdapter
from src.core.search.cypher_executor import CypherExecutor


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
    return SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)


def _write_py(code: str) -> Path:
    fd, path = tempfile.mkstemp(suffix=".py")
    os.close(fd)
    f = Path(path)
    f.write_text(code, encoding="utf-8")
    return f


# ═══════════════════════════════════════════════════════════════
# 1. DECORATES — извлечение из AST
# ═══════════════════════════════════════════════════════════════

class TestDecoratorExtraction:
    def test_python_method_and_class_decorators(self, parser):
        f = _write_py(
            """
class Base:
    @property
    def prop(self):
        return 1

@dataclass
class Data:
    x: int
"""
        )
        decos = parser.extract_decorators(f)
        f.unlink(missing_ok=True)

        pairs = {(d["decorated"], d["decorator"]) for d in decos}
        assert ("Base.prop", "property") in pairs, f"got {pairs}"
        assert ("Data", "dataclass") in pairs, f"got {pairs}"

    def test_decorator_with_args_strips_call(self, parser):
        f = _write_py(
            """
from flask import Flask
app = Flask(__name__)

@app.route('/health')
def health():
    return 'ok'
"""
        )
        decos = parser.extract_decorators(f)
        f.unlink(missing_ok=True)

        names = {d["decorator"] for d in decos}
        assert "app.route" in names, f"got {names}"

    def test_chained_decorator_name(self, parser):
        f = _write_py(
            """
@abc.abstractmethod
def abstract(x):
    return x
"""
        )
        decos = parser.extract_decorators(f)
        f.unlink(missing_ok=True)

        assert any(d["decorator"] == "abc.abstractmethod" for d in decos)

    def test_undecorated_file_returns_empty(self, parser):
        f = _write_py(
            """
def plain(a):
    return a + 1

class NoDeco:
    def m(self):
        return 1
"""
        )
        decos = parser.extract_decorators(f)
        f.unlink(missing_ok=True)
        assert decos == []

    def test_multiple_decorators_on_one_symbol(self, parser):
        f = _write_py(
            """
@staticmethod
@lru_cache(maxsize=128)
def cached():
    return 42
"""
        )
        decos = parser.extract_decorators(f)
        f.unlink(missing_ok=True)

        names = sorted(d["decorator"] for d in decos)
        assert names == ["lru_cache", "staticmethod"], f"got {names}"
        # обе записи указывают на один символ
        assert {d["decorated"] for d in decos} == {"cached"}


# ═══════════════════════════════════════════════════════════════
# 2. OVERRIDES — извлечение из AST (same-file иерархия)
# ═══════════════════════════════════════════════════════════════

class TestOverrideExtraction:
    def test_same_file_override(self, parser):
        f = _write_py(
            """
class Base:
    def method(self):
        pass

class Child(Base):
    def method(self):
        pass

    def new_one(self):
        pass
"""
        )
        ovr = parser.extract_overrides(f)
        f.unlink(missing_ok=True)

        assert len(ovr) == 1, f"got {ovr}"
        assert ovr[0]["override"] == "Child.method"
        assert ovr[0]["overridden"] == "Base.method"
        assert ovr[0]["base"] == "Base"

    def test_multi_level_override(self, parser):
        f = _write_py(
            """
class A:
    def m(self):
        pass

class B(A):
    def m(self):
        pass

class C(B):
    def m(self):
        pass
"""
        )
        ovr = parser.extract_overrides(f)
        f.unlink(missing_ok=True)

        pairs = {(o["override"], o["overridden"]) for o in ovr}
        assert ("B.m", "A.m") in pairs, f"got {pairs}"
        assert ("C.m", "B.m") in pairs, f"got {pairs}"

    def test_external_base_no_overrides(self, parser):
        # Базовый класс из другого модуля — same-file резолв невозможен (v1)
        f = _write_py(
            """
from ext import Base

class Child(Base):
    def method(self):
        pass
"""
        )
        ovr = parser.extract_overrides(f)
        f.unlink(missing_ok=True)
        assert ovr == []

    def test_no_inheritance_empty(self, parser):
        f = _write_py(
            """
class Standalone:
    def m(self):
        pass
"""
        )
        ovr = parser.extract_overrides(f)
        f.unlink(missing_ok=True)
        assert ovr == []


# ═══════════════════════════════════════════════════════════════
# 3. PropertyGraph storage
# ═══════════════════════════════════════════════════════════════

class TestGraphStorage:
    def _index_python_file(self, adapter, parser, code: str) -> Path:
        f = _write_py(code)
        chunks, symbols = parser.parse_file(f)
        rel = f.resolve().as_posix()
        if symbols:
            adapter.add_definitions(rel, symbols)
        decos = parser.extract_decorators(f)
        if decos:
            adapter.add_decorators(rel, decos)
        ovr = parser.extract_overrides(f)
        if ovr:
            adapter.add_overrides(rel, ovr)
        return f

    def test_decorates_edges_created(self, adapter, parser):
        f = self._index_python_file(
            adapter,
            parser,
            """
class Base:
    @property
    def prop(self):
        return 1
""",
        )
        f.unlink(missing_ok=True)

        graph = adapter.graph
        edges = graph.get_edges_by_properties(edge_type=EdgeType.DECORATES)
        assert len(edges) == 1, f"got {len(edges)} DECORATES edges"

        src_node, tgt_node, edge = edges[0]
        assert src_node.name == "property"
        assert src_node.label == NodeLabel.TYPE
        assert tgt_node.name == "Base.prop"
        assert tgt_node.label in (NodeLabel.FUNCTION, NodeLabel.METHOD)

    def test_overrides_edges_created(self, adapter, parser):
        f = self._index_python_file(
            adapter,
            parser,
            """
class Base:
    def method(self):
        pass

class Child(Base):
    def method(self):
        pass
""",
        )
        f.unlink(missing_ok=True)

        edges = adapter.graph.get_edges_by_properties(edge_type=EdgeType.OVERRIDES)
        assert len(edges) == 1, f"got {len(edges)} OVERRIDES edges"

        src_node, tgt_node, _edge = edges[0]
        assert src_node.name == "Child.method"
        assert tgt_node.name == "Base.method"

    def test_decorates_skips_undefined_symbol(self, adapter, parser):
        # Декоратор создаётся, но ребро не проводится к неопределённому символу
        f = _write_py(
            """
@route('/x')
def handler():
    pass
"""
        )
        rel = f.resolve().as_posix()
        decos = parser.extract_decorators(f)
        adapter.add_decorators(rel, decos)
        f.unlink(missing_ok=True)

        edges = adapter.graph.get_edges_by_properties(edge_type=EdgeType.DECORATES)
        assert edges == []
        # Декоратор-узел создан
        nodes = adapter.graph.find_nodes(name_pattern="route")
        assert nodes, "decorator node should exist even without a defined target"


# ═══════════════════════════════════════════════════════════════
# 4. Cypher-доступность (schema валидация новых типов)
# ═══════════════════════════════════════════════════════════════

class TestCypherAccess:
    def test_decorates_queryable(self, adapter, parser):
        # Декорированная функция индексируется как символ; декорированный
        # класс (контейнер без методов) — нет (ограничение symbol extraction)
        f = _write_py(
            """
@dataclass
class Data:
    x: int

@lru_cache
@functools.wraps
def fetch():
    return 1
"""
        )
        chunks, symbols = parser.parse_file(f)
        rel = f.resolve().as_posix()
        adapter.add_definitions(rel, symbols)
        adapter.add_decorators(rel, parser.extract_decorators(f))
        f.unlink(missing_ok=True)

        engine = CypherExecutor(adapter.graph)
        res = engine.execute(
            "MATCH (d)-[:DECORATES]->(s) RETURN s.name AS decorated, d.name AS deco"
        )
        rows = res["results"]
        pairs = {(r["decorated"], r["deco"]) for r in rows}
        assert ("fetch", "lru_cache") in pairs, f"got {pairs}"
        assert ("fetch", "functools.wraps") in pairs, f"got {pairs}"

    def test_overrides_queryable(self, adapter, parser):
        f = _write_py(
            """
class A:
    def m(self):
        pass

class B(A):
    def m(self):
        pass
"""
        )
        chunks, symbols = parser.parse_file(f)
        rel = f.resolve().as_posix()
        adapter.add_definitions(rel, symbols)
        adapter.add_overrides(rel, parser.extract_overrides(f))
        f.unlink(missing_ok=True)

        engine = CypherExecutor(adapter.graph)
        res = engine.execute(
            "MATCH (a)-[:OVERRIDES]->(b) RETURN a.name AS child, b.name AS parent"
        )
        rows = res["results"]
        assert len(rows) == 1, f"got {rows}"
        assert rows[0]["child"] == "B.m"
        assert rows[0]["parent"] == "A.m"
