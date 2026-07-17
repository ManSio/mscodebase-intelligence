"""Cypher query engine — компонент для подмножества openCypher.

Facade: реэкспортирует все публичные классы для обратной совместимости.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.core.search.cypher_ast import (  # noqa: F401
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
from src.core.search.cypher_executor import CypherExecutor  # noqa: F401
from src.core.search.cypher_lexer import (  # noqa: F401
    DIRECTION_LEFT,
    DIRECTION_NONE,
    DIRECTION_RIGHT,
    KEYWORDS,
    CypherLexer,
    Token,
    TokenType,
)
from src.core.search.cypher_parser import CypherParser  # noqa: F401
from src.core.search.cypher_sql import CypherToSQL  # noqa: F401

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
    "CypherLexer", "Token", "TokenType", "KEYWORDS",
    "DIRECTION_LEFT", "DIRECTION_RIGHT", "DIRECTION_NONE",
    "ASTNode", "NodePattern", "RelPattern", "PathPattern", "MatchClause",
    "Comparison", "WhereClause", "ReturnItem", "OrderItem", "Query",
    "_BinaryOp", "_UnaryOp", "_LabelTest", "_ExistsSubquery",
    "CypherParser", "CypherToSQL", "CypherExecutor",
    "query_graph",
]
