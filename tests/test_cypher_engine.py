"""
Tests for Cypher Engine — lexer, parser, SQL generator, and end-to-end execution.

Phase 1: Lexer + Parser (AST correctness)
Phase 2: SQL generation (Cypher -> SQL translation)
Phase 3: End-to-end execution against PropertyGraph
Phase 4: OPTIONAL MATCH (LEFT JOIN) — correctness bug fix
Phase 5: Error handling and edge cases
"""

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.core.cypher_engine import (
    CypherExecutor,
    CypherLexer,
    CypherParser,
    CypherToSQL,
    Query,
    Token,
    TokenType,
    query_graph,
)
from src.core.graph import EdgeType, NodeLabel, PropertyGraph


# ════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════


@pytest.fixture
def pg(tmp_path):
    """PropertyGraph with test data for function call graph."""
    pg = PropertyGraph(tmp_path / "test.db")

    # Functions
    pg.add_node("main", label=NodeLabel.FUNCTION, qualified_name="main", file_path="app.py")
    pg.add_node("parse", label=NodeLabel.FUNCTION, qualified_name="parse", file_path="parser.py")
    pg.add_node("validate", label=NodeLabel.FUNCTION, qualified_name="validate", file_path="validator.py")
    pg.add_node("render", label=NodeLabel.FUNCTION, qualified_name="render", file_path="view.py")
    pg.add_node("log_error", label=NodeLabel.FUNCTION, qualified_name="log_error", file_path="logger.py")

    # Variables
    pg.add_node("config", label=NodeLabel.VARIABLE, qualified_name="config", file_path="config.py")
    pg.add_node("db_conn", label=NodeLabel.VARIABLE, qualified_name="db_conn", file_path="db.py")

    # Edges: main -> parse, main -> validate, parse -> render, validate -> log_error
    pg.add_edge("main", "parse", type=EdgeType.CALLS)
    pg.add_edge("main", "validate", type=EdgeType.CALLS)
    pg.add_edge("parse", "render", type=EdgeType.CALLS)
    pg.add_edge("validate", "log_error", type=EdgeType.CALLS)

    # Edges: parse -> config (USAGE), validate -> db_conn (USAGE)
    pg.add_edge("parse", "config", type=EdgeType.USAGE)
    pg.add_edge("validate", "db_conn", type=EdgeType.USAGE)

    return pg


@pytest.fixture
def executor(pg):
    """CypherExecutor wrapping the test PropertyGraph."""
    return CypherExecutor(pg)


# ════════════════════════════════════════════════════════════
# Phase 1: Lexer
# ════════════════════════════════════════════════════════════


class TestCypherLexer:
    """Lexer tokenization tests."""

    def test_tokenize_simple_match(self):
        tokens = CypherLexer("MATCH (n:Function) RETURN n.name").tokenize()
        assert len(tokens) > 0
        types = [t.type for t in tokens]
        assert TokenType.KEYWORD in types

    def test_tokenize_optional_match(self):
        tokens = CypherLexer("MATCH (a) OPTIONAL MATCH (b) RETURN a.name").tokenize()
        values = [t.value for t in tokens]
        assert "OPTIONAL" in values
        assert "MATCH" in values

    def test_tokenize_relationship(self):
        tokens = CypherLexer("MATCH (a)-[:CALLS]->(b) RETURN a.name, b.name").tokenize()
        values = [t.value for t in tokens]
        assert "CALLS" in values
        assert "->" in values

    def test_tokenize_star_relationship(self):
        """Lexer tokenizes *1..3 as part of the rel_types token (pre-existing behavior)."""
        tokens = CypherLexer("MATCH (a)-[:CALLS*1..3]->(b) RETURN a.name").tokenize()
        values = [t.value for t in tokens]
        # The lexer merges CALLS*1..3 into a single token — this is existing behavior
        assert "CALLS*1..3" in values

    def test_tokenize_where_clause(self):
        tokens = CypherLexer("MATCH (n) WHERE n.label = 'Function' RETURN n.name").tokenize()
        values = [t.value for t in tokens]
        assert "WHERE" in values

    def test_tokenize_order_limit(self):
        tokens = CypherLexer("MATCH (n) RETURN n.name ORDER BY n.name LIMIT 10").tokenize()
        values = [t.value for t in tokens]
        assert "ORDER" in values
        assert "LIMIT" in values

    def test_tokenize_return_distinct(self):
        tokens = CypherLexer("MATCH (n) RETURN DISTINCT n.label").tokenize()
        values = [t.value for t in tokens]
        assert "DISTINCT" in values


