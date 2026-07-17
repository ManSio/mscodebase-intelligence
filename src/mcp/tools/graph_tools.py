"""Инструменты графа и связей: graph_query, get_related_files,
cross_repo_search, cross_project_deps.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.core.indexing.project_indexer_registry import ProjectIndexerRegistry
from src.core.multi_project_searcher import MultiProjectSearcher
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
        from src.core.search.cross_project_deps import CrossProjectDependencyGraph

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
    """graph_query — единый мультиплексированный инструмент для всех графовых запросов.

    Заменяет собой 4 отдельных тула: graph_query, cypher_query,
    get_related_files, get_variable_flow (Фаза 2).

    Multi-window (INC-6BCB-v2): НЕ кэшируем symbol_index в __init__ —
    Indexer (и его _symbol_index) теперь per-project через registry.
    Резолвим per-call через resolve_symbol_index() / resolve_indexer().

    Параметр `action` выбирает тип запроса:
    - "query" — GraphRAG (query_type=impact|feature|deps|tests), target=symbol
    - "cypher" — Cypher-like запрос к PropertyGraph
    - "related" — связанные файлы через CommitMemory
    - "flow" — трассировка переменной (data flow)
    - "drift" — Architecture Drift Detector
    - "verify" — Claim Verifier (проверка утверждений против кода)
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="graph_query")

    @error_boundary("graph_query", timeout_ms=15000)
    async def execute(
        self,
        action: str = "query",
        query_type: str = "",
        target: str = "",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        if action == "cypher":
            return await self._execute_cypher(target, kwargs)
        elif action == "related":
            return await self._execute_related(target, kwargs)
        elif action == "flow":
            return await self._execute_flow(target, kwargs)
        elif action == "drift":
            return await self._execute_arch_drift(target)
        elif action == "verify":
            return await self._execute_verify(target, kwargs)
        else:
            # По умолчанию — GraphRAG (action="query")
            return await self._execute_query(query_type or "impact", target, kwargs)

    async def _execute_query(
        self, query_type: str, target: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        """GraphRAG: impact/feature/deps/tests запросы к графу знаний."""
        from src.core.graph_rag import GraphRAGQueryEngine

        indexer = self.resolve_indexer()
        engine = GraphRAGQueryEngine(
            indexer.project_path,
            symbol_index=self.resolve_symbol_index(),
        )

        if query_type == "impact":
            result = engine.query_impact(target)
            return {
                "status": "ok",
                "action": "query",
                "query_type": "impact",
                "target": target,
                "risk_score": result.get("risk_score", 0),
                "direct_impact": result.get("direct_impact", [])[:10],
                "tests_to_run": result.get("tests_to_run", []),
            }

        elif query_type == "feature":
            result = engine.query_feature(target)
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
                "action": "query",
                "query_type": "feature",
                "target": target,
                "files": result.get("files", []),
                "symbols": symbols_dicts,
            }

        elif query_type == "deps":
            result = engine.query_dependencies(target)
            return {
                "status": "ok",
                "action": "query",
                "query_type": "deps",
                "target": target,
                "depends_on": result.get("depends_on", []),
                "depended_by": result.get("depended_by", []),
            }

        elif query_type == "tests":
            tests = engine.query_tests(target)
            return {
                "status": "ok",
                "action": "query",
                "query_type": "tests",
                "target": target,
                "tests": tests or [],
            }

        return {"status": "error", "action": "query", "message": f"Unknown query_type: {query_type}"}

    async def _execute_cypher(
        self, query: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        """Cypher-like запрос к PropertyGraph."""
        from src.core.cypher_engine import CypherExecutor
        from src.core.graph import PropertyGraph

        limit = (kwargs or {}).get("limit", 50)
        if not query:
            return {"status": "error", "action": "cypher", "message": "query is required"}

        _kwargs = kwargs or {}
        try:
            pg = self._services.resolve(PropertyGraph)
        except KeyError:
            indexer = self.resolve_indexer()
            project_path = indexer.project_path
            db_path = project_path / ".codebase" / "graph.db"
            pg = PropertyGraph(db_path)

        executor = CypherExecutor(pg)

        q = query.strip()
        if limit and limit < 200 and "LIMIT" not in q.upper():
            q += f" LIMIT {limit}"

        result = executor.execute(q)
        error = result.get("error")
        if error:
            return {"status": "error", "action": "cypher", "message": error, "query": query}

        rows = result.get("results", [])
        for row in rows:
            if isinstance(row, dict):
                for key, val in row.items():
                    if key.endswith("_properties") or key == "properties":
                        if isinstance(val, dict) and "condition_path" in val:
                            cp = val["condition_path"]
                            row[key + "_flow"] = " → ".join(cp) if cp else "unconditional"

        return {
            "status": "ok",
            "action": "cypher",
            "query": query,
            "columns": result.get("columns", []),
            "results": rows,
            "stats": result.get("stats", {}),
        }

    async def _execute_related(
        self, file_path: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        """Связанные файлы через CommitMemory + RelationExtractor."""
        from src.core.commit_memory import CommitMemory
        from src.core.relation_extractor import RelationExtractor

        _kwargs = kwargs or {}
        project_root = _kwargs.get("project_root", "")
        max_depth = _kwargs.get("max_depth", 1)

        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return {
                "status": "error",
                "action": "related",
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
                "action": "related",
                "file": file_path,
                "related_files": [],
                "relation_summary": summary,
            }

        items = []
        for rel in related[:15]:
            items.append({
                "file": rel["file"],
                "depth": rel["depth"],
                "weight": round(rel.get("total_weight", 0), 2),
                "path": " → ".join(rel.get("path", [])),
            })

        return {
            "status": "ok",
            "action": "related",
            "file": file_path,
            "search_depth": max_depth,
            "total_relations": len(related),
            "related_files": items,
            "relation_summary": summary,
        }

    async def _execute_flow(
        self, name: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        """Трассировка потока данных переменной (ASSIGNED_FROM)."""
        from src.core.graph import PropertyGraph
        from src.core.search.graph_adapter import SymbolIndexAdapter

        _kwargs = kwargs or {}
        scope_id = _kwargs.get("scope_id")
        file_path = _kwargs.get("file_path")
        max_depth = _kwargs.get("max_depth", 3)

        if not name:
            return {"status": "error", "action": "flow", "message": "name is required"}

        try:
            pg = self._services.resolve(PropertyGraph)
            adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
        except KeyError:
            indexer = self.resolve_indexer()
            pg = getattr(indexer, "_graph", None) or getattr(indexer, "property_graph", None)
            if not pg:
                return {
                    "status": "error",
                    "action": "flow",
                    "message": "PropertyGraph not available. Run reindex first.",
                }
            adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)

        variables = adapter.find_variables(name=name, scope_id=scope_id, limit=20)
        if not variables:
            return {
                "status": "ok",
                "action": "flow",
                "variable": None,
                "message": f"No variable '{name}' found.",
            }

        if not scope_id:
            files = set(v["file_path"] for v in variables)
            scopes = [
                {
                    "scope_id": v["function_scope"],
                    "file": v["file_path"],
                    "function": v["function"],
                    "line": v["line"],
                }
                for v in variables
                if v["function_scope"]
            ]
            return {
                "status": "ok",
                "action": "flow",
                "variable": {
                    "name": name,
                    "found": len(variables),
                    "files": sorted(files),
                    "scopes": scopes,
                    "conflict": len(variables) > 1,
                },
                "message": (
                    f"Found {len(variables)} variable(s) named '{name}'. "
                    f"{'Multiple scopes detected! ' if len(variables) > 1 else ''}"
                    f"Use scope_id for precise data flow."
                ),
            }

        if scope_id:
            variables = [v for v in variables if v["function_scope"] == scope_id]

        if not variables:
            return {
                "status": "ok",
                "action": "flow",
                "variable": None,
                "message": f"Variable '{name}' with scope_id '{scope_id}' not found.",
            }

        flow = adapter.get_variable_flow(
            variable_name=name, scope_id=scope_id,
            file_path=file_path, max_depth=max_depth,
        )

        return {
            "status": "ok",
            "action": "flow",
            "variable": flow["variable"],
            "incoming": flow["incoming"],
            "outgoing": flow["outgoing"],
            "chain": flow["chain"],
            "summary": {
                "name": name,
                "scope_id": scope_id,
                "incoming_count": len(flow["incoming"]),
                "outgoing_count": len(flow["outgoing"]),
                "chain_length": len(flow["chain"]),
                "conditional_edges": sum(
                    1 for e in flow["chain"] if e.get("condition_path")
                ),
            },
        }

    async def _execute_arch_drift(self, file_path: str = "") -> dict:
        """Architecture Drift Detector: ищет структурные аномалии импортов.

        Анализирует PropertyGraph на паттерны, которые указывают
        на дрейф архитектуры:

        1. **Chain imports** (A->B->C, но A мог бы ->C напрямую):
           Признак shim/re-export прослойки.
        2. **Circular imports** (A->B->A):
           Циклические зависимости между модулями.
        3. **Hub modules**:
           Модули, которые импортируют всё подряд (признак god-object).

        Returns:
            dict с найденными аномалиями.
        """
        import sqlite3
        from pathlib import Path

        # Находим PropertyGraph (через indexer или напрямую)
        db_path = None
        try:
            indexer = self.resolve_indexer()
            pg = getattr(indexer, "_graph", None) or getattr(indexer, "property_graph", None)
            if pg:
                db_path = pg._db_path if hasattr(pg, '_db_path') else getattr(pg, 'path', None)
        except Exception:
            pass

        # Fallback: прямой путь к PropertyGraph
        if not db_path:
            from pathlib import Path
            try:
                registry = self._services.resolve(ProjectIndexerRegistry)
                roots = registry.active_project_paths() if hasattr(registry, 'active_project_paths') else []
                for r in roots:
                    candidate = Path(r) / ".codebase" / "graph.db"
                    if candidate.exists():
                        db_path = str(candidate)
                        break
            except Exception:
                pass
        if not db_path:
            candidate = Path("D:/Project/MSCodeBase/.codebase/graph.db")
            if candidate.exists():
                db_path = str(candidate)

        if not db_path or not Path(str(db_path)).exists():
            return {
                "status": "error",
                "action": "drift",
                "message": "PropertyGraph not available. Run reindex first.",
            }

        conn = sqlite3.connect(str(db_path))
        result = {
            "status": "ok",
            "action": "drift",
            "anomalies": {},
        }

        # 1. Chain imports (A->B->C, no direct A->C)
        chain = conn.execute("""
            SELECT a.name, b.name, c.name
            FROM edges e1
            JOIN edges e2 ON e1.target_id = e2.source_id AND e2.type = 'IMPORTS'
            JOIN nodes a ON e1.source_id = a.id
            JOIN nodes b ON e1.target_id = b.id
            JOIN nodes c ON e2.target_id = c.id
            WHERE e1.type = 'IMPORTS'
              AND a.name <> c.name
              AND NOT EXISTS (
                SELECT 1 FROM edges e3
                WHERE e3.source_id = a.id AND e3.target_id = c.id
                  AND e3.type = 'IMPORTS'
              )
            ORDER BY a.name
            LIMIT 30
        """).fetchall()

        result["anomalies"]["chain_imports"] = {
            "count": len(chain),
            "description": "A->B->C chain where A could import C directly. Possible shim/re-export.",
            "patterns": [
                {"from": r[0], "via": r[1], "to": r[2]}
                for r in chain[:20]
            ],
        }

        # 2. Hub modules (modules that import many others)
        hub = conn.execute("""
            SELECT n.name, COUNT(*) as import_count
            FROM edges e
            JOIN nodes n ON e.source_id = n.id
            WHERE e.type = 'IMPORTS'
            GROUP BY n.id
            HAVING import_count > 10
            ORDER BY import_count DESC
            LIMIT 10
        """).fetchall()

        result["anomalies"]["hub_modules"] = {
            "count": len(hub),
            "description": "Modules with >10 imports. May indicate god-object or poor modularization.",
            "hubs": [{"module": r[0], "imports": r[1]} for r in hub],
        }

        # 3. Circular imports (A->B->A)
        circular = conn.execute("""
            SELECT DISTINCT a.name, b.name
            FROM edges e1
            JOIN edges e2 ON e1.source_id = e2.target_id
              AND e1.target_id = e2.source_id
            JOIN nodes a ON e1.source_id = a.id
            JOIN nodes b ON e1.target_id = b.id
            WHERE e1.type = 'IMPORTS' AND e2.type = 'IMPORTS'
              AND a.name < b.name
            LIMIT 20
        """).fetchall()

        result["anomalies"]["circular_imports"] = {
            "count": len(circular),
            "description": "Mutual imports between modules. Can cause initialization issues.",
            "cycles": [{"a": r[0], "b": r[1]} for r in circular],
        }

        conn.close()
        return result

    # ── Claim Verifier ─────────────────────────────────────

    async def _execute_verify(
        self, claim: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        """Проверяет утверждение AI-агента против SymbolIndex + PropertyGraph.

        Args:
            claim: JSON-строка с полями:
                - subject (str): имя символа
                - predicate (str): calls|defined_in|imports|handles_error|defines|implements|inherits
                - object (str): цель
                - file (str, optional): файл для сужения

        Returns:
            dict с вердиктом: confirmed / contradicted / unverifiable
        """
        import json

        # Парсим claim (строка или dict)
        if isinstance(claim, str):
            try:
                claim_dict = json.loads(claim)
            except json.JSONDecodeError:
                return {"status": "error", "message": "claim must be valid JSON"}
        elif isinstance(claim, dict):
            claim_dict = claim
        else:
            return {"status": "error", "message": "claim must be a string or dict"}

        subject = claim_dict.get("subject", "").strip()
        predicate = claim_dict.get("predicate", "").strip()
        obj = claim_dict.get("object", "").strip()
        if not subject:
            return {"status": "error", "message": "claim.subject is required"}

        SUPPORTED = {"calls", "defined_in", "imports", "handles_error", "defines", "implements", "inherits"}
        if predicate not in SUPPORTED:
            return {"status": "error", "message": f"Unsupported predicate '{predicate}'. Supported: {sorted(SUPPORTED)}"}

        # Get PropertyGraph
        pg = None
        db_path = None
        try:
            indexer = self.resolve_indexer()
            pg = getattr(indexer, "_graph", None) or getattr(indexer, "property_graph", None)
            if pg:
                db_path = pg._db_path if hasattr(pg, '_db_path') else getattr(pg, 'path', None)
        except Exception:
            pass
        if not db_path:
            from pathlib import Path
            try:
                registry = self._services.resolve(ProjectIndexerRegistry)
                roots = registry.active_project_paths() if hasattr(registry, 'active_project_paths') else []
                for r in roots:
                    candidate = Path(r) / ".codebase" / "graph.db"
                    if candidate.exists():
                        db_path = str(candidate)
                        break
            except Exception:
                pass
        if not db_path:
            candidate = Path("D:/Project/MSCodeBase/.codebase/graph.db")
            if candidate.exists():
                db_path = str(candidate)

        if not db_path or not Path(str(db_path)).exists():
            return _unverifiable("PropertyGraph not available", predicate)

        from src.core.graph import EdgeType, NodeLabel, PropertyGraph
        from src.core.search.graph_adapter import SymbolIndexAdapter

        pg = PropertyGraph(db_path)
        adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)

        # Dispatch
        if predicate == "calls":
            return await self._v_calls(pg, adapter, subject, obj)
        elif predicate == "defined_in":
            return await self._v_defined_in(pg, adapter, subject, obj)
        elif predicate == "imports":
            return await self._v_imports(pg, subject, obj)
        elif predicate == "handles_error":
            return await self._v_error_handling(pg, subject)
        elif predicate == "defines":
            return await self._v_defines(pg, subject, obj)
        elif predicate in ("implements", "inherits"):
            return await self._v_relationship(pg, subject, obj, predicate)

        return {"status": "error", "message": f"Unhandled predicate: {predicate}"}

    async def _v_calls(self, pg, adapter, subject: str, obj: str) -> dict:
        nodes = pg.find_nodes(name_pattern=subject, limit=5)
        if not nodes:
            return _unverifiable(f"Symbol '{subject}' not found", "calls")
        evidence = []
        for node in nodes[:3]:
            for neighbor, edge, _ in pg.get_neighbors(
                node.qualified_name, edge_type=EdgeType.CALLS, direction="outgoing", max_depth=1,
            ):
                if not obj or obj.lower() in neighbor.name.lower():
                    evidence.append({
                        "file": neighbor.file_path or edge.properties.get("file", "?"),
                        "line": edge.properties.get("line", 0),
                        "detail": f"{node.name} -> {neighbor.name}",
                    })
        if evidence:
            return _confirmed(f"{subject} calls {obj}" if obj else f"{subject} calls", evidence, "calls")
        # Show what it actually calls
        callees = []
        for node in nodes[:1]:
            for neighbor, edge, _ in pg.get_neighbors(
                node.qualified_name, edge_type=EdgeType.CALLS, direction="outgoing", max_depth=1,
            ):
                callees.append(neighbor.name)
        if callees:
            return _contradicted(f"{subject} does NOT call {obj}. Actually calls: {callees[:10]}", [{"detail": f"Callees: {', '.join(callees[:10])}"}], "calls")
        return _unverifiable(f"No call info for '{subject}'", "calls")

    async def _v_defined_in(self, pg, adapter, subject: str, obj: str) -> dict:
        nodes = pg.find_nodes(name_pattern=subject, limit=10)
        # Skip placeholder nodes (empty file_path = __extern__)
        real_nodes = [n for n in nodes if n.file_path]
        if real_nodes:
            node = real_nodes[0]
            fp = node.file_path
            match = obj and obj in fp
            return _confirmed(
                f"{subject} defined in {fp}" + ("" if not obj else " " + ("" if match else f"(not {obj})")),
                [{"file": fp, "line": node.properties.get("line", 0)}],
                "defined_in",
            )
        if nodes:
            # All nodes are placeholders or externals
            return _unverifiable(f"'{subject}' exists but no file location found (maybe external/placeholder)", "defined_in")
        # Fallback: SymbolIndex
        try:
            si = self.resolve_symbol_index()
            defs = si.find_definitions(subject) or []
            if defs:
                files = list(set(d.file_path for d in defs))
                if obj and any(obj in f for f in files):
                    return _confirmed(f"{subject} defined in {files[0]}", [{"file": files[0], "line": defs[0].line}], "defined_in")
                return _confirmed(f"{subject} defined in: {', '.join(files[:3])}", [{"file": f} for f in files[:3]], "defined_in")
        except Exception:
            pass
        return _unverifiable(f"Symbol '{subject}' not found", "defined_in")

    async def _v_imports(self, pg, subject: str, obj: str) -> dict:
        nodes = pg.find_nodes(name_pattern=subject, limit=5)
        file_nodes = [n for n in nodes if n.label == NodeLabel.FILE]
        if not file_nodes:
            return _unverifiable(f"File matching '{subject}' not found", "imports")
        for fn in file_nodes[:2]:
            for neighbor, edge, _ in pg.get_neighbors(
                fn.qualified_name, edge_type=EdgeType.IMPORTS, direction="outgoing", max_depth=1,
            ):
                if not obj or obj.lower() in neighbor.name.lower():
                    return _confirmed(f"{fn.name} imports {neighbor.name}", [{"file": fn.file_path or fn.name, "line": edge.properties.get("line", 0), "detail": f"import {neighbor.name}"}], "imports")
        return _contradicted(f"{subject} does NOT import {obj}" if obj else f"{subject} has no matching imports", [], "imports")

    async def _v_error_handling(self, pg, subject: str) -> dict:
        nodes = pg.find_nodes(name_pattern=subject, limit=5)
        if not nodes:
            return _unverifiable(f"Symbol '{subject}' not found", "handles_error")
        node = nodes[0]
        fp = node.file_path
        if not fp:
            return _unverifiable(f"No file for '{subject}'", "handles_error")
        full_path = Path("D:/Project/MSCodeBase") / fp
        if not full_path.exists():
            return _unverifiable(f"File not found: {fp}", "handles_error")
        try:
            lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
            start = node.properties.get("line", 0)
            func_text = "\n".join(lines[start:start + 50])
            if "try" in func_text and ("except" in func_text or "finally" in func_text):
                evidence = []
                for i, line in enumerate(lines[start:start + 50], start):
                    if "try" in line or "except" in line or "finally" in line:
                        evidence.append({"line": i, "detail": line.strip()[:80]})
                return _confirmed(f"{subject} handles errors ({len(evidence)} try/except blocks)", evidence[:5], "handles_error")
            return _contradicted(f"No try/except found in {subject}", [{"detail": f"Scanned lines {start}-{start + 50} of {fp}"}], "handles_error")
        except Exception as e:
            return _unverifiable(f"Error reading file: {e}", "handles_error")

    async def _v_defines(self, pg, subject: str, obj: str) -> dict:
        subject_nodes = pg.find_nodes(name_pattern=subject, limit=5)
        if not subject_nodes:
            return _unverifiable(f"'{subject}' not found", "defines")
        sn = subject_nodes[0]
        for neighbor, edge, _ in pg.get_neighbors(
            sn.qualified_name, edge_type=EdgeType.DEFINES, direction="outgoing", max_depth=1,
        ):
            if not obj or obj.lower() in neighbor.name.lower():
                return _confirmed(f"{subject} defines {neighbor.name}", [{"file": neighbor.file_path or sn.file_path, "line": edge.properties.get("line", 0), "detail": f"defines {neighbor.name} ({neighbor.label})"}], "defines")
        return _contradicted(f"'{subject}' does NOT define '{obj}'" if obj else f"'{subject}' has no DEFINES edges", [], "defines")

    async def _v_relationship(self, pg, subject: str, obj: str, rel_type: str) -> dict:
        edge_type = EdgeType.IMPLEMENTS if rel_type == "implements" else EdgeType.INHERITS
        subject_nodes = pg.find_nodes(name_pattern=subject, limit=5)
        if not subject_nodes:
            return _unverifiable(f"'{subject}' not found", rel_type)
        sn = subject_nodes[0]
        for neighbor, edge, _ in pg.get_neighbors(
            sn.qualified_name, edge_type=edge_type, direction="outgoing", max_depth=1,
        ):
            if not obj or obj.lower() in neighbor.name.lower():
                return _confirmed(f"{subject} {rel_type} {neighbor.name}", [{"file": neighbor.file_path or sn.file_path, "line": edge.properties.get("line", 0)}], rel_type)
        return _contradicted(f"No {rel_type} relationship found for '{subject}'", [], rel_type)


# ── Helper factories (module-level) ──

def _confirmed(message: str, evidence: list, predicate: str) -> dict:
    return {"status": "ok", "verdict": "confirmed", "message": message, "evidence": evidence, "confidence": 0.9, "predicate": predicate}

def _contradicted(message: str, evidence: list, predicate: str) -> dict:
    return {"status": "ok", "verdict": "contradicted", "message": message, "evidence": evidence, "confidence": 0.85, "predicate": predicate}

def _unverifiable(message: str, predicate: str) -> dict:
    return {"status": "ok", "verdict": "unverifiable", "message": message, "evidence": [], "confidence": 0.3, "predicate": predicate}


__all__ = [
    "CrossRepoSearchTool",
    "CrossProjectDepsTool",
    "GraphQueryTool",
]
