"""Schema-валидация Cypher AST против канонической схемы PropertyGraph.

Слой между парсером и SQL-генератором. Архитектурно закрывает паттерн P-004
(«разрыв валидации между слоями»): запрос принят лексером/парсером, но
исполнен SQL неверно и тихо — без понятной ошибки.

Что валидирует (сверх уже сделанных C1-C4):
- неизвестный label в обязательном MATCH или WHERE-`n:Label` → понятная ошибка
  вместо тихого `[]` (классическая галлюцинация LLM: `MATCH (f:SERVICE)`).
- неизвестный rel type в обязательном MATCH → ошибка вместо тихого `[]`.
- свойства узла в паттерне `{prop: value}` — на текущий момент парсер на них
  падает (SyntaxError «Expected :»), до SQL не доходят; schema-проверка —
  defensive-слой: если парсер когда-нибудь начнёт принимать их, а SQL-генератор
  по-прежнему игнорирует (тихий неверный результат), schema даст явную ошибку.

Источник правды — NodeLabel/EdgeType из graph.py (single source of truth),
НЕ хардкоженный набор. OPTIONAL MATCH намеренно пропускается: NULL-семантика
легитимна (`OPTIONAL MATCH (g)-[:NONEXISTENT]->(x)` — корректный NULL,
задокументировано тестами test_cypher_engine.py).
"""
from __future__ import annotations

from typing import List, Optional, Set

from src.core.graph import EdgeType, NodeLabel
from src.core.search.cypher_ast import (
    MatchClause,
    NodePattern,
    Query,
    WhereClause,
    _BinaryOp,
    _LabelTest,
    _UnaryOp,
)

# ────────────────────────────────────────────────────────────
# Каноническая схема (из graph.py — единственный источник правды)
# ────────────────────────────────────────────────────────────

KNOWN_LABELS: Set[str] = {
    v for k, v in vars(NodeLabel).items()
    if isinstance(v, str) and not k.startswith("__")
}
KNOWN_REL_TYPES: Set[str] = {
    v for k, v in vars(EdgeType).items()
    if isinstance(v, str) and not k.startswith("__")
}

# Валидируем case-insensitively (cypher_sql генерирует COLLATE NOCASE —
# lowercase-метки легитимны, см. C1). Хранение в upper() без коллизий:
# все канонические имена ASCII (Function, Method, CALLS, ...).
_KNOWN_LABELS_UPPER: Set[str] = {l.upper() for l in KNOWN_LABELS}
_KNOWN_REL_TYPES_UPPER: Set[str] = {r.upper() for r in KNOWN_REL_TYPES}


# ────────────────────────────────────────────────────────────
# Валидация
# ────────────────────────────────────────────────────────────

def _check_node_pattern(node: NodePattern) -> Optional[str]:
    """Проверяет метки и свойства одного узла паттерна."""
    for label in node.labels:
        if label.upper() not in _KNOWN_LABELS_UPPER:
            return f"schema: unknown label :{label} (known: {', '.join(sorted(KNOWN_LABELS))})"
    if node.properties:
        keys = ", ".join(sorted(node.properties))
        return (
            f"schema: node pattern properties {{{keys}}} are not supported; "
            f"move the filter to WHERE, e.g. WHERE n.{next(iter(node.properties))} = ..."
        )
    return None


def _check_match_clause(mc: MatchClause) -> Optional[str]:
    """Проверяет паттерны обязательного MATCH (метки, свойства, rel types)."""
    for path in mc.paths:
        for node in (path.left, path.right):
            if node is None:
                continue
            err = _check_node_pattern(node)
            if err:
                return err
        for rtype in path.rel.rel_types:
            if rtype.upper() not in _KNOWN_REL_TYPES_UPPER:
                return (
                    f"schema: unknown rel type :{rtype} in MATCH "
                    f"(known: {', '.join(sorted(KNOWN_REL_TYPES))})"
                )
    return None


def _iter_where_labels(expr, found: List[str]) -> None:
    """Собирает label-имена из label-тестов в WHERE (n:Label)."""
    if isinstance(expr, _LabelTest):
        found.append(expr.label)
    elif isinstance(expr, (_BinaryOp, _UnaryOp)):
        if isinstance(expr, _UnaryOp):
            _iter_where_labels(expr.expr, found)
        else:
            _iter_where_labels(expr.left, found)
            _iter_where_labels(expr.right, found)


def schema_check(query: Query) -> Optional[str]:
    """Возвращает текст ошибки schema-валидации или None.

    Строго: обязательный MATCH (метки, rel types, свойства) и WHERE-label-tests.
    Пропускается: OPTIONAL MATCH (NULL-семантика легитимна).
    """
    if query.match is not None:
        err = _check_match_clause(query.match)
        if err:
            return err

    if query.where is not None:
        labels: List[str] = []
        _iter_where_labels(query.where.expr, labels)
        for label in labels:
            if label.upper() not in _KNOWN_LABELS_UPPER:
                return f"schema: unknown label :{label} in WHERE (known: {', '.join(sorted(KNOWN_LABELS))})"

    return None
