"""
Pure mode methods for SymbolIndexAdapter.

Содержит PURE (PropertyGraph-only) реализацию методов
для SymbolIndexAdapter. Подмешивается через PureGraphMixin.

Оригинальный SymbolIndexAdapter наследует PureGraphMixin
и получает эти методы автоматически.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from src.core.graph import (
    EdgeType,
    Node,
    NodeLabel,
)
from src.core.indexing.symbol_index import SymbolRef


class PureGraphMixin:
    """
    Mixin с PURE-методами SymbolIndexAdapter.

    Использует self._graph (PropertyGraph), self._lock, self._mode,
    self._definitions, self._references, self._file_to_defs,
    self._file_to_symbols, self._file_to_calls — всё задаётся
    в SymbolIndexAdapter.__init__().
    """

    # ── Pure Import (PropertyGraph контур) ────────────────

    def _pure_add_definitions(self, file_path: str, symbols: List[Dict]) -> None:
        """PropertyGraph контур: File-узел + символы + DEFINES рёбра.

        Вызывается из SymbolIndexAdapter.add_definitions() под self._lock.
        """
        project_name = self._get_project_name(file_path)
        file_qname = f"{project_name}.{file_path}"

        if not self._graph.get_node(file_qname):
            self._graph.add_node(
                name=Path(file_path).name,
                label=NodeLabel.FILE,
                qualified_name=file_qname,
                file_path=file_path,
            )

        for sym in symbols:
            name = sym["name"]
            kind = sym.get("kind", "function")
            line = sym.get("line", 0)
            qname = f"{project_name}.{file_path}.{name}"

            label_map = {
                "function_definition": NodeLabel.FUNCTION,
                "function": NodeLabel.FUNCTION,
                "class_definition": NodeLabel.CLASS,
                "class": NodeLabel.CLASS,
                "method_definition": NodeLabel.METHOD,
                "method": NodeLabel.METHOD,
                "interface": NodeLabel.INTERFACE,
                "enum": NodeLabel.ENUM,
                "type": NodeLabel.TYPE,
                "variable": NodeLabel.VARIABLE,
            }
            node_label = label_map.get(kind, NodeLabel.FUNCTION)

            self._graph.add_node(
                name=name,
                label=node_label,
                qualified_name=qname,
                file_path=file_path,
                properties={"line": line, "kind": kind},
            )

            # DEFINES ребро: File → Symbol
            self._graph.add_edge(
                source_qname=file_qname,
                target_qname=qname,
                type=EdgeType.DEFINES,
                weight=1.0,
                properties={"line": line, "kind": kind},
            )

    def _pure_add_references(self, file_path: str, calls: List[Dict]) -> None:
        """PropertyGraph контур: CALLS рёбра между Function/Method узлами.

        Вызывается из SymbolIndexAdapter.add_references() под self._lock.
        """
        project_name = self._get_project_name(file_path)

        for call in calls:
            caller = call.get("caller", "")
            callee = call.get("callee", "")
            line = call.get("line", 0)

            if not caller or not callee or caller == callee:
                continue

            # PropertyGraph контур
            caller_qname = f"{project_name}.{file_path}.{caller}"

            # Пытаемся найти callee в PropertyGraph
            callee_nodes = self._graph.find_nodes(
                name_pattern=callee,
                limit=5,
            )
            if callee_nodes:
                for cn in callee_nodes:
                    self._graph.add_edge(
                        source_qname=caller_qname,
                        target_qname=cn.qualified_name,
                        type=EdgeType.CALLS,
                        weight=1.0,
                        properties={"line": line, "file": file_path},
                    )
            else:
                # callee ещё не проиндексирован — создаём placeholder
                callee_qname = f"{project_name}.__extern__.{callee}"
                self._graph.add_node(
                    name=callee,
                    label=NodeLabel.FUNCTION,
                    qualified_name=callee_qname,
                    properties={"line": line, "file": file_path, "placeholder": True},
                )
                self._graph.add_edge(
                    source_qname=caller_qname,
                    target_qname=callee_qname,
                    type=EdgeType.CALLS,
                    weight=1.0,
                    properties={"line": line, "file": file_path},
                )

    def _pure_remove_file(self, file_path: str) -> None:
        """PropertyGraph контур: удаляет файл и все его символы.

        Вызывается из SymbolIndexAdapter.remove_file() под self._lock.
        """
        project_name = self._get_project_name(file_path)
        file_qname = f"{project_name}.{file_path}"
        self._graph.delete_node(file_qname)
        for node in self._graph.find_nodes(file_path=file_path):
            self._graph.delete_node(node.qualified_name)

    # ── Call Chain ────────────────────────────────────────

    def _graph_call_chain(self, node: Node, direction: str, max_depth: int) -> Dict:
        """Call chain из PropertyGraph."""
        result = {
            "symbol": node.name,
            "callers_chain": [],
            "callees_chain": [],
            "total_connected": 0,
        }

        if direction in ("up", "both"):
            for neighbor, edge, depth in self._graph.get_neighbors(
                node.qualified_name, edge_type=EdgeType.CALLS,
                direction="incoming", max_depth=max_depth,
            ):
                result["callers_chain"].append({
                    "symbol": neighbor.name, "file": neighbor.file_path,
                    "line": edge.properties.get("line", 0), "depth": depth,
                })

        if direction in ("down", "both"):
            for neighbor, edge, depth in self._graph.get_neighbors(
                node.qualified_name, edge_type=EdgeType.CALLS,
                direction="outgoing", max_depth=max_depth,
            ):
                result["callees_chain"].append({
                    "symbol": neighbor.name, "file": neighbor.file_path,
                    "line": edge.properties.get("line", 0), "depth": depth,
                })

        result["total_connected"] = len(result["callers_chain"]) + len(result["callees_chain"])
        return result

    def get_call_chain(self, symbol: str, direction: str = "both", max_depth: int = 3) -> Dict:
        """Цепочка вызовов: кто вызывает (up) / кого вызывает (down).

        Использует PropertyGraph.get_neighbors с BFS.
        """
        nodes = self._graph.find_nodes(name_pattern=symbol, limit=5)
        if nodes:
            return self._graph_call_chain(nodes[0], direction, max_depth)

        # HYBRID fallback
        with self._lock:
            return self._hybrid_call_chain(symbol, direction, max_depth)

    # ── Поиск ─────────────────────────────────────────────

    def find_definitions(self, symbol: str) -> List[SymbolRef]:
        """Где определён символ.

        Сначала PropertyGraph, fallback на in-memory HYBRID.
        """
        # Пробуем через PropertyGraph
        nodes = self._graph.find_nodes(name_pattern=symbol, limit=20)
        if nodes:
            result = []
            for n in nodes:
                if n.label in (NodeLabel.FUNCTION, NodeLabel.CLASS, NodeLabel.METHOD):
                    result.append(SymbolRef(
                        symbol=n.name,
                        file_path=n.file_path,
                        line=n.properties.get("line", 0),
                        kind=n.properties.get("kind", n.label.lower()),
                        is_definition=True,
                    ))
            if result:
                return result

        # HYBRID fallback
        with self._lock:
            result = self._definitions.get(symbol, [])
            if result:
                return list(result)
            try:
                fallback = self.search_symbols(symbol, top_k=5)
                return [r for r in fallback if r.is_definition]
            except Exception:
                return []

    def find_references(self, symbol: str) -> List[SymbolRef]:
        """Где используется символ."""
        # PropertyGraph: ищем incoming CALLS edges
        nodes = self._graph.find_nodes(name_pattern=symbol, limit=5)
        if nodes:
            refs = []
            for n in nodes:
                neighbors = self._graph.get_neighbors(
                    n.qualified_name, edge_type=EdgeType.CALLS, direction="incoming",
                )
                for neighbor, edge, _depth in neighbors:
                    refs.append(SymbolRef(
                        symbol=neighbor.name,
                        file_path=edge.properties.get("file", neighbor.file_path),
                        line=edge.properties.get("line", 0),
                        kind="call",
                        is_definition=False,
                    ))
            if refs:
                return refs

        # HYBRID fallback
        with self._lock:
            return list(self._references.get(symbol, []))

    def get_symbols_in_file(self, file_path: str) -> List[str]:
        """Возвращает список символов, определённых в файле."""
        file_path = Path(file_path).resolve().as_posix()

        # PropertyGraph: находим узлы по file_path
        nodes = self._graph.find_nodes(file_path=file_path)
        if nodes:
            return [n.name for n in nodes
                    if n.label in (NodeLabel.FUNCTION, NodeLabel.CLASS,
                                   NodeLabel.METHOD, NodeLabel.INTERFACE)]

        # HYBRID
        with self._lock:
            return list(self._file_to_defs.get(file_path, set()))

    def get_symbol_context(self, symbol: str) -> Dict:
        """Контекст символа: определения + вызовы."""
        nodes = self._graph.find_nodes(name_pattern=symbol, limit=10)
        if not nodes:
            with self._lock:
                return self._get_hybrid_symbol_context(symbol)

        node = nodes[0]
        defined_in = [{"file": node.file_path, "line": node.properties.get("line", 0),
                       "kind": node.properties.get("kind", node.label.lower())}]

        # Входящие вызовы (callers)
        callers = []
        for neighbor, edge, _depth in self._graph.get_neighbors(
            node.qualified_name, edge_type=EdgeType.CALLS, direction="incoming",
        ):
            callers.append({"symbol": neighbor.name, "file": neighbor.file_path,
                            "line": edge.properties.get("line", 0)})

        # Исходящие вызовы (callees)
        callees = []
        for neighbor, edge, _depth in self._graph.get_neighbors(
            node.qualified_name, edge_type=EdgeType.CALLS, direction="outgoing",
        ):
            callees.append({"symbol": neighbor.name, "file": neighbor.file_path,
                            "line": edge.properties.get("line", 0)})

        return {
            "symbol": symbol,
            "defined_in": defined_in,
            "used_in_count": len(set(c["file"] for c in callers)),
            "used_in_files": list(set(c["file"] for c in callers))[:10],
            "calls_count": len(callees),
            "calls": callees[:10],
        }

    def _get_hybrid_symbol_context(self, symbol: str) -> Dict:
        """HYBRID fallback для get_symbol_context."""
        defs = self._definitions.get(symbol, [])
        refs = self._references.get(symbol, [])
        if not defs and not refs:
            return {}
        unique_files_using = set(r.file_path for r in refs if not r.is_definition)
        callees = []
        for callee_sym, callee_refs in self._references.items():
            for ref in callee_refs:
                if ref.symbol == symbol and not ref.is_definition:
                    callees.append({"symbol": callee_sym, "file": ref.file_path, "line": ref.line})
        return {
            "symbol": symbol,
            "defined_in": [{"file": d.file_path, "line": d.line, "kind": d.kind} for d in defs],
            "used_in_count": len(unique_files_using),
            "used_in_files": list(unique_files_using)[:10],
            "calls_count": len(callees),
            "calls": callees[:10],
        }


__all__ = ["PureGraphMixin"]