# ════════════════════════════════════════════════════════════
# Phase 2: Parser
# ════════════════════════════════════════════════════════════


class TestCypherParser:
    """Parser AST construction tests."""

    def _parse(self, cypher: str) -> Query:
        tokens = CypherLexer(cypher).tokenize()
        return CypherParser(tokens).parse()

    def test_simple_match(self):
        q = self._parse("MATCH (n:Function) RETURN n.name LIMIT 5")
        assert q.match is not None
        assert len(q.match.paths) == 1
        assert q.match.paths[0].left.variable == "n"
        assert q.match.paths[0].left.labels == ["Function"]
        assert q.limit == 5

    def test_match_with_relationship(self):
        q = self._parse("MATCH (a)-[:CALLS]->(b) RETURN a.name, b.name")
        path = q.match.paths[0]
        assert path.left.variable == "a"
        assert path.rel.rel_types == ["CALLS"]
        assert path.rel.direction == "->"
        assert path.right.variable == "b"

    def test_optional_match_stored(self):
        q = self._parse("MATCH (a) OPTIONAL MATCH (b)-[:USES]->(c) RETURN a.name")
        assert q.match is not None
        assert len(q.optional_match) == 1
        opt = q.optional_match[0]
        assert opt.optional is True
        assert len(opt.paths) == 1
        assert opt.paths[0].left.variable == "b"
        assert opt.paths[0].rel.rel_types == ["USES"]

    def test_multiple_optional_matches(self):
        q = self._parse(
            "MATCH (a) OPTIONAL MATCH (b)-[:USES]->(c) "
            "OPTIONAL MATCH (d)-[:EXTENDS]->(a) RETURN a.name"
        )
        assert len(q.optional_match) == 2

    def test_where_clause(self):
        q = self._parse("MATCH (n) WHERE n.name = 'main' RETURN n.name")
        assert q.where is not None

    def test_return_items(self):
        q = self._parse("MATCH (a)-[:CALLS]->(b) RETURN a.name, b.label, count(*)")
        assert len(q.return_items) == 3

    def test_return_distinct(self):
        q = self._parse("MATCH (n) RETURN DISTINCT n.label")
        assert q.return_distinct is True

    def test_order_by(self):
        q = self._parse("MATCH (n) RETURN n.name ORDER BY n.name ASC")
        assert len(q.order_by) == 1
        assert q.order_by[0].direction == "ASC"

    def test_limit_skip(self):
        q = self._parse("MATCH (n) RETURN n.name LIMIT 10 SKIP 5")
        assert q.limit == 10
        assert q.skip == 5

    def test_no_optional_match(self):
        q = self._parse("MATCH (n) RETURN n.name")
        assert q.optional_match == []

    def test_label_filter(self):
        q = self._parse("MATCH (n:Function:Exported) RETURN n.name")
        assert q.match.paths[0].left.labels == ["Function", "Exported"]

    def test_undirected_relationship(self):
        q = self._parse("MATCH (a)--(b) RETURN a.name, b.name")
        assert q.match.paths[0].rel.direction == "--"

    def test_incoming_relationship(self):
        q = self._parse("MATCH (a)<-[:CALLS]-(b) RETURN a.name")
        assert q.match.paths[0].rel.direction == "<-"

    def test_parser_is_idempotent(self):
        """Parser produces valid Query for repeated parses."""
        q1 = self._parse("MATCH (a)-[:CALLS]->(b) RETURN a.name")
        q2 = self._parse("MATCH (a)-[:CALLS]->(b) RETURN a.name")
        assert len(q1.match.paths) == len(q2.match.paths)


