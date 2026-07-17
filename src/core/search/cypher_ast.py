"""Cypher query engine — компонент для подмножества openCypher."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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



# ─── Internal AST helpers для WHERE ─────────────────────────

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
    def __init__(self, pattern):
        self.pattern = pattern


# ════════════════════════════════════════════════════════════
# SQL Generator
# ════════════════════════════════════════════════════════════
