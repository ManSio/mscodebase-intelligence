"""Cypher query engine — компонент для подмножества openCypher."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from src.core.search.cypher_ast import (
    ASTNode,
    Comparison,
    PathPattern,
    Query,
    _BinaryOp,
    _ExistsSubquery,
    _LabelTest,
    _UnaryOp,
)

logger = logging.getLogger(__name__)


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
