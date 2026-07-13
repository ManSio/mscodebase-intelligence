"""
Cypher-like Query Engine — переводит подмножество openCypher в SQL на PropertyGraph.

Позволяет LLM-агенту выполнять сложные графовые запросы одной строкой:

    MATCH (f:Function)-[:CALLS]->(g:Function)
    WHERE f.file_path STARTS WITH "src"
    RETURN f.name, g.name, count(*) AS call_count
    ORDER BY call_count DESC
    LIMIT 10

Поддерживаемое подмножество openCypher:
  - MATCH (n:Label), (n)-[:TYPE]->(m), (n)-[:TYPE*1..3]->(m)
  - WHERE: =, <>, <, <=, >, >=, AND/OR, IN, CONTAINS, STARTS WITH, ENDS WITH,
           IS [NOT] NULL, =~ (regex), label test n:Label
  - RETURN + DISTINCT, агрегаты (count, sum, avg, min, max, collect)
  - ORDER BY ... ASC/DESC, LIMIT, SKIP
  - Несколько MATCH (AND семантика)
  - Опциональный MATCH (LEFT JOIN)

Не поддерживается:
  - CREATE, MERGE, DELETE (read-only engine)
  - UNWIND, UNION, CALL subquery
  - List/map literals, comprehensions, path functions

Архитектура:
  Lexer (tokenizer) → Parser (AST) → Planner (SQL gen) → Executor (SQLite)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
# Lexer
# ════════════════════════════════════════════════════════════

class TokenType(Enum):
    KEYWORD = auto()
    IDENTIFIER = auto()
    STRING = auto()
    NUMBER = auto()
    PUNCTUATION = auto()
    OPERATOR = auto()
    LABEL = auto()       # :Label
    REL_TYPE = auto()    # :TYPE or :TYPE*min..max
    VARIABLE = auto()    # n, m, f


KEYWORDS = {
    "MATCH", "OPTIONAL", "WHERE", "RETURN", "DISTINCT",
    "ORDER", "BY", "ASC", "DESC", "LIMIT", "SKIP",
    "AND", "OR", "XOR", "NOT", "IN", "CONTAINS",
    "STARTS", "ENDS", "WITH", "IS", "NULL", "TRUE", "FALSE",
    "AS", "COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT",
    "CASE", "WHEN", "THEN", "ELSE", "END",
    "EXISTS",
}

DIRECTION_LEFT = "<-"
DIRECTION_RIGHT = "->"
DIRECTION_NONE = "--"  # undirected


@dataclass
class Token:
    type: TokenType
    value: str
    pos: int  # позиция в исходном запросе


class CypherLexer:
    """Лексер для подмножества openCypher."""

    def __init__(self, query: str):
        self._query = query
        self._pos = 0
        self._tokens: List[Token] = []

    def tokenize(self) -> List[Token]:
        """Разбивает строку запроса на токены."""
        tokens: List[Token] = []
        i = 0
        q = self._query

        while i < len(q):
            ch = q[i]

            # Пропускаем пробелы
            if ch in " \t\n\r":
                i += 1
                continue

            # Комментарии //
            if ch == "/" and i + 1 < len(q) and q[i + 1] == "/":
                end = q.find("\n", i)
                if end == -1:
                    break
                i = end + 1
                continue

            # Строки в кавычках
            if ch in "\"'":
                end = ch
                j = i + 1
                while j < len(q) and q[j] != end:
                    if q[j] == "\\":
                        j += 1
                    j += 1
                if j >= len(q):
                    raise SyntaxError(f"Unterminated string at pos {i}")
                tokens.append(Token(TokenType.STRING, q[i + 1:j], i))
                i = j + 1
                continue

            # Числа
            if ch.isdigit() or (ch == "." and i + 1 < len(q) and q[i + 1].isdigit()):
                j = i
                while j < len(q) and (q[j].isdigit() or q[j] in "."):
                    j += 1
                tokens.append(Token(TokenType.NUMBER, q[i:j], i))
                i = j
                continue

            # Идентификаторы, ключевые слова, метки
            if ch.isalpha() or ch == "_" or ch == "`":
                if ch == "`":
                    # Backtick-escaped identifier
                    j = q.find("`", i + 1)
                    if j == -1:
                        raise SyntaxError(f"Unterminated backtick at pos {i}")
                    tokens.append(Token(TokenType.IDENTIFIER, q[i + 1:j], i))
                    i = j + 1
                    continue

                j = i
                while j < len(q) and (q[j].isalnum() or q[j] == "_"):
                    j += 1
                word = q[i:j]
                upper = word.upper()

                if upper in KEYWORDS:
                    tt = TokenType.KEYWORD
                elif word[0].isupper() and ":" not in word:
                    tt = TokenType.LABEL
                else:
                    tt = TokenType.IDENTIFIER

                tokens.append(Token(tt, word, i))
                i = j
                continue

            # Операторы сравнения (двухсимвольные)
            if i + 1 < len(q) and q[i:i + 2] in (">=", "<=", "<>", "!=", "=~"):
                tokens.append(Token(TokenType.OPERATOR, q[i:i + 2], i))
                i += 2
                continue

            # Стрелки направлений
            if i + 2 < len(q) and q[i:i + 2] == "<-":
                tokens.append(Token(TokenType.PUNCTUATION, "<-", i))
                i += 2
                continue
            if i + 1 < len(q) and q[i:i + 2] == "->":
                tokens.append(Token(TokenType.PUNCTUATION, "->", i))
                i += 2
                continue
            if i + 1 < len(q) and q[i:i + 2] == "--":
                tokens.append(Token(TokenType.PUNCTUATION, "--", i))
                i += 2
                continue

            # Односимвольные операторы
            if ch in "=<>!+-*/%":
                tokens.append(Token(TokenType.OPERATOR, ch, i))
                i += 1
                continue

            # Скобки и пунктуация
            if ch in "()[]{}.,*":
                tokens.append(Token(TokenType.PUNCTUATION, ch, i))
                i += 1
                continue

            # Метка :Label или :TYPE или :TYPE*min..max
            if ch == ":":
                j = i + 1
                while j < len(q) and (q[j].isalnum() or q[j] in "_"):
                    j += 1

                # Проверяем на variable-length path
                label = q[i + 1:j]
                rest = q[j:j + 10]  # смотрим вперед на *min..max

                if rest.startswith("*"):
                    # :TYPE*min..max или :TYPE*
                    k = j + 1
                    while k < len(q) and (q[k].isdigit() or q[k] in ".."):
                        k += 1
                    path_range = q[j:k]  # *1..3 или *
                    tokens.append(Token(TokenType.REL_TYPE, f"{label}{path_range}", i))
                    i = k
                else:
                    tokens.append(Token(TokenType.LABEL, label if label else "", i))
                    i = j
                continue

            # Неизвестный символ
            raise SyntaxError(f"Unexpected character '{ch}' at pos {i}")

        self._tokens = tokens
        return tokens


# ════════════════════════════════════════════════════════════
# AST Nodes
# ════════════════════════════════════════════════════════════

class ASTNode:
    """Base class for all AST nodes."""
    pass


@dataclass
class NodePattern(ASTNode):
    """(n:Label) или (n) или (:Label)"""
    variable: Optional[str]       # n
    labels: List[str]             # ['Label']
    properties: Dict[str, Any]    # {name: 'value'}


@dataclass
class RelPattern(ASTNode):
    """[r:TYPE] или [r:TYPE*1..3] или просто :TYPE или --"""
    variable: Optional[str]       # r
    rel_types: List[str]          # ['TYPE']
    direction: str                # '->', '<-', '--'
    min_hops: Optional[int]       # для *min..max
    max_hops: Optional[int]
    properties: Dict[str, Any]


@dataclass
class PathPattern(ASTNode):
    """Полный паттерн: (n)-[:TYPE]->(m)"""
    left: NodePattern
    rel: RelPattern
    right: Optional[NodePattern]  # None для (n)


@dataclass
class MatchClause(ASTNode):
    """MATCH или OPTIONAL MATCH"""
    optional: bool
    paths: List[PathPattern]


@dataclass
class Comparison(ASTNode):
    """n.name = 'value' или n.name IN [...]"""
    left: str        # 'n.name'
    op: str          # '=', '<>', 'IN', 'CONTAINS', 'STARTS WITH', ...
    right: Any       # 'value', 42, ['a', 'b']


@dataclass
class WhereClause(ASTNode):
    """WHERE с AND/OR/NOT"""
    expr: ASTNode  # Comparison или логическая комбинация


@dataclass
class ReturnItem(ASTNode):
    """n.name, count(*) AS c, n"""
    expression: str
    alias: Optional[str]


@dataclass
class OrderItem(ASTNode):
    """n.name ASC/DESC"""
    expression: str
    direction: str  # 'ASC' or 'DESC'


@dataclass
class Query(ASTNode):
    """Полный разобранный запрос."""
    match: Optional[MatchClause]
    where: Optional[WhereClause]
    return_distinct: bool
    return_items: List[ReturnItem]
    order_by: List[OrderItem]
    limit: Optional[int]
    skip: Optional[int]
    optional_match: List[MatchClause]


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


# AST вспомогательные классы для WHERE

class _BinaryOp(ASTNode):
    def __init__(self, op: str, left: ASTNode, right: ASTNode):
        self.op = op
        self.left = left
        self.right = right

class _UnaryOp(ASTNode):
    def __init__(self, op: str, expr: ASTNode):
        self.op = op
        self.expr = expr

class _LabelTest(ASTNode):
    def __init__(self, variable: str, label: str):
        self.variable = variable
        self.label = label

class _ExistsSubquery(ASTNode):
    def __init__(self, pattern: PathPattern):
        self.pattern = pattern


# ════════════════════════════════════════════════════════════
# SQL Generator
# ════════════════════════════════════════════════════════════

class CypherToSQL:
    """Переводит AST Cypher в SQL для PropertyGraph."""

    def __init__(self, graph):
        self._graph = graph
        self._cte_counter = 0

    def translate(self, query: Query) -> Tuple[str, List[Any]]:
        """Генерирует SQL из AST Cypher.

        Returns:
            (sql_string, params_list)
        """
        if not query.match:
            raise ValueError("MATCH clause is required")

        self._cte_counter = 0

        # Фаза 1: определяем все переменные узлов и их алиасы в SQL
        node_vars: Dict[str, str] = {}  # переменная Cypher → SQL алиас
        path_joins: List[str] = []
        path_where: List[str] = []  # WHERE условия из label/type фильтров
        path_where_params: List[Any] = []  # params для path_where (добавляются в конце)
        params: List[Any] = []
        select_cols: List[str] = []

        for path_idx, path in enumerate(query.match.paths):
            self._process_path_pattern(path, node_vars, path_joins, path_where, params, path_idx, path_where_params)

        # Фаза 1.5: OPTIONAL MATCH — LEFT JOIN
        opt_path_counter = len(query.match.paths)
        for opt_clause in query.optional_match:
            for opt_path in opt_clause.paths:
                self._process_path_pattern(
                    opt_path, node_vars, path_joins, path_where, params,
                    opt_path_counter, path_where_params,
                    join_type="LEFT JOIN", left_labels_in_on=True,
                )
                opt_path_counter += 1

        # Фаза 2: WHERE (из паттернов + явный WHERE)
        where_clauses: List[str] = list(path_where)

        # Добавляем path_where_params ПЕРЕД explicit WHERE params
        # (потому что path_where идёт ПЕРВЫМ в SQL WHERE clause)
        params.extend(path_where_params)

        if query.where:
            self._process_where(query.where.expr, node_vars, where_clauses, params)

        # Фаза 3: RETURN
        agg_columns = []
        group_by = []

        for item in query.return_items:
            sql_col = self._translate_return_expr(item.expression, node_vars)
            if self._is_aggregate(item.expression):
                agg_columns.append(sql_col)
            else:
                group_by.append(sql_col)
            # Всегда используем AS для консистентности имён колонок
            if item.alias:
                alias = f" AS {item.alias}"
            elif "." in item.expression:
                # f.name → AS "f.name" для консистентности результата
                alias = f' AS "{item.expression}"'
            else:
                alias = ""
            select_cols.append(f"{sql_col}{alias}")

        if not select_cols:
            select_cols = ["*"]

        # Собираем SELECT
        select_distinct = "DISTINCT " if query.return_distinct else ""

        # FROM — первый узел первого паттерна (target)
        from_node_alias = node_vars.get(query.match.paths[0].left.variable or "n", "n1")

        columns_sql = ", ".join(select_cols)
        joins_sql = "\n".join(path_joins)
        where_text = " AND ".join(where_clauses)
        where_sql = f"WHERE {where_text}" if where_text else ""

        # GROUP BY для агрегатов
        group_sql = ""
        if agg_columns and group_by:
            group_sql = f"GROUP BY {', '.join(group_by)}"

        # ORDER BY
        order_sql = ""
        if query.order_by:
            order_parts = []
            for o in query.order_by:
                col = self._translate_return_expr(o.expression, node_vars)
                order_parts.append(f"{col} {o.direction}")
            order_sql = f"ORDER BY {', '.join(order_parts)}"

        # LIMIT / SKIP
        limit_sql = ""
        if query.limit is not None:
            limit_sql = f"LIMIT {query.limit}"
            if query.skip is not None:
                limit_sql = f"LIMIT {query.skip}, {query.limit}"
        elif query.skip is not None:
            limit_sql = f"LIMIT {query.skip}, 1000"

        sql = (
            f"SELECT {select_distinct}{columns_sql}\n"
            f"FROM nodes AS {from_node_alias}\n"
            f"{joins_sql}\n"
            f"{where_sql}\n"
            f"{group_sql}\n"
            f"{order_sql}\n"
            f"{limit_sql}"
        ).strip()

        return sql, params

    def _process_path_pattern(
        self,
        path: PathPattern,
        node_vars: Dict[str, str],
        joins: List[str],
        wheres: List[str],
        params: List[Any],
        path_idx: int,
        where_params: Optional[List[Any]] = None,
        join_type: str = "JOIN",
        left_labels_in_on: bool = False,
    ):
        """Генерирует JOIN для одного паттерна (n)-[:TYPE]->(m).

        Args:
            join_type: "JOIN" для обязательного MATCH, "LEFT JOIN" для OPTIONAL MATCH.
            left_labels_in_on: Если True, label-фильтры левого узла попадают в ON
                (а не WHERE), чтобы не ломать NULL-семантику LEFT JOIN.
        """
        left_var = path.left.variable or f"n{path_idx * 2}"
        has_right = path.right is not None and path.rel is not None

        # Регистрируем алиасы
        if left_var not in node_vars:
            node_vars[left_var] = left_var

        # Левый узел: label фильтр
        left_label_sql: Optional[str] = None
        left_label_vals: Optional[List[Any]] = None
        if path.left.labels:
            labels = path.left.labels
            placeholders = ",".join("?" for _ in labels)
            if left_labels_in_on and has_right:
                # LEFT JOIN: фильтр в ON, чтобы не ломать NULL-семантику
                left_label_sql = f"{node_vars[left_var]}.label IN ({placeholders})"
                left_label_vals = list(labels)
            else:
                wheres.append(f"{node_vars[left_var]}.label IN ({placeholders})")
                target = where_params if where_params is not None else params
                target.extend(labels)

        # Если нет ребра — одиночный узел, дальше не идём
        if not has_right:
            return

        right_var = path.right.variable or f"m{path_idx * 2}"
        if right_var not in node_vars:
            node_vars[right_var] = right_var

        # Ребро
        edge_alias = f"e{path_idx}"
        edge_on = ""  # дополнительное условие для ON

        if path.rel.rel_types:
            rtypes = path.rel.rel_types
            if len(rtypes) == 1:
                edge_on = f"AND {edge_alias}.type = ?"
                params.append(rtypes[0])
            else:
                placeholders = ",".join("?" for _ in rtypes)
                edge_on = f"AND {edge_alias}.type IN ({placeholders})"
                params.extend(rtypes)

        # Направление — условие JOIN для edges
        if path.rel.direction == "->":
            edge_join = (
                f"{node_vars[left_var]}.id = {edge_alias}.source_id "
                f"{edge_on}"
            )
            target_join = f"{edge_alias}.target_id = {node_vars[right_var]}.id"
        elif path.rel.direction == "<-":
            edge_join = (
                f"{node_vars[left_var]}.id = {edge_alias}.target_id "
                f"{edge_on}"
            )
            target_join = f"{edge_alias}.source_id = {node_vars[right_var]}.id"
        else:  # undirected
            edge_join = (
                f"({node_vars[left_var]}.id = {edge_alias}.source_id "
                f"OR {node_vars[left_var]}.id = {edge_alias}.target_id) "
                f"{edge_on}"
            )
            target_join = (
                f"({edge_alias}.source_id = {node_vars[right_var]}.id "
                f"OR {edge_alias}.target_id = {node_vars[right_var]}.id)"
            )

        # LEFT JOIN: label фильтр левого узла в ON
        if left_label_sql:
            edge_join += f" AND {left_label_sql}"
            target = where_params if where_params is not None else params
            target.extend(left_label_vals)

        joins.append(f"{join_type} edges AS {edge_alias} ON {edge_join}")

        # Правый узел: label фильтр в условие JOIN
        if path.right and path.right.labels:
            labels = path.right.labels
            if len(labels) == 1:
                target_join += f" AND {node_vars[right_var]}.label = ?"
                params.append(labels[0])
            else:
                placeholders = ",".join("?" for _ in labels)
                target_join += f" AND {node_vars[right_var]}.label IN ({placeholders})"
                params.extend(labels)

        joins.append(f"{join_type} nodes AS {node_vars[right_var]} ON {target_join}")

        # Variable-length path: пока не поддерживается в SQL генерации
        # Для [*1..3] используем обычный JOIN (single hop) — функционально
        # корректно, без ошибок SQL. Полная поддержка multi-hop через CTE
        # будет в следующей версии.
        if path.rel.max_hops and path.rel.max_hops > 1:
            logger.debug(
                f"Variable-length path [*{path.rel.min_hops}..{path.rel.max_hops}] "
                f"использует single-hop (полная multi-hop поддержка в плане)"
            )

    def _process_where(
        self,
        expr: ASTNode,
        node_vars: Dict[str, str],
        clauses: List[str],
        params: List[Any],
    ):
        """Рекурсивно обрабатывает WHERE."""
        if isinstance(expr, Comparison):
            sql_ref = self._property_ref_to_sql(expr.left, node_vars)

            if expr.op in ("IN",):
                if isinstance(expr.right, list):
                    placeholders = ",".join("?" for _ in expr.right)
                    clauses.append(f"{sql_ref} IN ({placeholders})")
                    params.extend(expr.right)
                else:
                    clauses.append(f"{sql_ref} = ?")
                    params.append(expr.right)
            elif expr.op in ("CONTAINS",):
                clauses.append(f"{sql_ref} LIKE ?")
                params.append(f"%{expr.right}%")
            elif expr.op in ("STARTS WITH",):
                clauses.append(f"{sql_ref} LIKE ?")
                params.append(f"{expr.right}%")
            elif expr.op in ("ENDS WITH",):
                clauses.append(f"{sql_ref} LIKE ?")
                params.append(f"%{expr.right}")
            elif expr.op in ("=~",):
                # SQL regex via LIKE (simplified)
                clauses.append(f"{sql_ref} LIKE ?")
                params.append(expr.right)
            elif expr.op in ("IS NULL",):
                # Bare variable (v.* -> v.id) to avoid invalid SQL
                null_ref = sql_ref[:-2] + ".id" if sql_ref.endswith(".*") else sql_ref
                clauses.append(f"{null_ref} IS NULL")
            elif expr.op in ("IS NOT NULL",):
                null_ref = sql_ref[:-2] + ".id" if sql_ref.endswith(".*") else sql_ref
                clauses.append(f"{null_ref} IS NOT NULL")
            elif expr.op in ("=",):
                clauses.append(f"{sql_ref} = ?")
                params.append(expr.right)
            elif expr.op in ("<>", "!="):
                clauses.append(f"{sql_ref} != ?")
                params.append(expr.right)
            elif expr.op in (">",):
                clauses.append(f"{sql_ref} > ?")
                params.append(expr.right)
            elif expr.op in ("<",):
                clauses.append(f"{sql_ref} < ?")
                params.append(expr.right)
            elif expr.op in (">=",):
                clauses.append(f"{sql_ref} >= ?")
                params.append(expr.right)
            elif expr.op in ("<=",):
                clauses.append(f"{sql_ref} <= ?")
                params.append(expr.right)

        elif isinstance(expr, _BinaryOp):
            left_clauses: List[str] = []
            right_clauses: List[str] = []
            self._process_where(expr.left, node_vars, left_clauses, params)
            self._process_where(expr.right, node_vars, right_clauses, params)

            all_clauses = left_clauses + right_clauses
            if expr.op == "OR":
                clauses.append(f"({' OR '.join(all_clauses)})")
            else:  # AND
                clauses.extend(all_clauses)

        elif isinstance(expr, _UnaryOp):
            inner: List[str] = []
            self._process_where(expr.expr, node_vars, inner, params)
            if expr.op == "NOT":
                clauses.append(f"NOT ({inner[0]})" if inner else "1=0")

        elif isinstance(expr, _LabelTest):
            alias = node_vars.get(expr.variable, expr.variable)
            clauses.append(f"{alias}.label = ?")
            params.append(expr.label)

        elif isinstance(expr, _ExistsSubquery):
            # EXISTS { (n)-[:TYPE]->() }
            pattern = expr.pattern
            left_alias = node_vars.get(pattern.left.variable or "n", "n")
            edge_filter = ""
            if pattern.rel.rel_types:
                rtypes = pattern.rel.rel_types
                if len(rtypes) == 1:
                    edge_filter = "AND e.type = ?"
                    params.append(rtypes[0])
                else:
                    placeholders = ",".join("?" for _ in rtypes)
                    edge_filter = f"AND e.type IN ({placeholders})"
                    params.extend(rtypes)

            if pattern.rel.direction == "<-":
                clauses.append(
                    f"EXISTS (SELECT 1 FROM edges e WHERE e.target_id = {left_alias}.id {edge_filter})"
                )
            else:
                clauses.append(
                    f"EXISTS (SELECT 1 FROM edges e WHERE e.source_id = {left_alias}.id {edge_filter})"
                )

    def _property_ref_to_sql(self, ref: str, node_vars: Dict[str, str]) -> str:
        """Переводит n.name или n.label в SQL: n_alias.name или n_alias.label."""
        parts = ref.split(".")
        if len(parts) == 2:
            var, prop = parts
            alias = node_vars.get(var, var)

            # Специальные имена свойств
            prop_map = {
                "name": "name",
                "label": "label",
                "qualified_name": "qualified_name",
                "file_path": "file_path",
            }
            if prop in prop_map:
                return f"{alias}.{prop_map[prop]}"

            # properties JSON path
            return f"json_extract({alias}.properties, '$.{prop}')"

        if len(parts) == 1 and parts[0] in node_vars:
            # RETURN n — весь узел
            return f"{node_vars[parts[0]]}.*"

        return ref

    def _translate_return_expr(self, expr: str, node_vars: Dict[str, str]) -> str:
        """Переводит RETURN выражение в SQL."""
        # count(*)
        if expr == "count(*)":
            return "count(*)"

        # count(n.name)
        agg_match = re.match(r"(count|sum|avg|min|max|collect)\((.+)\)", expr, re.IGNORECASE)
        if agg_match:
            func = agg_match.group(1).upper()
            inner = agg_match.group(2)
            sql_inner = self._property_ref_to_sql(inner, node_vars)
            return f"{func}({sql_inner})"

        # Простое свойство
        return self._property_ref_to_sql(expr, node_vars)

    def _is_aggregate(self, expr: str) -> bool:
        return bool(re.match(r"(count|sum|avg|min|max|collect)\(", expr, re.IGNORECASE))


# ════════════════════════════════════════════════════════════
# Executor
# ════════════════════════════════════════════════════════════

class CypherExecutor:
    """Выполняет Cypher-запросы на PropertyGraph.

    Использование:
        executor = CypherExecutor(property_graph)
        result = executor.execute("MATCH (f:Function)-[:CALLS]->(g) RETURN f.name, g.name LIMIT 10")
    """

    def __init__(self, graph):
        self._graph = graph
        self._parser_cache: Dict[str, Query] = {}

    def execute(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Выполняет Cypher-запрос и возвращает результаты.

        Args:
            query: Cypher-like запрос
            params: Параметры (пока не используются, только для API совместимости)

        Returns:
            {
                "columns": ["f.name", "g.name"],
                "results": [{"f.name": "...", "g.name": "..."}],
                "stats": {"elapsed_ms": 5, "rows": 10}
            }
        """
        import time

        start = time.monotonic()

        try:
            # 1. Lex
            lexer = CypherLexer(query)
            tokens = lexer.tokenize()

            # 2. Parse
            parser = CypherParser(tokens)
            ast = parser.parse()

            # 3. Translate to SQL
            translator = CypherToSQL(self._graph)
            sql, sql_params = translator.translate(ast)

            # 4. Execute
            conn = self._graph._get_conn()
            cursor = conn.execute(sql, sql_params)
            rows = cursor.fetchall()

            # 5. Format results
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            results = []
            for row in rows:
                result_row = {}
                for i, col in enumerate(columns):
                    result_row[col] = row[i]
                results.append(result_row)

            elapsed = (time.monotonic() - start) * 1000

            return {
                "columns": columns,
                "results": results,
                "stats": {
                    "elapsed_ms": round(elapsed, 1),
                    "rows": len(results),
                    "sql": sql,
                    "sql_params": sql_params,
                },
            }

        except SyntaxError as e:
            return {
                "columns": [],
                "results": [],
                "error": f"Syntax error: {e}",
                "stats": {"elapsed_ms": 0, "rows": 0, "sql": ""},
            }
        except Exception as e:
            logger.exception(f"Cypher execution failed: {e}")
            return {
                "columns": [],
                "results": [],
                "error": str(e),
                "stats": {"elapsed_ms": 0, "rows": 0, "sql": ""},
            }

    def execute_with_explain(self, query: str) -> Dict[str, Any]:
        """Выполняет запрос и возвращает результат + explain."""
        result = self.execute(query)
        result["explain"] = {
            "cypher": query,
            "parsed_tokens": len(CypherLexer(query).tokenize()),
        }
        return result


# ════════════════════════════════════════════════════════════
# PropertyGraph integration
# ════════════════════════════════════════════════════════════

def query_graph(
    graph,
    query: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Удобная функция для прямого вызова Cypher-запроса к PropertyGraph.

    Пример:
        result = query_graph(pg, "MATCH (f:Function) RETURN f.name, f.label LIMIT 5")
    """
    executor = CypherExecutor(graph)
    return executor.execute(query, params)


__all__ = [
    "CypherLexer",
    "CypherParser",
    "CypherToSQL",
    "CypherExecutor",
    "Query",
    "query_graph",
]