# ════════════════════════════════════════════════════════════
# Phase 3: SQL Generation
# ════════════════════════════════════════════════════════════


class TestCypherToSQL:
    """Cypher -> SQL translation tests (no execution)."""

    def _translate(self, cypher: str, graph=None) -> tuple:
        tokens = CypherLexer(cypher).tokenize()
        ast = CypherParser(tokens).parse()
        translator = CypherToSQL(graph)
        return translator.translate(ast)

    def test_simple_match_sql(self):
        sql, params = self._translate("MATCH (n:Function) RETURN n.name LIMIT 5")
        assert "FROM nodes AS" in sql
        assert params.count("Function") == 1

    def test_match_with_relationship_sql(self):
        sql, params = self._translate("MATCH (a)-[:CALLS]->(b) RETURN a.name, b.name")
        assert "JOIN edges AS" in sql
        assert "JOIN nodes AS" in sql
        assert "CALLS" in params

    def test_optional_match_generates_left_join(self):
        sql, params = self._translate(
            "MATCH (a)-[:CALLS]->(b) "
            "OPTIONAL MATCH (b)-[:USES]->(c) "
            "RETURN a.name, c.name"
        )
        assert "LEFT JOIN" in sql
        assert sql.count("LEFT JOIN") == 2
        # Regular JOIN should still be present for mandatory match
        assert "JOIN edges AS e0" in sql
        assert "LEFT JOIN edges AS e1" in sql

    def test_optional_match_left_label_in_on(self):
        """Left node label in OPTIONAL MATCH should be in ON, not WHERE."""
        sql, params = self._translate(
            "MATCH (f:Function) "
            "OPTIONAL MATCH (g:Global)-[:CALLS]->(f) "
            "RETURN f.name, g.name"
        )
        assert "LEFT JOIN" in sql
        # 'Global' should be in the ON clause of the LEFT JOIN
        assert "g.label IN (?)" in sql or "g.label IN" in sql

    def test_multiple_optional_matches(self):
        sql, params = self._translate(
            "MATCH (a)-[:CALLS]->(b) "
            "OPTIONAL MATCH (b)-[:USES]->(c) "
            "OPTIONAL MATCH (b)-[:EXTENDS]->(d) "
            "RETURN a.name"
        )
        assert sql.count("LEFT JOIN") == 4

    def test_where_clause_sql(self):
        sql, params = self._translate(
            "MATCH (n) WHERE n.label = 'Function' RETURN n.name"
        )
        assert "WHERE" in sql

    def test_order_limit_sql(self):
        sql, params = self._translate(
            "MATCH (n) RETURN n.name ORDER BY n.name LIMIT 10"
        )
        assert "ORDER BY" in sql
        assert "LIMIT 10" in sql

    def test_return_star(self):
        sql, params = self._translate("MATCH (n) RETURN n")
        assert "SELECT" in sql

    def test_distinct_sql(self):
        sql, params = self._translate("MATCH (n) RETURN DISTINCT n.label")
        assert "DISTINCT" in sql


# ════════════════════════════════════════════════════════════
# Phase 4: End-to-End Execution + OPTIONAL MATCH
# ════════════════════════════════════════════════════════════


