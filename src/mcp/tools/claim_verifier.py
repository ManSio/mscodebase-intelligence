"""
Claim Verifier — проверяет утверждения AI-агента против реального кода.

Позволяет агенту сделать структурированное утверждение вида:
  {"subject": "hybrid_search_async", "predicate": "calls", "object": "_bm25_search_async"}

И получает вердикт: confirmed / contradicted / unverifiable + строки кода.

API:
  verify_claim(claim={...}) -> dict
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.core.graph import EdgeType, NodeLabel
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.claim_verifier")

# ────────────────────────────────────────────────────────────
# Supported predicates and their check logic
# ────────────────────────────────────────────────────────────

PREDICATE_CALLS = "calls"
PREDICATE_DEFINED_IN = "defined_in"
PREDICATE_IMPORTS = "imports"
PREDICATE_HANDLES_ERROR = "handles_error"
PREDICATE_DEFINES = "defines"
PREDICATE_IMPLEMENTS = "implements"
PREDICATE_INHERITS = "inherits"

SUPPORTED_PREDICATES = {
    PREDICATE_CALLS,
    PREDICATE_DEFINED_IN,
    PREDICATE_IMPORTS,
    PREDICATE_HANDLES_ERROR,
    PREDICATE_DEFINES,
    PREDICATE_IMPLEMENTS,
    PREDICATE_INHERITS,
}


class ClaimVerifierTool(MCPTool):
    """verify_claim — проверяет утверждение AI-агента против SymbolIndex и PropertyGraph."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="verify_claim")

    @error_boundary("verify_claim", timeout_ms=10000)
    async def execute(
        self,
        claim: Dict[str, Any],
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Проверяет одно структурированное утверждение.

        Args:
            claim: Словарь с полями:
                - subject (str): Имя проверяемого символа (функция/класс/файл)
                - predicate (str): Тип утверждения:
                    "calls" — subject вызывает object
                    "defined_in" — subject определён в файле/модуле object
                    "imports" — subject (файл) импортирует object (модуль)
                    "handles_error" — subject содержит try/except
                    "defines" — subject (файл/класс) определяет object (функцию/метод)
                    "implements" — subject реализует object (интерфейс/класс)
                    "inherits" — subject наследует object
                - object (str): Цель утверждения (опционально для handles_error)
                - file (str, optional): Файл для сужения поиска
        """
        if not isinstance(claim, dict):
            return {"status": "error", "message": "claim must be a dict"}

        subject = claim.get("subject", "").strip()
        predicate = claim.get("predicate", "").strip()
        obj = claim.get("object", "").strip()
        file_hint = claim.get("file", "").strip()

        if not subject:
            return {"status": "error", "message": "claim.subject is required"}
        if predicate not in SUPPORTED_PREDICATES:
            return {
                "status": "error",
                "message": f"Unsupported predicate '{predicate}'. "
                           f"Supported: {sorted(SUPPORTED_PREDICATES)}",
            }

        # Диспетчеризация
        if predicate == PREDICATE_CALLS:
            return await self._verify_calls(subject, obj, file_hint)
        elif predicate == PREDICATE_DEFINED_IN:
            return await self._verify_defined_in(subject, obj, file_hint)
        elif predicate == PREDICATE_IMPORTS:
            return await self._verify_imports(subject, obj, file_hint)
        elif predicate == PREDICATE_HANDLES_ERROR:
            return await self._verify_error_handling(subject)
        elif predicate == PREDICATE_DEFINES:
            return await self._verify_defines(subject, obj)
        elif predicate in (PREDICATE_IMPLEMENTS, PREDICATE_INHERITS):
            return await self._verify_relationship(subject, obj, predicate)

        return {"status": "error", "message": f"Unhandled predicate: {predicate}"}

    # ── PropertyGraph access ──

    def _get_pg(self) -> tuple:
        """Получает PropertyGraph и SymbolIndexAdapter."""
        from src.core.graph import PropertyGraph
        from src.core.search.graph_adapter import SymbolIndexAdapter

        indexer = self.resolve_indexer()
        pg = getattr(indexer, "_graph", None) or getattr(indexer, "property_graph", None)
        if pg:
            adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
            return pg, adapter

        # Fallback: прямой путь
        db_path = self._services.resolve(PropertyGraph) if hasattr(self._services, 'resolve') else None
        if not db_path:
            candidate = Path("D:/Project/MSCodeBase/.codebase/graph.db")
            if candidate.exists():
                pg = PropertyGraph(candidate)
                adapter = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
                return pg, adapter
        return None, None

    # ── Individual verifiers ──

    async def _verify_calls(
        self, subject: str, obj: str, file_hint: str
    ) -> Dict[str, Any]:
        """Проверяет: subject вызывает object?"""
        pg, adapter = self._get_pg()
        if not pg:
            return _unverifiable("PropertyGraph not available", "calls")

        evidence = []
        nodes = pg.find_nodes(name_pattern=subject, limit=5)
        if not nodes:
            return _unverifiable(f"Symbol '{subject}' not found in PropertyGraph", "calls")

        for node in nodes[:3]:
            for neighbor, edge, _ in pg.get_neighbors(
                node.qualified_name,
                edge_type=EdgeType.CALLS,
                direction="outgoing",
                max_depth=1,
            ):
                if obj.lower() in neighbor.name.lower():
                    evidence.append({
                        "file": neighbor.file_path or edge.properties.get("file", "?"),
                        "line": edge.properties.get("line", 0),
                        "detail": f"{node.name} -> {neighbor.name}",
                    })

        if evidence:
            return _confirmed(f"{subject} calls {obj}", evidence, "calls")

        # Если не нашли — показываем, ЧТО вызывает subject
        callees = []
        for node in nodes[:1]:
            for neighbor, edge, _ in pg.get_neighbors(
                node.qualified_name,
                edge_type=EdgeType.CALLS,
                direction="outgoing",
                max_depth=1,
            ):
                callees.append(neighbor.name)
        if callees:
            return _contradicted(
                f"{subject} does NOT call {obj}. Actually calls: {callees[:10]}",
                [{"detail": f"Callees: {', '.join(callees[:10])}"}],
                "calls",
            )
        return _unverifiable(f"No call information for '{subject}'", "calls")

    async def _verify_defined_in(
        self, subject: str, obj: str, file_hint: str
    ) -> Dict[str, Any]:
        """Проверяет: subject определён в файле/модуле?"""
        pg, adapter = self._get_pg()
        if not pg:
            return _unverifiable("PropertyGraph not available", "defined_in")

        nodes = pg.find_nodes(name_pattern=subject, limit=5)
        if not nodes:
            # Fallback: поиск по SymbolIndex
            try:
                si = self.resolve_symbol_index()
                defs = si.find_definitions(subject) or []
                if defs:
                    files = list(set(d.file_path for d in defs))
                    if obj and any(obj in f for f in files):
                        return _confirmed(
                            f"{subject} defined in {files[0]}",
                            [{"file": files[0], "line": defs[0].line}],
                            "defined_in",
                        )
                    return _confirmed(
                        f"{subject} defined in: {', '.join(files[:3])}",
                        [{"file": f} for f in files[:3]],
                        "defined_in",
                    )
            except Exception:
                pass
            return _unverifiable(f"Symbol '{subject}' not found", "defined_in")

        node = nodes[0]
        file_path = node.file_path or ""
        if obj and obj in file_path:
            return _confirmed(
                f"{subject} defined in {file_path}",
                [{"file": file_path, "line": node.properties.get("line", 0)}],
                "defined_in",
            )
        if file_path:
            return _confirmed(
                f"{subject} defined in {file_path} (not {obj})" if obj else f"{subject} defined in {file_path}",
                [{"file": file_path, "line": node.properties.get("line", 0)}],
                "defined_in",
            )
        return _unverifiable(f"File for '{subject}' not found", "defined_in")

    async def _verify_imports(
        self, subject: str, obj: str, file_hint: str
    ) -> Dict[str, Any]:
        """Проверяет: subject (файл) импортирует object (модуль)?"""
        pg, adapter = self._get_pg()
        if not pg:
            return _unverifiable("PropertyGraph not available", "imports")

        # Ищем file node с именем, содержащим subject
        nodes = pg.find_nodes(name_pattern=subject, limit=5)
        file_nodes = [n for n in nodes if n.label == NodeLabel.FILE]

        if not file_nodes:
            return _unverifiable(
                f"File matching '{subject}' not found in PropertyGraph",
                "imports",
            )

        for fn in file_nodes[:2]:
            for neighbor, edge, _ in pg.get_neighbors(
                fn.qualified_name,
                edge_type=EdgeType.IMPORTS,
                direction="outgoing",
                max_depth=1,
            ):
                if not obj or obj.lower() in neighbor.name.lower():
                    return _confirmed(
                        f"{fn.name} imports {neighbor.name}",
                        [{
                            "file": fn.file_path or fn.name,
                            "line": edge.properties.get("line", 0),
                            "detail": f"import {neighbor.name}",
                        }],
                        "imports",
                    )

        return _contradicted(
            f"{subject} does NOT import {obj}" if obj else f"{subject} has no matching imports",
            [],
            "imports",
        )

    async def _verify_error_handling(
        self, subject: str
    ) -> Dict[str, Any]:
        """Проверяет: subject содержит try/except (обработку ошибок)?"""
        pg, adapter = self._get_pg()
        if not pg:
            return _unverifiable("PropertyGraph not available", "handles_error")

        nodes = pg.find_nodes(name_pattern=subject, limit=5)
        if not nodes:
            return _unverifiable(f"Symbol '{subject}' not found", "handles_error")

        node = nodes[0]
        file_path = node.file_path
        if not file_path:
            return _unverifiable(f"No file for '{subject}'", "handles_error")

        full_path = Path("D:/Project/MSCodeBase") / file_path
        if not full_path.exists():
            return _unverifiable(f"File not found: {file_path}", "handles_error")

        # Ищем try/except в тексте функции
        try:
            text = full_path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            start = node.properties.get("line", 0)
            # Берём 50 строк вокруг определения
            func_text = "\n".join(lines[start:start + 50])
            if "try" in func_text and ("except" in func_text or "finally" in func_text):
                evidence = []
                for i, line in enumerate(lines[start:start + 50], start):
                    if "try" in line or "except" in line or "finally" in line:
                        evidence.append({"line": i, "detail": line.strip()[:80]})
                return _confirmed(
                    f"{subject} handles errors ({len(evidence)} try/except blocks)",
                    evidence[:5],
                    "handles_error",
                )
            return _contradicted(
                f"No try/except found in {subject}",
                [{"detail": f"Scanned lines {start}-{start + 50} of {file_path}"}],
                "handles_error",
            )
        except Exception as e:
            return _unverifiable(f"Error reading file: {e}", "handles_error")

    async def _verify_defines(
        self, subject: str, obj: str
    ) -> Dict[str, Any]:
        """Проверяет: subject содержит определение object?"""
        pg, adapter = self._get_pg()
        if not pg:
            return _unverifiable("PropertyGraph not available", "defines")

        # Ищем субъект
        subject_nodes = pg.find_nodes(name_pattern=subject, limit=5)
        if not subject_nodes:
            return _unverifiable(f"'{subject}' not found", "defines")

        sn = subject_nodes[0]
        # Ищем DEFINES edges
        for neighbor, edge, _ in pg.get_neighbors(
            sn.qualified_name, edge_type=EdgeType.DEFINES, direction="outgoing", max_depth=1,
        ):
            if not obj or obj.lower() in neighbor.name.lower():
                return _confirmed(
                    f"{subject} defines {neighbor.name}",
                    [{
                        "file": neighbor.file_path or sn.file_path,
                        "line": edge.properties.get("line", 0),
                        "detail": f"defines {neighbor.name} ({neighbor.label})",
                    }],
                    "defines",
                )

        return _contradicted(f"'{subject}' does NOT define '{obj}'" if obj else f"'{subject}' has no DEFINES edges", [], "defines")

    async def _verify_relationship(
        self, subject: str, obj: str, rel_type: str
    ) -> Dict[str, Any]:
        """Проверяет implements/inherits отношения."""
        pg, adapter = self._get_pg()
        if not pg:
            return _unverifiable("PropertyGraph not available", rel_type)

        edge_type = EdgeType.IMPLEMENTS if rel_type == PREDICATE_IMPLEMENTS else EdgeType.INHERITS
        subject_nodes = pg.find_nodes(name_pattern=subject, limit=5)
        if not subject_nodes:
            return _unverifiable(f"'{subject}' not found", rel_type)

        sn = subject_nodes[0]
        for neighbor, edge, _ in pg.get_neighbors(
            sn.qualified_name, edge_type=edge_type, direction="outgoing", max_depth=1,
        ):
            if not obj or obj.lower() in neighbor.name.lower():
                return _confirmed(
                    f"{subject} {rel_type} {neighbor.name}",
                    [{
                        "file": neighbor.file_path or sn.file_path,
                        "line": edge.properties.get("line", 0),
                    }],
                    rel_type,
                )

        return _contradicted(f"No {rel_type} relationship found for '{subject}'", [], rel_type)


# ── Helper factories ──

def _confirmed(message: str, evidence: List[Dict], predicate: str) -> Dict:
    return {
        "status": "ok",
        "verdict": "confirmed",
        "message": message,
        "evidence": evidence,
        "confidence": 0.9,
        "predicate": predicate,
    }


def _contradicted(message: str, evidence: List[Dict], predicate: str) -> Dict:
    return {
        "status": "ok",
        "verdict": "contradicted",
        "message": message,
        "evidence": evidence,
        "confidence": 0.85,
        "predicate": predicate,
    }


def _unverifiable(message: str, predicate: str) -> Dict:
    return {
        "status": "ok",
        "verdict": "unverifiable",
        "message": message,
        "evidence": [],
        "confidence": 0.3,
        "predicate": predicate,
    }


__all__ = ["ClaimVerifierTool"]
