"""Инструменты графа и связей: graph_query, get_related_files,
cross_repo_search, cross_project_deps.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.core.multi_project_searcher import MultiProjectSearcher, ProjectRegistry
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.graph_tools")


class CrossRepoSearchTool(MCPTool):
    """cross_repo_search — поиск по нескольким проектам с @-mention."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="cross_repo_search")
        self.multi_searcher = services.resolve(MultiProjectSearcher)

    @error_boundary("cross_repo_search", timeout_ms=15000)
    async def execute(self, query: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        return self.multi_searcher.search(query, limit=8)


class CrossProjectDepsTool(MCPTool):
    """cross_project_deps — анализ зависимостей между проектами."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="cross_project_deps")
        self.multi_searcher = services.resolve(MultiProjectSearcher)

    @error_boundary("cross_project_deps", timeout_ms=15000)
    async def execute(
        self,
        action: str = "graph",
        project_name: str = "",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        from src.core.cross_project_deps import CrossProjectDependencyGraph

        registry = getattr(self.multi_searcher, "registry", None)
        deps_graph = CrossProjectDependencyGraph(project_registry=registry)

        if action == "graph":
            graph = deps_graph.build_dependency_graph()
            return {
                "status": "ok",
                "action": "graph",
                "graph": deps_graph.format_dependency_graph(graph),
            }

        elif action == "deps":
            if not project_name:
                return {"status": "error", "message": "project_name required for deps"}
            direction = (kwargs or {}).get("direction", "both")
            deps = deps_graph.get_project_dependencies(
                project_name, direction=direction
            )
            return {
                "status": "ok",
                "action": "deps",
                "project": project_name,
                "dependencies": deps_graph.format_project_deps(deps),
            }

        elif action == "cycles":
            cycles = deps_graph.find_circular_dependencies()
            return {
                "status": "ok",
                "action": "cycles",
                "has_cycles": bool(cycles),
                "cycles": cycles,
            }

        elif action == "shared":
            shared = deps_graph.find_shared_interfaces()
            return {
                "status": "ok",
                "action": "shared",
                "shared_interfaces": shared[:10] if shared else [],
            }

        elif action == "impact":
            if not project_name:
                return {
                    "status": "error",
                    "message": "project_name required for impact",
                }
            impact = deps_graph.analyze_impact(project_name)
            return {
                "status": "ok",
                "action": "impact",
                "project": project_name,
                "risk_level": impact.get("risk_level", "unknown"),
                "directly_affected": impact.get("directly_affected", []),
                "transitively_affected": impact.get("transitively_affected", []),
            }

        elif action == "path":
            extra = kwargs or {}
            from_proj = extra.get("from_project", "")
            to_proj = extra.get("to_project", "")
            if not from_proj or not to_proj:
                return {
                    "status": "error",
                    "message": "from_project and to_project required",
                }
            path = deps_graph.get_dependency_path(from_proj, to_proj)
            return {
                "status": "ok",
                "action": "path",
                "path": path if path else None,
            }

        return {"status": "error", "message": f"Unknown action: {action}"}


class GraphQueryTool(MCPTool):
    """graph_query — запрос к графу знаний (GraphRAG).

    Multi-window (INC-6BCB-v2): НЕ кэшируем symbol_index в __init__ —
    Indexer (и его _symbol_index) теперь per-project через registry.
    Резолвим per-call через resolve_symbol_index() / resolve_indexer().
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="graph_query")

    @error_boundary("graph_query", timeout_ms=15000)
    async def execute(
        self, query_type: str, target: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        from src.core.graph_rag import GraphRAGQueryEngine

        # Multi-window: per-project indexer → per-project symbol_index.
        indexer = self.resolve_indexer()
        engine = GraphRAGQueryEngine(
            indexer.project_path,
            symbol_index=self.resolve_symbol_index(),
        )

        if query_type == "impact":
            result = engine.query_impact(target)
            return {
                "status": "ok",
                "query_type": "impact",
                "target": target,
                "risk_score": result.get("risk_score", 0),
                "direct_impact": result.get("direct_impact", [])[:10],
                "tests_to_run": result.get("tests_to_run", []),
            }

        elif query_type == "feature":
            result = engine.query_feature(target)
            # SymbolRef → dict для JSON-сериализации
            symbols_raw = result.get("symbols", [])
            symbols_dicts = []
            for s in symbols_raw:
                if hasattr(s, "to_dict"):
                    symbols_dicts.append(s.to_dict())
                elif isinstance(s, dict):
                    symbols_dicts.append(s)
                else:
                    symbols_dicts.append(str(s))
            return {
                "status": "ok",
                "query_type": "feature",
                "target": target,
                "files": result.get("files", []),
                "symbols": symbols_dicts,
            }

        elif query_type == "deps":
            result = engine.query_dependencies(target)
            return {
                "status": "ok",
                "query_type": "deps",
                "target": target,
                "depends_on": result.get("depends_on", []),
                "depended_by": result.get("depended_by", []),
            }

        elif query_type == "tests":
            tests = engine.query_tests(target)
            return {
                "status": "ok",
                "query_type": "tests",
                "target": target,
                "tests": tests or [],
            }

        return {"status": "error", "message": f"Unknown query_type: {query_type}"}


class CypherQueryTool(MCPTool):
    """query_graph — Cypher-like запрос к PropertyGraph знаний.

    Позволяет выполнять графовые запросы в стиле openCypher:

        MATCH (f:Function)-[:CALLS]->(g:Function)
        WHERE f.file_path STARTS WITH "src"
        RETURN f.name, g.name, count(*) AS calls
        ORDER BY calls DESC
        LIMIT 10

    Поддерживаемые конструкции:
      - MATCH (n:Label), (n)-[:TYPE]->(m), (n)-[:TYPE*1..3]->(m)
      - WHERE: =, <>, CONTAINS, STARTS WITH, IN, IS NULL, AND/OR, EXISTS
      - RETURN: n.name, count(*) AS alias, DISTINCT, ORDER BY, LIMIT, SKIP
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="query_graph")

    @error_boundary("query_graph", timeout_ms=15000)
    async def execute(self, query: str, limit: int = 50) -> dict:
        from src.core.cypher_engine import CypherExecutor
        from src.core.graph import PropertyGraph

        try:
            pg = self.services.resolve(PropertyGraph)
        except KeyError:
            # Fallback: per-project PropertyGraph через indexer
            indexer = self.resolve_indexer()
            project_path = indexer.project_path
            db_path = project_path / ".codebase" / "graph.db"
            pg = PropertyGraph(db_path)

        executor = CypherExecutor(pg)

        # Лимит на результаты для безопасности
        if limit and limit < 200:
            query = query.strip()
            if "LIMIT" not in query.upper():
                query += f" LIMIT {limit}"

        result = executor.execute(query)

        error = result.get("error")
        if error:
            return {
                "status": "error",
                "message": error,
                "query": query,
            }

        # Пост-обработка: добавляем condition_path как читаемую строку
        # для ASSIGNED_FROM рёбер, чтобы LLM сразу видела контекст.
        rows = result.get("results", [])
        for row in rows:
            if isinstance(row, dict):
                for key, val in row.items():
                    if isinstance(val, str) and val.startswith("[") and "condition" not in key:
                        continue  # не трогаем уже форматированные строки
                    # Если есть properties с condition_path — выводим как строку
                    if key.endswith("_properties") or key == "properties":
                        if isinstance(val, dict) and "condition_path" in val:
                            cp = val["condition_path"]
                            row[key + "_flow"] = " → ".join(cp) if cp else "unconditional"

        return {
            "status": "ok",
            "query": query,
            "columns": result.get("columns", []),
            "results": rows,
            "stats": result.get("stats", {}),
        }


class GetRelatedFilesTool(MCPTool):
    """get_related_files — файлы связанные с данным через Knowledge Graph."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_related_files")

    @error_boundary("get_related_files", timeout_ms=15000)
    async def execute(
        self,
        project_root: str,
        file_path: str,
        max_depth: int = 1,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        from src.core.commit_memory import CommitMemory
        from src.core.relation_extractor import RelationExtractor

        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return {
                "status": "error",
                "message": f"Path does not exist: {project_root}",
            }

        memory = CommitMemory(target_path)
        extractor = RelationExtractor(memory)

        extractor.extract_all_relations()
        related = extractor.get_related_files(file_path, max_depth=max_depth)
        summary = extractor.get_relation_summary()

        if not related:
            return {
                "status": "ok",
                "file": file_path,
                "related_files": [],
                "relation_summary": summary,
            }

        items = []
        for rel in related[:15]:
            items.append(
                {
                    "file": rel["file"],
                    "depth": rel["depth"],
                    "weight": round(rel.get("total_weight", 0), 2),
                    "path": " → ".join(rel.get("path", [])),
                }
            )

        return {
            "status": "ok",
            "file": file_path,
            "search_depth": max_depth,
            "total_relations": len(related),
            "related_files": items,
            "relation_summary": summary,
        }


__all__ = [
    "CrossRepoSearchTool",
    "CrossProjectDepsTool",
    "GraphQueryTool",
    "GetRelatedFilesTool",
]