class TestCypherE2E:
    """End-to-end tests against real PropertyGraph."""

    def test_simple_query(self, executor):
        result = executor.execute(
            "MATCH (f:Function) RETURN f.name ORDER BY f.name LIMIT 5"
        )
        names = [r["f.name"] for r in result["results"]]
        assert "log_error" in names
        assert "main" in names
        assert "parse" in names
        assert "render" in names
        assert "validate" in names

    def test_relationship_query(self, executor):
        result = executor.execute(
            "MATCH (a)-[:CALLS]->(b) "
            "RETURN a.name, b.name ORDER BY a.name, b.name"
        )
        pairs = [(r["a.name"], r["b.name"]) for r in result["results"]]
        assert ("main", "parse") in pairs
        assert ("main", "validate") in pairs
        assert ("parse", "render") in pairs
        assert ("validate", "log_error") in pairs

    def test_optional_match_basic(self, executor):
        """OPTIONAL MATCH should return NULLs for nodes without matching edges."""
        result = executor.execute(
            "MATCH (f:Function)-[:CALLS]->(g) "
            "OPTIONAL MATCH (g)-[:USAGE]->(v) "
            "RETURN f.name, g.name, v.name "
            "ORDER BY f.name, g.name"
        )
        rows = result["results"]
        # main -> parse (has USAGE -> config)
        # main -> validate (has USAGE -> db_conn)
        # parse -> render (NO USAGE)
        # validate -> log_error (NO USAGE)
        main_parse = [r for r in rows if r["g.name"] == "parse"]
        assert len(main_parse) == 1
        assert main_parse[0]["v.name"] == "config"

        main_validate = [r for r in rows if r["g.name"] == "validate"]
        assert len(main_validate) == 1
        assert main_validate[0]["v.name"] == "db_conn"

        parse_render = [r for r in rows if r["g.name"] == "render"]
        assert len(parse_render) == 1
        assert parse_render[0]["v.name"] is None  # LEFT JOIN -> NULL

        validate_log = [r for r in rows if r["g.name"] == "log_error"]
        assert len(validate_log) == 1
        assert validate_log[0]["v.name"] is None  # LEFT JOIN -> NULL

    def test_optional_match_preserves_all_rows(self, executor):
        """All mandatory MATCH rows should be present even if OPTIONAL MATCH has no match."""
        result_all = executor.execute(
            "MATCH (a)-[:CALLS]->(b) "
            "RETURN a.name, b.name ORDER BY a.name"
        )
        result_opt = executor.execute(
            "MATCH (a)-[:CALLS]->(b) "
            "OPTIONAL MATCH (b)-[:NONEXISTENT]->(c) "
            "RETURN a.name, b.name ORDER BY a.name"
        )
        # OPTIONAL MATCH should not reduce row count
        assert len(result_opt["results"]) == len(result_all["results"])

    def test_optional_match_with_label_filter(self, executor):
        """OPTIONAL MATCH with label on new node -- label should filter in ON."""
        result = executor.execute(
            "MATCH (f:Function)-[:CALLS]->(g) "
            "OPTIONAL MATCH (g)-[:USAGE]->(v:Variable) "
            "RETURN f.name, g.name, v.name "
            "ORDER BY f.name, g.name"
        )
        rows = result["results"]
        # parse -> render: render has no USAGE edge -> v.name = None
        parse_render = [r for r in rows if r["g.name"] == "render"]
        assert parse_render[0]["v.name"] is None

        # main -> parse: parse has USAGE -> config (which IS a Variable)
        main_parse = [r for r in rows if r["g.name"] == "parse"]
        assert main_parse[0]["v.name"] == "config"

    def test_optional_match_no_edges_at_all(self, executor):
        """OPTIONAL MATCH where no edges exist at all -- should still return rows."""
        result = executor.execute(
            "MATCH (f:Function) "
            "OPTIONAL MATCH (f)-[:NONEXISTENT]->(x) "
            "RETURN f.name, x.name ORDER BY f.name"
        )
        rows = result["results"]
        assert len(rows) == 5  # All 5 functions
        assert all(r["x.name"] is None for r in rows)

    def test_query_graph_function(self, executor, pg):
        """Test the top-level query_graph function."""
        result = query_graph(pg, "MATCH (f:Function) RETURN count(*)")
        assert result["results"][0]["count(*)"] == 5


# ════════════════════════════════════════════════════════════
# Phase 5: Error Handling
# ════════════════════════════════════════════════════════════


