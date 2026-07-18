"""Cypher query engine — компонент для подмножества openCypher."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.search.cypher_ast import (
    ASTNode,
    Comparison,
    MatchClause,
    NodePattern,
    OrderItem,
    PathPattern,
    Query,
    RelPattern,
    ReturnItem,
    WhereClause,
    _BinaryOp,
    _ExistsSubquery,
    _LabelTest,
    _UnaryOp,
)
from src.core.search.cypher_lexer import (
    Token,
    TokenType,
)

# ════════════════════════════════════════════════════════════
# Parser (Recursive Descent)
# ════════════════════════════════════════════════════════════

class CypherParser:
    """Рекурсивный парсер подмножества openCypher."""

    def __init__(self, tokens: List[Token]):
        self._tokens = tokens
        self._pos = 0

    def peek(self) -> Optional[Token]:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def advance(self) -> Token:
        t = self._tokens[self._pos]
        self._pos += 1
        return t

    def expect(self, *expected: str) -> Token:
        t = self.advance()
        if t.value.upper() not in expected and t.type not in (
            (TokenType.PUNCTUATION,) if all(e in "()[]{}.,:*->" for e in expected) else ()
        ):
            raise SyntaxError(
                f"Expected {expected} at pos {t.pos}, got '{t.value}'"
            )
        return t

    def parse(self) -> Query:
        """Точка входа: парсит полный запрос."""
        query = Query(
            match=None, where=None, return_distinct=False,
            return_items=[], order_by=[], limit=None, skip=None,
            optional_match=[],
        )

        # MATCH / OPTIONAL MATCH
        while self.peek() and self.peek().value.upper() in ("MATCH", "OPTIONAL"):
            token = self.advance()
            optional = token.value.upper() == "OPTIONAL"
            if optional:
                self.expect("MATCH")

            paths = self._parse_path_patterns()
            mc = MatchClause(optional=optional, paths=paths)

            if optional:
                query.optional_match.append(mc)
            else:
                if query.match is None:
                    query.match = mc
                else:
                    # Несколько MATCH — AND семантика
                    query.match.paths.extend(mc.paths)
                    query.match.optional = query.match.optional and mc.optional

        # WHERE
        if self.peek() and self.peek().value.upper() == "WHERE":
            self.advance()
            query.where = WhereClause(expr=self._parse_or_expr())

        # RETURN
        if self.peek() and self.peek().value.upper() == "RETURN":
            self.advance()
            if self.peek() and self.peek().value.upper() == "DISTINCT":
                self.advance()
                query.return_distinct = True
            query.return_items = self._parse_return_items()

        # ORDER BY
        if self.peek() and self.peek().value.upper() == "ORDER":
            self.advance()
            self.expect("BY")
            query.order_by = self._parse_order_items()

        # LIMIT / SKIP
        while self.peek() and self.peek().value.upper() in ("LIMIT", "SKIP"):
            kw = self.advance().value.upper()
            num = self.advance()
            val = int(num.value)
            if kw == "LIMIT":
                query.limit = val
            else:
                query.skip = val

        return query

    def _parse_path_patterns(self) -> List[PathPattern]:
        """Парсит один или несколько паттернов, разделённых запятыми."""
        patterns = []
        patterns.append(self._parse_path_pattern())

        while self.peek() and self.peek().value == ",":
            self.advance()
            patterns.append(self._parse_path_pattern())

        return patterns

    def _parse_path_pattern(self) -> PathPattern:
        """Парсит (n:Label)-[:TYPE]->(m)."""
        self.expect("(")
        left = self._parse_node_pattern()
        self.expect(")")

        # Если следующий токен не стрелка и не дефис — одиночный узел (n)
        nxt = self.peek()
        if not nxt or nxt.value not in ("->", "<-", "--", "-"):
            rel = RelPattern(
                variable=None, rel_types=[], direction="--",
                min_hops=None, max_hops=None, properties={},
            )
            return PathPattern(left=left, rel=rel, right=None)

        rel = self._parse_rel_pattern()
        self.expect("(")
        right = self._parse_node_pattern()
        self.expect(")")

        return PathPattern(left=left, rel=rel, right=right)

    def _parse_node_pattern(self) -> NodePattern:
        """Парсит n:Label {prop: 'val'}."""
        var = None
        labels = []
        props = {}

        if self.peek() and self.peek().type == TokenType.IDENTIFIER:
            var = self.advance().value

        while self.peek() and self.peek().type == TokenType.LABEL:
            labels.append(self.advance().value)

        # Свойства {name: 'value'}
        if self.peek() and self.peek().value == "{":
            props = self._parse_properties()

        return NodePattern(variable=var, labels=labels, properties=props)

    def _parse_rel_pattern(self) -> RelPattern:
        """Парсит [r:TYPE*1..3] или просто -> / <- / --"""
        rel_types = []
        var = None
        min_hops = None
        max_hops = None
        props = {}
        direction = "--"

        # Пропускаем начальный дефис (n)-[ или n-->
        if self.peek() and self.peek().value == "-":
            self.advance()  # consume the -

        if self.peek() and self.peek().value == "[":
            self.advance()
            if self.peek().type == TokenType.IDENTIFIER:
                var = self.advance().value
            # Пропускаем : перед TYPE
            if self.peek() and self.peek().value == ":":
                self.advance()
            # REL_TYPE: :TYPE*1..3 как один токен (из лексера)
            if self.peek() and self.peek().type == TokenType.REL_TYPE:
                rt = self.advance().value
                if "*" in rt:
                    parts = rt.split("*")
                    rel_types.append(parts[0])
                    if parts[1]:
                        range_parts = parts[1].split("..")
                        min_hops = int(range_parts[0]) if range_parts[0] else None
                        max_hops = int(range_parts[1]) if len(range_parts) > 1 and range_parts[1] else None
                else:
                    rel_types.append(rt)
            elif self.peek() and self.peek().type == TokenType.LABEL:
                rel_types.append(self.advance().value)
                # Парсим *min..max после label: CALLS*1..3
                if self.peek() and self.peek().value == "*":
                    self.advance()  # consume *
                    if self.peek() and self.peek().type == TokenType.NUMBER:
                        min_hops = int(self.advance().value)
                        if self.peek() and self.peek().value == "..":
                            self.advance()  # consume ..
                            if self.peek() and self.peek().type == TokenType.NUMBER:
                                max_hops = int(self.advance().value)
                            else:
                                max_hops = None
                        else:
                            max_hops = min_hops
                    else:
                        max_hops = None  # * без чисел = неограниченно
            if self.peek() and self.peek().value == "{":
                props = self._parse_properties()
            self.expect("]")

        # Определяем направление (после [r:TYPE] или после дефиса)
        if self.peek():
            if self.peek().value == "->":
                direction = "->"
                self.advance()
            elif self.peek().value == "<-":
                direction = "<-"
                self.advance()
            elif self.peek().value == "-":
                # -- для undirected
                self.advance()
                if self.peek() and self.peek().value == "-":
                    self.advance()
                direction = "--"

        return RelPattern(
            variable=var, rel_types=rel_types, direction=direction,
            min_hops=min_hops, max_hops=max_hops, properties=props,
        )

    def _parse_properties(self) -> Dict[str, Any]:
        """Парсит {key: 'value', key2: 42}."""
        props = {}
        self.expect("{")
        while self.peek() and self.peek().value != "}":
            key = self.advance().value
            self.expect(":")
            value = self._parse_literal()
            props[key] = value
            if self.peek() and self.peek().value == ",":
                self.advance()
        self.expect("}")
        return props

    def _parse_literal(self) -> Any:
        """Парсит литерал: строку, число, булево, NULL, список."""
        t = self.advance()
        if t.type == TokenType.STRING:
            return t.value
        if t.type == TokenType.NUMBER:
            if "." in t.value:
                return float(t.value)
            return int(t.value)
        if t.value.upper() == "TRUE":
            return True
        if t.value.upper() == "FALSE":
            return False
        if t.value.upper() == "NULL":
            return None
        if t.value == "[":
            items = []
            while self.peek() and self.peek().value != "]":
                items.append(self._parse_literal())
                if self.peek() and self.peek().value == ",":
                    self.advance()
            self.expect("]")
            return items
        return t.value

    # ── WHERE expression parser ───────────────────────────

    def _parse_or_expr(self) -> ASTNode:
        """OR."""
        left = self._parse_and_expr()
        while self.peek() and self.peek().value.upper() == "OR":
            self.advance()
            right = self._parse_and_expr()
            left = _BinaryOp("OR", left, right)
        return left

    def _parse_and_expr(self) -> ASTNode:
        """AND."""
        left = self._parse_not_expr()
        while self.peek() and self.peek().value.upper() == "AND":
            self.advance()
            right = self._parse_not_expr()
            left = _BinaryOp("AND", left, right)
        return left

    def _parse_not_expr(self) -> ASTNode:
        """NOT expr."""
        if self.peek() and self.peek().value.upper() == "NOT":
            self.advance()
            return _UnaryOp("NOT", self._parse_primary_expr())
        return self._parse_primary_expr()

    def _parse_primary_expr(self) -> ASTNode:
        """Primary expression: сравнение, EXISTS, (expr), n:Label."""
        # EXISTS { (n)-[:TYPE]->() }
        if self.peek() and self.peek().value.upper() == "EXISTS":
            self.advance()
            self.expect("{")
            pattern = self._parse_path_pattern()
            self.expect("}")
            return _ExistsSubquery(pattern)

        # n:Label — label test
        if (self.peek() and self.peek().type == TokenType.IDENTIFIER
                and self._pos + 1 < len(self._tokens)
                and self._tokens[self._pos + 1].type == TokenType.LABEL):
            var = self.advance().value
            label = self.advance().value
            return _LabelTest(var, label)

        # ( expr )
        if self.peek() and self.peek().value == "(":
            self.expect("(")
            expr = self._parse_or_expr()
            self.expect(")")
            return expr

        # Сравнение: n.prop OP value
        left = self._parse_property_ref()
        if self.peek() and self.peek().type in (TokenType.OPERATOR, TokenType.KEYWORD):
            op = self.advance()
            # KEYWORD может быть IN, CONTAINS, STARTS WITH, ENDS WITH, IS
            if op.value.upper() == "IS":
                if self.peek().value.upper() == "NOT":
                    self.advance()
                    self.expect("NULL")
                    return Comparison(left, "IS NOT NULL", None)
                else:
                    self.expect("NULL")
                    return Comparison(left, "IS NULL", None)

            keyword_ops = {"IN", "CONTAINS", "STARTS", "ENDS"}
            if op.value.upper() in keyword_ops:
                if op.value.upper() == "STARTS":
                    self.expect("WITH")
                    right = self._parse_literal_or_expr()
                    return Comparison(left, "STARTS WITH", right)
                if op.value.upper() == "ENDS":
                    self.expect("WITH")
                    right = self._parse_literal_or_expr()
                    return Comparison(left, "ENDS WITH", right)
                right = self._parse_literal_or_expr()
                return Comparison(left, op.value, right)

            right = self._parse_literal_or_expr()
            return Comparison(left, op.value, right)

        return left

    def _parse_property_ref(self) -> str:
        """Парсит n.name, n, count(*)."""
        t = self.advance()
        result = t.value

        # n.name или n.qualified_name
        if self.peek() and self.peek().value == ".":
            self.advance()
            prop = self.advance()
            result = f"{result}.{prop.value}"

        # count(*)
        if self.peek() and self.peek().value == "(":
            self.advance()
            if self.peek().value == "*":
                result = f"{result}(*)"
                self.advance()
            else:
                # count(n.name)
                inner = self._parse_property_ref()
                result = f"{result}({inner})"
            self.expect(")")

        return result

    def _parse_literal_or_expr(self) -> Any:
        """Литерал или подвыражение."""
        t = self.peek()
        if t.type == TokenType.STRING:
            return self.advance().value
        if t.type == TokenType.NUMBER:
            raw = self.advance().value
            return float(raw) if "." in raw else int(raw)
        if t.value == "[":
            self.advance()  # [
            items = []
            while self.peek() and self.peek().value != "]":
                items.append(self._parse_literal_or_expr())
                if self.peek().value == ",":
                    self.advance()
            self.advance()  # ]
            return items
        if t.value.upper() in ("TRUE", "FALSE"):
            return self.advance().value.upper() == "TRUE"
        if t.value.upper() == "NULL":
            self.advance()
            return None
        # Свойство как выражение (n.name)
        return self._parse_property_ref()

    def _parse_return_items(self) -> List[ReturnItem]:
        """Парсит n.name, count(*) AS c, ..."""
        items = []
        items.append(self._parse_return_item())
        while self.peek() and self.peek().value == ",":
            self.advance()
            items.append(self._parse_return_item())
        return items

    def _parse_return_item(self) -> ReturnItem:
        """Парсит один return item: expr [AS alias]."""
        expr = self._parse_property_ref()
        alias = None
        if self.peek() and self.peek().value.upper() == "AS":
            self.advance()
            alias = self.advance().value
        return ReturnItem(expression=expr, alias=alias)

    def _parse_order_items(self) -> List[OrderItem]:
        """Парсит n.name ASC, ..."""
        items = []
        items.append(self._parse_order_item())
        while self.peek() and self.peek().value == ",":
            self.advance()
            items.append(self._parse_order_item())
        return items

    def _parse_order_item(self) -> OrderItem:
        expr = self._parse_property_ref()
        direction = "ASC"
        if self.peek() and self.peek().value.upper() in ("ASC", "DESC"):
            direction = self.advance().value.upper()
        return OrderItem(expression=expr, direction=direction)