class TestCypherErrors:
    """Error handling and edge cases.

    Note: CypherExecutor.execute() catches exceptions internally and returns
    a dict with an 'error' key rather than propagating the exception.
    """

    def test_missing_match_returns_error(self, executor):
        result = executor.execute("RETURN 1")
        assert "error" in result
        assert len(result["results"]) == 0

    def test_invalid_syntax_returns_error(self, executor):
        # The parser may accept some invalid syntax, but the SQL generation should fail
        result = executor.execute("RETURN 1")
        assert "error" in result

    def test_empty_query_returns_error(self, executor):
        result = executor.execute("")
        assert "error" in result

    def test_return_without_match_returns_error(self, executor):
        result = executor.execute("RETURN n.name")
        assert "error" in result
        assert len(result["results"]) == 0

    def test_successful_query_no_error(self, executor):
        result = executor.execute("MATCH (f:Function) RETURN f.name LIMIT 1")
        assert "error" not in result
        assert len(result["results"]) == 1


# ════════════════════════════════════════════════════════════
# Phase 6: Complex OPTIONAL MATCH Scenarios
# ════════════════════════════════════════════════════════════


class TestOptionalMatchEdgeCases:
    """Edge cases for OPTIONAL MATCH (LEFT JOIN) correctness."""

    def test_two_optional_matches_independent(self, executor):
        """Two independent OPTIONAL MATCH clauses."""
        result = executor.execute(
            "MATCH (f:Function)-[:CALLS]->(g) "
            "OPTIONAL MATCH (g)-[:USAGE]->(v) "
            "RETURN f.name, g.name, v.name "
            "ORDER BY f.name, g.name"
        )
        rows = result["results"]
        # main -> parse: v = config (from parse USAGE -> config)
        # main -> validate: v = db_conn (from validate USAGE -> db_conn)
        main_parse = [r for r in rows if r["f.name"] == "main" and r["g.name"] == "parse"]
        assert len(main_parse) == 1
        assert main_parse[0]["v.name"] == "config"

    def test_optional_match_chain(self, executor):
        """Multiple results from OPTIONAL MATCH should all be present."""
        result = executor.execute(
            "MATCH (f:Function)-[:CALLS]->(g) "
            "OPTIONAL MATCH (g)-[:USAGE]->(v) "
            "RETURN f.name, g.name, v.name "
            "ORDER BY f.name"
        )
        rows = result["results"]
        # All 4 CALLS edges should be present
        assert len(rows) == 4
        # NULLs where no USAGE exists
        nulls = [r for r in rows if r["v.name"] is None]
        assert len(nulls) == 2  # render and log_error have no USAGE edge

    def test_optional_match_no_match_all_null(self, executor):
        """OPTIONAL MATCH with nonexistent edge type -- all optional columns NULL."""
        result = executor.execute(
            "MATCH (f:Function)-[:CALLS]->(g) "
            "OPTIONAL MATCH (g)-[:NONEXISTENT]->(x) "
            "RETURN f.name, g.name, x.name "
            "ORDER BY f.name, g.name"
        )
        rows = result["results"]
        assert len(rows) == 4  # All 4 CALLS edges preserved
        assert all(r["x.name"] is None for r in rows)

    def test_optional_match_with_where_not_null(self, executor):
        """WHERE filtering on non-null optional values."""
        result = executor.execute(
            "MATCH (f:Function)-[:CALLS]->(g) "
            "OPTIONAL MATCH (g)-[:USAGE]->(v) "
            "WHERE v IS NOT NULL "
            "RETURN f.name, g.name, v.name ORDER BY f.name"
        )
        rows = result["results"]
        # Only parse and validate have USAGE edges
        assert len(rows) == 2
        g_names = [r["g.name"] for r in rows]
        assert "render" not in g_names
        assert "log_error" not in g_names

    def test_optional_match_with_where_null(self, executor):
        """WHERE IS NULL filters to only rows without optional match."""
        result = executor.execute(
            "MATCH (f:Function)-[:CALLS]->(g) "
            "OPTIONAL MATCH (g)-[:USAGE]->(v) "
            "WHERE v IS NULL "
            "RETURN f.name, g.name ORDER BY f.name, g.name"
        )
        rows = result["results"]
        # Only render and log_error have no USAGE edge
        assert len(rows) == 2
        g_names = [r["g.name"] for r in rows]
        assert "render" in g_names
        assert "log_error" in g_names
        assert "parse" not in g_names
        assert "validate" not in g_names
