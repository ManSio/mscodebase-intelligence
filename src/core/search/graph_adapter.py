"""
Graph Adapters — обратная совместимость между PropertyGraph и существующими
интерфейсами SymbolIndex / GraphRAGQueryEngine / RelationExtractor.

Позволяет внедрить PropertyGraph без единого изменения в существующих
потребителях (MCP-инструменты, intelligence_layer, search_tools).

Стратегия адаптации:
    1. SymbolIndexAdapter — оборачивает PropertyGraph в интерфейс SymbolIndex
       (add_definitions, add_references, get_call_chain, impact_analysis...)
    2. GraphRAGAdapter — оборачивает PropertyGraph + адаптированный SymbolIndex
       в интерфейс GraphRAGQueryEngine
    3. CompositionAdapter — объединяет все три адаптера в единую точку входа

Фаза 1: PropertyGraph + адаптеры (текущий код работает без изменений)
Фаза 2: Прямое внедрение PropertyGraph в инструменты (удаление адаптеров)
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from src.core.graph import (
    EdgeType,
    Node,
    NodeLabel,
    PropertyGraph,
)
from src.core.symbol_index import SymbolRef
from src.core.search.graph_adapter_pure import PureGraphMixin

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
# SymbolIndexAdapter — PropertyGraph → SymbolIndex
# ════════════════════════════════════════════════════════════

class SymbolIndexAdapter(PureGraphMixin):
    """
    Адаптер PropertyGraph → интерфейс SymbolIndex.

    Хранит PropertyGraph + дублирует некоторые in-memory структуры
    SymbolIndex для полной обратной совместимости.

    Два режима:
    - HYBRID: PropertyGraph + in-memory Dict (для плавной миграции)
    - PURE: только PropertyGraph (после полной миграции потребителей)
    """

    MODE_HYBRID = "hybrid"
    MODE_PURE = "pure"

    def __init__(self, graph: PropertyGraph, mode: str = MODE_HYBRID):
        self._graph = graph
        self._mode = mode
        self._lock = threading.RLock()

        # In-memory структуры для HYBRID режима (совместимость)
        self._definitions: Dict[str, List[SymbolRef]] = {}
        self._references: Dict[str, List[SymbolRef]] = {}
        self._file_to_symbols: Dict[str, Set[str]] = {}
        self._file_to_defs: Dict[str, Set[str]] = {}
        self._file_to_calls: Dict[str, Set[str]] = {}
        self._id_pattern = __import__("re").compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

    @property
    def graph(self) -> PropertyGraph:
        return self._graph

    # ── Импорт из парсера ─────────────────────────────────

    def add_definitions(self, file_path: str, symbols: List[Dict]) -> None:
        """Добавляет определения символов из распаршенного файла.

        Два контура:
        - PropertyGraph: Node(Function|Class|Method) + DEFINES/IMPLEMENTS edges
        - In-memory: SymbolIndex._definitions (HYBRID режим)
        """
        file_path = Path(file_path).resolve().as_posix()

        with self._lock:
            # 1. PropertyGraph контур (PureGraphMixin)
            self._pure_add_definitions(file_path, symbols)

            # 2. In-memory контур (HYBRID)
            if self._mode == self.MODE_HYBRID:
                self._hybrid_add_definitions(file_path, symbols)

    def _hybrid_add_definitions(self, file_path: str, symbols: List[Dict]):
        """HYBRID: дублирует в in-memory структуры."""
        if file_path not in self._file_to_symbols:
            self._file_to_symbols[file_path] = set()
        if file_path not in self._file_to_defs:
            self._file_to_defs[file_path] = set()

        defined_names = set()
        for sym in symbols:
            name = sym["name"]
            defined_names.add(name)
            ref = SymbolRef(
                symbol=name,
                file_path=file_path,
                line=sym["line"],
                kind=sym.get("kind", "function"),
                is_definition=True,
            )
            if name not in self._definitions:
                self._definitions[name] = []
            existing = {r.line for r in self._definitions[name] if r.file_path == file_path}
            if sym["line"] not in existing:
                self._definitions[name].append(ref)
            self._file_to_symbols[file_path].add(name)

        self._file_to_defs[file_path] = defined_names

    def add_references(self, file_path: str, calls: List[Dict]) -> None:
        """Добавляет связи вызовов.

        PropertyGraph: CALLS/ASYNC_CALLS edges между Function/Method nodes.
        """
        file_path = Path(file_path).resolve().as_posix()

        with self._lock:
            # 1. PropertyGraph контур (PureGraphMixin)
            self._pure_add_references(file_path, calls)

            # 2. HYBRID: дублируем в in-memory
            if self._mode == self.MODE_HYBRID:
                self._hybrid_add_references(file_path, calls)

    def add_assignments(self, file_path: str, assignments: List[Dict]) -> None:
        """Добавляет ASSIGNED_FROM связи между переменными.

        Создаёт Variable-узлы для source и target, если их ещё нет,
        и проводит ASSIGNED_FROM ребро от source → target.

        Поток: Variable(source) --[ASSIGNED_FROM]--> Variable(target)
        """
        file_path = Path(file_path).resolve().as_posix()
        project_name = self._get_project_name(file_path)

        if not assignments:
            return

        with self._lock:
            for a in assignments:
                target = a.get("target", "")
                source = a.get("source", "")
                line = a.get("line", 0)
                function = a.get("function", "")
                condition_path = a.get("condition_path")
                scope_id = a.get("scope_id")

                if not target or not source or target == source:
                    continue

                # Qualified names для source и target переменных
                source_qname = f"{project_name}.{file_path}.{source}"
                target_qname = f"{project_name}.{file_path}.{target}"

                # Убеждаемся, что оба узла существуют (создаём если нет)
                for qname, name in [(source_qname, source), (target_qname, target)]:
                    existing = self._graph.get_node(qname)
                    if not existing:
                        props_node = {
                            "line": line,
                            "function": function,
                        }
                        if scope_id:
                            props_node["function_scope"] = scope_id
                        self._graph.add_node(
                            name=name,
                            label=NodeLabel.VARIABLE,
                            qualified_name=qname,
                            file_path=file_path,
                            properties=props_node,
                        )

                # ASSIGNED_FROM ребро: source → target
                props = {
                    "line": line,
                    "function": function,
                    "file": file_path,
                }
                if condition_path:
                    props["condition_path"] = condition_path
                if scope_id:
                    props["scope_id"] = scope_id

                self._graph.add_edge(
                    source_qname=source_qname,
                    target_qname=target_qname,
                    type=EdgeType.ASSIGNED_FROM,
                    weight=1.0,
                    properties=props,
                )

    def _hybrid_add_references(self, file_path: str, calls: List[Dict]):
        """HYBRID: дублирует в in-memory структуры SymbolIndex."""
        if file_path not in self._file_to_symbols:
            self._file_to_symbols[file_path] = set()
        if file_path not in self._file_to_calls:
            self._file_to_calls[file_path] = set()

        for call in calls:
            caller = call.get("caller", "")
            callee = call.get("callee", "")
            line = call.get("line", 0)
            if not caller or not callee or caller == callee:
                continue

            if callee not in self._references:
                self._references[callee] = []
            existing = {(r.file_path, r.line) for r in self._references[callee] if r.symbol == caller}
            if (file_path, line) not in existing:
                self._references[callee].append(
                    SymbolRef(symbol=caller, file_path=file_path, line=line, kind="call", is_definition=False)
                )

            self._file_to_calls[file_path].add(callee)
            self._file_to_symbols[file_path].add(caller)
            self._file_to_symbols[file_path].add(callee)

    def remove_file(self, file_path: str) -> None:
        """Удаляет все данные о файле."""
        file_path = Path(file_path).resolve().as_posix()

        with self._lock:
            # 1. PropertyGraph: удаляем файл и все связанные узлы/рёбра (PureGraphMixin)
            self._pure_remove_file(file_path)

            # 2. HYBRID: чистим in-memory
            if self._mode == self.MODE_HYBRID:
                self._hybrid_remove_file(file_path)

    def _hybrid_remove_file(self, file_path: str):
        """HYBRID: чистит in-memory."""
        symbols = self._file_to_symbols.pop(file_path, set())
        self._file_to_defs.pop(file_path, None)
        self._file_to_calls.pop(file_path, None)
        for sym in symbols:
            if sym in self._definitions:
                self._definitions[sym] = [r for r in self._definitions[sym] if r.file_path != file_path]
                if not self._definitions[sym]:
                    del self._definitions[sym]
            if sym in self._references:
                self._references[sym] = [r for r in self._references[sym] if r.file_path != file_path]
                if not self._references[sym]:
                    del self._references[sym]

    # ── Поиск ─────────────────────────────────────────────

    def find_variables(
        self,
        name: str,
        scope_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict]:
        """Находит Variable-узлы по имени, опционально фильтруя по scope_id.

        Без scope_id: возвращает все переменные с таким именем + их scope_id.
        С scope_id: возвращает только конкретную переменную.

        Returns:
            Список словарей: name, file_path, line, function, function_scope (scope_id)
        """
        if scope_id:
            nodes = self._graph.find_nodes_by_property(
                label=NodeLabel.VARIABLE,
                property_key="function_scope",
                property_value=scope_id,
                name_pattern=name,
                limit=limit,
            )
        else:
            nodes = self._graph.find_nodes(
                label=NodeLabel.VARIABLE,
                name_pattern=name,
                limit=limit,
            )

        results = []
        for n in nodes:
            entry = {
                "name": n.name,
                "file_path": n.file_path,
                "line": n.properties.get("line", 0),
                "function": n.properties.get("function", ""),
                "function_scope": n.properties.get("function_scope", ""),
                "qualified_name": n.qualified_name,
            }
            results.append(entry)
        return results

    def get_variable_flow(
        self,
        variable_name: str,
        scope_id: Optional[str] = None,
        file_path: Optional[str] = None,
        max_depth: int = 3,
    ) -> Dict:
        """Возвращает полный Data Flow для переменной.

        Ищет Variable-узел по имени + scope_id (если указан),
        затем собирает цепочку ASSIGNED_FROM (откуда пришло значение)
        и ASSIGNED_TO (куда пошло дальше).

        Returns:
            Dict с variable (инфо об узле), incoming (откуда),
            outgoing (куда), chain (полная цепочка присваиваний)
        """
        results = self.find_variables(variable_name, scope_id=scope_id, limit=5)
        if not results:
            return {"variable": None, "incoming": [], "outgoing": [], "chain": []}

        # Если scope_id не указан, но нашли только один — используем его
        var_info = results[0]
        var_qname = var_info["qualified_name"]

        # Собираем ASSIGNED_FROM цепочку через обход графа
        chain = []
        incoming = []
        outgoing = []

        # Outgoing: от этой переменной к другим (это источник для других)
        neighbors = self._graph.get_neighbors(
            var_qname,
            edge_type=EdgeType.ASSIGNED_FROM,
            direction="outgoing",
            max_depth=max_depth,
        )
        for neighbor_node, edge, depth in neighbors:
            entry = {
                "depth": depth,
                "target_name": neighbor_node.name,
                "target_file": neighbor_node.file_path,
                "line": edge.properties.get("line", 0),
                "condition_path": edge.properties.get("condition_path", []),
                "scope_id": edge.properties.get("scope_id", ""),
            }
            outgoing.append(entry)
            chain.append({
                "from": var_info["name"],
                "to": neighbor_node.name,
                "via": "ASSIGNED_FROM",
                "condition_path": edge.properties.get("condition_path", []),
                "line": edge.properties.get("line", 0),
            })

        # Incoming: от других переменных к этой (откуда берётся значение)
        neighbors = self._graph.get_neighbors(
            var_qname,
            edge_type=EdgeType.ASSIGNED_FROM,
            direction="incoming",
            max_depth=max_depth,
        )
        for neighbor_node, edge, depth in neighbors:
            entry = {
                "depth": depth,
                "source_name": neighbor_node.name,
                "source_file": neighbor_node.file_path,
                "line": edge.properties.get("line", 0),
                "condition_path": edge.properties.get("condition_path", []),
                "scope_id": edge.properties.get("scope_id", ""),
            }
            incoming.append(entry)
            chain.append({
                "from": neighbor_node.name,
                "to": var_info["name"],
                "via": "ASSIGNED_FROM",
                "condition_path": edge.properties.get("condition_path", []),
                "line": edge.properties.get("line", 0),
            })

        return {
            "variable": var_info,
            "incoming": incoming,
            "outgoing": outgoing,
            "chain": chain,
        }



    def _hybrid_call_chain(self, symbol: str, direction: str, max_depth: int) -> Dict:
        """HYBRID call chain из in-memory."""
        visited: Set[str] = set()
        result = {"symbol": symbol, "callers_chain": [], "callees_chain": [], "total_connected": 0}

        if direction in ("up", "both"):
            current_level = {symbol}
            for d in range(max_depth):
                next_level = set()
                for sym in current_level:
                    if sym in visited:
                        continue
                    visited.add(sym)
                    refs = self._references.get(sym, [])
                    for r in refs:
                        if not r.is_definition and r.symbol != symbol:
                            result["callers_chain"].append(
                                {"symbol": r.symbol, "file": r.file_path, "line": r.line, "depth": d + 1}
                            )
                            next_level.add(r.symbol)
                current_level = next_level
                if not current_level:
                    break

        visited_callees: Set[str] = set()
        if direction in ("down", "both"):
            current_level = {symbol}
            for d in range(max_depth):
                next_level = set()
                for sym in current_level:
                    if sym in visited_callees:
                        continue
                    visited_callees.add(sym)
                    for callee_sym, callee_refs in self._references.items():
                        if callee_sym in visited_callees:
                            continue
                        for ref in callee_refs:
                            if ref.symbol == sym and not ref.is_definition:
                                result["callees_chain"].append(
                                    {"symbol": callee_sym, "file": ref.file_path,
                                     "line": ref.line, "depth": d + 1}
                                )
                                next_level.add(callee_sym)
                current_level = next_level
                if not current_level:
                    break

        result["total_connected"] = len(result["callers_chain"]) + len(result["callees_chain"])
        return result

    # ── Search ────────────────────────────────────────────

    def search_symbols(self, query: str, top_k: int = 10) -> List[SymbolRef]:
        """Поиск символов по имени (частичное совпадение).

        PropertyGraph: find_nodes с name_pattern LIKE.
        """
        # PropertyGraph search
        pattern = f"%{query}%"
        nodes = self._graph.find_nodes(
            name_pattern=pattern,
            limit=top_k,
        )
        if nodes:
            result = []
            for n in nodes:
                result.append(SymbolRef(
                    symbol=n.name, file_path=n.file_path,
                    line=n.properties.get("line", 0),
                    kind=n.properties.get("kind", n.label.lower()),
                    is_definition=True,
                ))
            return result

        # HYBRID fallback
        query_lower = query.lower()
        scored: List[Tuple[int, str]] = []

        with self._lock:
            for name in self._definitions:
                if query_lower in name.lower():
                    refs = self._references.get(name, [])
                    unique_users = len(set(r.file_path for r in refs))
                    scored.append((unique_users, name))
            for name in self._references:
                if query_lower in name.lower() and name not in self._definitions:
                    refs = self._references.get(name, [])
                    unique_users = len(set(r.file_path for r in refs))
                    scored.append((unique_users // 2, name))

        scored.sort(key=lambda x: -x[0])
        results: List[SymbolRef] = []
        for _, name in scored[:top_k]:
            with self._lock:
                defs = self._definitions.get(name, [])
                refs = self._references.get(name, [])
            results.extend(defs)
            results.extend(refs)
        return results

    # ── Call Graph ────────────────────────────────────────

    def build_call_graph(self, symbol: str, depth: int = 2) -> Dict:
        """Строит граф вызовов (BFS)."""
        nodes = self._graph.find_nodes(name_pattern=symbol, limit=5)
        if nodes:
            return self._graph_build_call_graph(nodes[0], depth)

        with self._lock:
            return self._hybrid_build_call_graph(symbol, depth)

    def _graph_build_call_graph(self, node: Node, depth: int) -> Dict:
        """Call graph из PropertyGraph."""
        result = {
            "symbol": node.name,
            "definition": [{"file": node.file_path, "line": node.properties.get("line", 0),
                            "kind": node.properties.get("kind", node.label.lower())}],
            "callers": [],
            "callees": [],
            "call_chain": [],
            "impact_files": {node.file_path},
            "depth_reached": 0,
        }

        visited_callers: Set[str] = {node.qualified_name}
        current_level = {node.qualified_name}
        for level in range(depth):
            next_level: Set[str] = set()
            for qname in current_level:
                for neighbor, edge, _depth in self._graph.get_neighbors(
                    qname, edge_type=EdgeType.CALLS, direction="incoming"
                ):
                    if neighbor.qualified_name in visited_callers:
                        continue
                    visited_callers.add(neighbor.qualified_name)
                    result["callers"].append({
                        "symbol": neighbor.name, "file": neighbor.file_path,
                        "line": edge.properties.get("line", 0),
                        "kind": neighbor.properties.get("kind", neighbor.label.lower()),
                        "depth": level + 1,
                    })
                    result["impact_files"].add(neighbor.file_path)
                    next_level.add(neighbor.qualified_name)
            current_level = next_level
            if not current_level:
                break
            result["depth_reached"] = level + 1

        # Аналогично для callees
        visited_callees: Set[str] = {node.qualified_name}
        current_level = {node.qualified_name}
        for level in range(depth):
            next_level = set()
            for qname in current_level:
                for neighbor, edge, _depth in self._graph.get_neighbors(
                    qname, edge_type=EdgeType.CALLS, direction="outgoing"
                ):
                    if neighbor.qualified_name in visited_callees:
                        continue
                    visited_callees.add(neighbor.qualified_name)
                    result["callees"].append({
                        "symbol": neighbor.name, "file": neighbor.file_path,
                        "line": edge.properties.get("line", 0),
                        "kind": neighbor.properties.get("kind", neighbor.label.lower()),
                        "depth": level + 1,
                    })
                    result["impact_files"].add(neighbor.file_path)
                    next_level.add(neighbor.qualified_name)
            current_level = next_level
            if not current_level:
                break

        if result["callers"]:
            top_callers = sorted(result["callers"], key=lambda c: c.get("depth", 99))[:5]
            result["call_chain"] = [f"{c['symbol']} ({c['file']}:{c['line']})" for c in top_callers]

        result["impact_files"] = sorted(result["impact_files"])
        return result

    def _hybrid_build_call_graph(self, symbol: str, depth: int) -> Dict:
        """HYBRID call graph из in-memory."""
        result = {
            "symbol": symbol,
            "definition": [],
            "callers": [],
            "callees": [],
            "call_chain": [],
            "impact_files": set(),
            "depth_reached": 0,
        }
        if depth < 1:
            depth = 1
        if depth > 5:
            depth = 5

        visited_callers: Set[str] = set()
        visited_callees: Set[str] = set()

        defs = self._definitions.get(symbol, [])
        for d in defs:
            result["definition"].append({"file": d.file_path, "line": d.line, "kind": d.kind})
            result["impact_files"].add(d.file_path)

        current_level_callers = {symbol}
        for level in range(depth):
            next_level_callers = set()
            for sym in current_level_callers:
                if sym in visited_callers:
                    continue
                visited_callers.add(sym)
                refs = self._references.get(sym, [])
                for r in refs:
                    if r.is_definition:
                        continue
                    caller_sym = r.symbol
                    if caller_sym == symbol:
                        continue
                    caller_entry = {"symbol": caller_sym, "file": r.file_path,
                                    "line": r.line, "kind": r.kind, "depth": level + 1}
                    if not any(c.get("symbol") == caller_sym and c.get("file") == r.file_path
                               for c in result["callers"]):
                        result["callers"].append(caller_entry)
                        result["impact_files"].add(r.file_path)
                        next_level_callers.add(caller_sym)
            current_level_callers = next_level_callers
            if not current_level_callers:
                break
            result["depth_reached"] = level + 1

        current_level_callees = {symbol}
        for level in range(depth):
            next_level_callees = set()
            for sym in current_level_callees:
                if sym in visited_callees:
                    continue
                visited_callees.add(sym)
                for callee_sym, callee_refs in self._references.items():
                    if callee_sym == symbol:
                        continue
                    for ref in callee_refs:
                        if ref.symbol == sym and not ref.is_definition:
                            callee_entry = {"symbol": callee_sym, "file": ref.file_path,
                                            "line": ref.line, "kind": ref.kind, "depth": level + 1}
                            if not any(c.get("symbol") == callee_sym for c in result["callees"]):
                                result["callees"].append(callee_entry)
                                result["impact_files"].add(ref.file_path)
                                next_level_callees.add(callee_sym)
            current_level_callees = next_level_callees
            if not current_level_callees:
                break

        if result["callers"]:
            top_callers = sorted(result["callers"], key=lambda c: c.get("depth", 99))[:5]
            result["call_chain"] = [f"{c['symbol']} ({c['file']}:{c['line']})" for c in top_callers]

        result["impact_files"] = sorted(result["impact_files"])
        return result

    # ── Impact Analysis ───────────────────────────────────

    def get_impact_analysis(self, symbol: str, depth: int = 3) -> Dict:
        """Анализ влияния изменения символа."""
        call_graph = self.build_call_graph(symbol, depth=depth)

        direct_callers = sum(1 for c in call_graph["callers"] if c.get("depth") == 1)
        transitive_callers = len(call_graph["callers"]) - direct_callers
        direct_callees = sum(1 for c in call_graph["callees"] if c.get("depth") == 1)
        transitive_callees = len(call_graph["callees"]) - direct_callees

        affected_files = call_graph.get("impact_files", [])
        affected_modules = set()
        for f in affected_files:
            parts = f.replace("\\", "/").split("/")
            for part in parts:
                if part and "." not in part and part != "src":
                    affected_modules.add(part)
                    break

        risk_score = 0
        risk_score += min(direct_callers * 5, 30)
        risk_score += min(transitive_callers * 2, 20)
        risk_score += min(len(affected_files) * 3, 25)
        risk_score += min(len(affected_modules) * 5, 15)
        risk_score += min(direct_callees * 2, 10)
        risk_score = min(risk_score, 100)
        risk_level = "critical" if risk_score >= 70 else "high" if risk_score >= 50 else "medium" if risk_score >= 25 else "low"

        return {
            "symbol": symbol,
            "direct_callers": direct_callers,
            "transitive_callers": transitive_callers,
            "direct_callees": direct_callees,
            "transitive_callees": transitive_callees,
            "affected_files": affected_files,
            "affected_modules": sorted(affected_modules),
            "risk_level": risk_level,
            "risk_score": risk_score,
            "call_graph": call_graph,
        }

    def get_architectural_diff(self, changed_files: List[str]) -> Dict:
        """Анализирует влияние изменений в файлах на архитектуру."""
        with self._lock:
            added_symbols = []
            affected_callers = []
            all_impact_files = set()

            for file_path in changed_files:
                file_path = Path(file_path).resolve().as_posix()
                defs = self._file_to_defs.get(file_path, set())
                for sym_name in defs:
                    sym_defs = self._definitions.get(sym_name, [])
                    for sd in sym_defs:
                        if sd.file_path == file_path:
                            added_symbols.append({"symbol": sym_name, "kind": sd.kind, "line": sd.line})
                    refs = self._references.get(sym_name, [])
                    for r in refs:
                        if r.file_path != file_path:
                            affected_callers.append({"symbol": sym_name, "called_from": r.file_path, "line": r.line})
                            all_impact_files.add(r.file_path)

            summary_parts = []
            for sym in added_symbols[:10]:
                callers = [c for c in affected_callers if c["symbol"] == sym["symbol"]]
                if callers:
                    files = list(set(c["called_from"] for c in callers))[:3]
                    summary_parts.append(f"{sym['kind'].upper()} {sym['symbol']} -> используется в {', '.join(files)}")
                else:
                    summary_parts.append(f"{sym['kind'].upper()} {sym['symbol']} (нет внешних зависимостей)")

            return {
                "changed_files": changed_files,
                "added_symbols": added_symbols,
                "affected_callers": affected_callers,
                "impact_files": sorted(all_impact_files),
                "impact_summary": "\n".join(summary_parts),
            }

    # ── Stats ─────────────────────────────────────────────

    def stats(self) -> Dict:
        """Статистика индекса символов."""
        summary = self._graph.get_graph_summary()
        with self._lock:
            return {
                "total_symbols": summary.get("total_nodes", 0),
                "total_definitions": len(self._definitions),
                "total_references": len(self._references),
                "tracked_files": summary.get("total_files", 0),
            }

    def get_symbol_count(self) -> int:
        return self._graph.count_nodes()

    # ── Совместимость с Intelligence Layer ────────────────

    def get_callers(self, symbol: str) -> List[SymbolRef]:
        """Кто вызывает этот символ."""
        nodes = self._graph.find_nodes(name_pattern=symbol, limit=5)
        if nodes:
            result = []
            for neighbor, edge, _depth in self._graph.get_neighbors(
                nodes[0].qualified_name, edge_type=EdgeType.CALLS, direction="incoming"
            ):
                result.append(SymbolRef(
                    symbol=neighbor.name, file_path=neighbor.file_path,
                    line=edge.properties.get("line", 0), kind="call", is_definition=False,
                ))
            return result
        return [r for r in self.find_references(symbol) if not r.is_definition]

    def get_callees(self, symbol: str) -> List[Dict]:
        """Кого вызывает этот символ."""
        graph = self.build_call_graph(symbol, depth=1)
        return graph.get("callees", [])

    def get_references(self, symbol: str) -> List[SymbolRef]:
        """Все упоминания символа."""
        return self.find_references(symbol)

    # ── Index Project ─────────────────────────────────────

    def index_project(self, project_path: str, parser) -> None:
        """Индексирует проект через PropertyGraph."""
        import os
        project_root = Path(project_path).resolve()

        for root, dirs, files in os.walk(str(project_root)):
            dirs[:] = [d for d in dirs if not self._should_skip_dir(d)]
            for file in files:
                abs_file_path = Path(root) / file
                chunks, symbols = parser.parse_file(abs_file_path)
                rel_path = abs_file_path.relative_to(project_root).as_posix()
                self.remove_file(rel_path)
                if symbols:
                    self.add_definitions(rel_path, symbols)
                if hasattr(parser, "extract_calls"):
                    calls = parser.extract_calls(abs_file_path)
                    if calls:
                        for call in calls:
                            call["file"] = rel_path
                        self.add_references(rel_path, calls)

    def _should_skip_dir(self, dir_name: str) -> bool:
        skip_dirs = {
            ".git", "node_modules", "venv", ".venv", "__pycache__",
            "dist", "build", "target", ".tox", ".mypy_cache",
            ".ruff_cache", ".pytest_cache", "htmlcov", ".coverage",
            ".codebase_index", ".codebase_indices", ".codebase_models",
            ".zed", ".idea", ".vscode", "out",
        }
        return dir_name in skip_dirs

    # ── PageRank ──────────────────────────────────────────

    def compute_repo_rank(self, damping: float = 0.85, iterations: int = 20) -> Dict[str, float]:
        """PageRank на PropertyGraph (через SQL-запросы)."""
        with self._lock:
            stats = self._graph.get_node_stats()
            func_count = stats.get(NodeLabel.FUNCTION, 0) + stats.get(NodeLabel.METHOD, 0)
            if func_count == 0:
                return {}

            # Читаем все CALLS рёбра из графа
            conn = self._graph._get_conn()
            rows = conn.execute(
                """SELECT src.qualified_name AS caller, dst.qualified_name AS callee
                   FROM edges e
                   JOIN nodes src ON e.source_id = src.id
                   JOIN nodes dst ON e.target_id = dst.id
                   WHERE e.type IN ('CALLS', 'ASYNC_CALLS')"""
            ).fetchall()

            # Собираем все узлы с CALLS
            all_symbols: Set[str] = set()
            outgoing: Dict[str, List[str]] = defaultdict(list)
            incoming: Dict[str, List[str]] = defaultdict(list)

            for row in rows:
                caller = row["caller"]
                callee = row["callee"]
                all_symbols.add(caller)
                all_symbols.add(callee)
                outgoing[caller].append(callee)
                incoming[callee].append(caller)

            if not all_symbols:
                return {}

            n = len(all_symbols)
            scores = {sym: 1.0 / n for sym in all_symbols}

            for _ in range(iterations):
                new_scores = {}
                for sym in all_symbols:
                    rank_sum = 0.0
                    for caller in incoming.get(sym, []):
                        out_degree = len(outgoing.get(caller, []))
                        if out_degree > 0:
                            rank_sum += scores[caller] / out_degree
                    new_scores[sym] = (1 - damping) / n + damping * rank_sum
                scores = new_scores

            if scores:
                max_score = max(scores.values())
                if max_score > 0:
                    scores = {k: v / max_score for k, v in scores.items()}

            return scores

    # ── Repo Map ──────────────────────────────────────────

    def get_repo_map(self, project_root: str) -> Dict:
        """Карта репозитория из PropertyGraph."""
        Path(project_root).resolve().as_posix()

        # Читаем все File nodes
        file_nodes = self._graph.find_nodes(label=NodeLabel.FILE, limit=10000)

        symbols_by_file = {}
        all_symbols = []
        dir_structure = {}

        for fn in file_nodes:
            rel_path = fn.file_path
            parts = rel_path.replace("\\", "/").split("/")

            current = dir_structure
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {"__dirs__": [], "__files__": []}
                current = current[part]

            filename = parts[-1]
            if "__files__" not in current:
                current["__files__"] = []
            current["__files__"].append(filename)

            # Символы в файле
            symbols_in_file = self._graph.find_nodes(file_path=fn.file_path, limit=500)
            file_syms = []
            for sym_node in symbols_in_file:
                if sym_node.label in (NodeLabel.FUNCTION, NodeLabel.CLASS, NodeLabel.METHOD):
                    file_syms.append({
                        "name": sym_node.name,
                        "kind": sym_node.properties.get("kind", sym_node.label.lower()),
                        "definitions": [{"line": sym_node.properties.get("line", 0),
                                         "context": sym_node.properties.get("kind", sym_node.label.lower())}],
                        "references": [],
                        "total_definitions": 1,
                        "total_references": 0,
                    })
                    all_symbols.append(sym_node.name)
            symbols_by_file[fn.file_path] = file_syms

        # Flatten structure
        def flatten_structure(node, path=""):
            items = []
            for key, value in node.items():
                if key == "__dirs__":
                    continue
                elif key == "__files__":
                    for filename in value:
                        items.append({"type": "file", "name": filename,
                                      "path": f"{path}/{filename}" if path else filename})
                else:
                    dir_path = f"{path}/{key}" if path else key
                    items.append({"type": "directory", "name": key, "path": dir_path})
                    items.extend(flatten_structure(value, dir_path))
            return items

        structure = flatten_structure(dir_structure)

        return {
            "structure": structure,
            "symbols_by_file": symbols_by_file,
            "all_symbols": list(set(all_symbols)),
            "total_files": len(file_nodes),
            "total_symbols": len(all_symbols),
        }

    # ── Write Tools Support ───────────────────────────────

    def find_all_references(self, symbol_name: str, kind: str = "") -> List[SymbolRef]:
        """Cross-file reference search."""
        nodes = self._graph.find_nodes(name_pattern=symbol_name, limit=50)
        result = []

        # Definitions first
        for n in nodes:
            node_kind = n.properties.get("kind", "")
            if not kind or node_kind == kind:
                result.append(SymbolRef(
                    symbol=n.name, file_path=n.file_path,
                    line=n.properties.get("line", 0),
                    kind=node_kind, is_definition=True,
                ))

        # Callers
        for n in nodes:
            for neighbor, edge, _depth in self._graph.get_neighbors(
                n.qualified_name, edge_type=EdgeType.CALLS, direction="incoming"
            ):
                result.append(SymbolRef(
                    symbol=neighbor.name, file_path=neighbor.file_path,
                    line=edge.properties.get("line", 0),
                    kind="call", is_definition=False,
                ))

        return result if result else self._hybrid_find_all_references(symbol_name, kind)

    def _hybrid_find_all_references(self, symbol_name: str, kind: str = "") -> List[SymbolRef]:
        with self._lock:
            result: List[SymbolRef] = []
            defs = self._definitions.get(symbol_name, [])
            for d in defs:
                if not kind or d.kind == kind:
                    result.append(d)
            refs = self._references.get(symbol_name, [])
            for r in refs:
                if not r.is_definition and (not kind or r.kind == kind):
                    if r.symbol == symbol_name:
                        result.append(r)
            return result

    def rename_symbol(self, old_name: str, new_name: str) -> int:
        """Rename symbol в PropertyGraph + HYBRID."""
        count = 0
        with self._lock:
            nodes = self._graph.find_nodes(name_pattern=old_name, limit=100)
            for n in nodes:
                if n.name == old_name:
                    new_qname = n.qualified_name.replace(f".{old_name}", f".{new_name}")
                    self._graph.add_node(
                        name=new_name, label=n.label, qualified_name=new_qname,
                        file_path=n.file_path, properties=n.properties,
                    )
                    self._graph.delete_node(n.qualified_name)
                    count += 1

            # HYBRID
            if self._mode == self.MODE_HYBRID:
                if old_name in self._definitions:
                    refs = self._definitions.pop(old_name)
                    for r in refs:
                        r.symbol = new_name
                    self._definitions[new_name] = refs
                    count += len(refs)
                    for r in refs:
                        if r.file_path in self._file_to_defs:
                            self._file_to_defs[r.file_path].discard(old_name)
                            self._file_to_defs[r.file_path].add(new_name)

                if old_name in self._references:
                    refs = self._references.pop(old_name)
                    for r in refs:
                        r.symbol = new_name
                    self._references[new_name] = refs
                    count += len(refs)
                    for r in refs:
                        if r.file_path in self._file_to_calls:
                            self._file_to_calls[r.file_path].discard(old_name)
                            self._file_to_calls[r.file_path].add(new_name)

                for file_path in list(self._file_to_symbols.keys()):
                    symbols = self._file_to_symbols[file_path]
                    if old_name in symbols:
                        symbols.discard(old_name)
                        symbols.add(new_name)

        return count

    def remap_file(self, old_path: str, new_path: str) -> int:
        """Remap file path в PropertyGraph."""
        old_norm = Path(old_path).resolve().as_posix()
        new_norm = Path(new_path).resolve().as_posix()
        if old_norm == new_norm:
            return 0

        count = 0
        with self._lock:
            nodes = self._graph.find_nodes(file_path=old_norm, limit=10000)
            for n in nodes:
                new_qname = n.qualified_name.replace(old_norm, new_norm)
                self._graph.add_node(
                    name=n.name, label=n.label, qualified_name=new_qname,
                    file_path=new_norm, properties=n.properties,
                )
                self._graph.delete_node(n.qualified_name)
                count += 1

            # HYBRID
            if self._mode == self.MODE_HYBRID:
                if old_norm in self._file_to_symbols:
                    self._file_to_symbols[new_norm] = self._file_to_symbols.pop(old_norm)
                    count += len(self._file_to_symbols[new_norm])
                if old_norm in self._file_to_defs:
                    self._file_to_defs[new_norm] = self._file_to_defs.pop(old_norm)
                if old_norm in self._file_to_calls:
                    self._file_to_calls[new_norm] = self._file_to_calls.pop(old_norm)
                for sym, refs in self._definitions.items():
                    for ref in refs:
                        if ref.file_path == old_norm:
                            ref.file_path = new_norm
                            count += 1
                for sym, refs in self._references.items():
                    for ref in refs:
                        if ref.file_path == old_norm:
                            ref.file_path = new_norm
                            count += 1

        logger.debug(f"♻️ SymbolIndexAdapter remap: {old_norm} -> {new_norm} ({count} entries)")
        return count

    def has_symbol(self, symbol_name: str) -> bool:
        """Quick existence check."""
        nodes = self._graph.find_nodes(name_pattern=symbol_name, limit=1)
        if nodes:
            return True
        with self._lock:
            return symbol_name in self._definitions or symbol_name in self._references

    # ── Helpers ───────────────────────────────────────────

    @staticmethod
    def _get_project_name(file_path: str) -> str:
        """Извлекает имя проекта из пути."""
        parts = file_path.replace("\\", "/").split("/")
        for p in parts:
            if p and p != "src" and "." not in p:
                return p
        return "unknown"


# ════════════════════════════════════════════════════════════
# GraphRAGAdapter — PropertyGraph → GraphRAGQueryEngine
# ════════════════════════════════════════════════════════════

class GraphRAGAdapter:
    """
    Адаптер PropertyGraph → интерфейс GraphRAGQueryEngine.

    Оборачивает PropertyGraph + SymbolIndexAdapter в интерфейс
    query_impact / query_feature / query_dependencies / query_tests.
    """

    def __init__(
        self,
        project_path: Path,
        graph: PropertyGraph,
        symbol_adapter: SymbolIndexAdapter,
        commit_memory=None,
    ):
        self.project_path = project_path
        self._graph = graph
        self._symbol_adapter = symbol_adapter
        self.commit_memory = commit_memory

    def query_impact(self, symbol_name: str, depth: int = 2) -> Dict:
        """Анализ влияния изменения символа."""
        result = {
            "symbol": symbol_name,
            "direct_impact": [],
            "transitive_impact": [],
            "tests_to_run": [],
            "risk_score": 0,
        }

        try:
            impact = self._symbol_adapter.get_impact_analysis(symbol_name, depth=depth)
            result["direct_impact"] = impact.get("affected_files", [])[:10]
            result["transitive_impact"] = impact.get("affected_files", [])[10:]
            result["risk_score"] = impact.get("risk_score", 0)
            result["tests_to_run"] = self._find_related_tests(result["direct_impact"])
        except Exception as e:
            logger.error(f"Impact query failed: {e}")

        return result

    def query_feature(self, feature_name: str) -> Dict:
        """Находит код, связанный с фичей."""
        result = {"feature": feature_name, "files": [], "symbols": [], "related_commits": []}

        try:
            symbols = self._symbol_adapter.search_symbols(feature_name)
            result["symbols"] = symbols[:20]
            for sym_info in symbols[:10]:
                file_path = getattr(sym_info, "file_path", None) or sym_info.file_path
                if file_path and file_path not in result["files"]:
                    result["files"].append(file_path)
        except Exception as e:
            logger.warning(f"Symbol search failed: {e}")

        if self.commit_memory:
            try:
                commits = self.commit_memory.search_commits(feature_name)
                result["related_commits"] = [
                    {"hash": c.get("hash", "")[:8], "message": c.get("message", "")}
                    for c in commits[:5]
                ]
            except Exception as e:
                logger.warning(f"Commit search failed: {e}")

        return result

    def query_dependencies(self, file_path: str, direction: str = "both") -> Dict:
        """Находит зависимости файла."""
        result = {
            "file": file_path,
            "depends_on": [],
            "depended_by": [],
            "cochange_files": [],
        }

        file_path = Path(file_path).resolve().as_posix()
        try:
            nodes = self._graph.find_nodes(file_path=file_path)
            depends_on = set()
            depended_by = set()

            for node in nodes:
                # Outgoing CALLS → depends_on
                for neighbor, edge, _depth in self._graph.get_neighbors(
                    node.qualified_name, edge_type=EdgeType.CALLS, direction="outgoing"
                ):
                    if neighbor.file_path and neighbor.file_path != file_path:
                        depends_on.add(neighbor.file_path)

                # Incoming CALLS → depended_by
                for neighbor, edge, _depth in self._graph.get_neighbors(
                    node.qualified_name, edge_type=EdgeType.CALLS, direction="incoming"
                ):
                    if neighbor.file_path and neighbor.file_path != file_path:
                        depended_by.add(neighbor.file_path)

            result["depends_on"] = list(depends_on)[:10]
            result["depended_by"] = list(depended_by)[:10]

        except Exception as e:
            logger.error(f"Dependency query failed: {e}")

        return result

    def query_tests(self, file_path: str) -> List[str]:
        """Находит тесты, связанные с файлом."""
        return self._find_related_tests([file_path])

    def _find_related_tests(self, file_paths: List[str]) -> List[str]:
        """Находит тесты для списка файлов."""
        tests = []
        test_dir = self.project_path / "tests"
        if not test_dir.exists():
            return tests

        for fpath in file_paths:
            stem = Path(fpath).stem
            for test_file in test_dir.glob("test_*.py"):
                if stem in test_file.name:
                    tests.append(str(test_file.relative_to(self.project_path)))

        return list(set(tests))[:10]

    def query_hotspots(self, min_changes: int = 3) -> List[Dict]:
        """Горячие точки из commit_memory."""
        if not self.commit_memory:
            return []
        try:
            return self.commit_memory.get_hotspots(min_changes=min_changes)
        except Exception as e:
            logger.error(f"Hotspots query failed: {e}")
            return []

    def query_similar_bugs(self, error_message: str) -> List[Dict]:
        """Поиск похожих багов."""
        if not self.commit_memory:
            return []
        try:
            return self.commit_memory.find_similar_bugs(error_message)
        except Exception as e:
            logger.error(f"Similar bugs query failed: {e}")
            return []


# ════════════════════════════════════════════════════════════
# CompositionAdapter — единая точка входа
# ════════════════════════════════════════════════════════════

class CompositionAdapter:
    """
    Композиционный адаптер — заменяет все три исходных сервиса одним.

    Использование:
        adapter = CompositionAdapter(project_root, graph_db_path)
        adapter.index_project(...)  # → SymbolIndexAdapter
        adapter.query_impact(...)   # → GraphRAGAdapter
        adapter.extract_relations() # → RelationExtractor (прямой вызов)
    """

    def __init__(
        self,
        project_path: Path,
        graph_db_path: Optional[Path] = None,
        commit_memory=None,
        mode: str = SymbolIndexAdapter.MODE_HYBRID,
    ):
        if graph_db_path is None:
            graph_db_path = project_path / ".codebase" / "graph.db"

        self._graph = PropertyGraph(graph_db_path)
        self._symbol_adapter = SymbolIndexAdapter(self._graph, mode=mode)
        self._graph_rag = GraphRAGAdapter(
            project_path, self._graph, self._symbol_adapter, commit_memory
        )

    @property
    def graph(self) -> PropertyGraph:
        return self._graph

    @property
    def symbol_index(self) -> SymbolIndexAdapter:
        return self._symbol_adapter

    @property
    def graph_rag(self) -> GraphRAGAdapter:
        return self._graph_rag

    # Делегирование SymbolIndex
    def add_definitions(self, file_path: str, symbols: List[Dict]) -> None:
        self._symbol_adapter.add_definitions(file_path, symbols)

    def add_references(self, file_path: str, calls: List[Dict]) -> None:
        self._symbol_adapter.add_references(file_path, calls)

    def remove_file(self, file_path: str) -> None:
        self._symbol_adapter.remove_file(file_path)

    def get_call_chain(self, symbol: str, direction: str = "both", max_depth: int = 3) -> Dict:
        return self._symbol_adapter.get_call_chain(symbol, direction, max_depth)

    def search_symbols(self, query: str, top_k: int = 10) -> List[SymbolRef]:
        return self._symbol_adapter.search_symbols(query, top_k)

    def get_impact_analysis(self, symbol: str, depth: int = 3) -> Dict:
        return self._symbol_adapter.get_impact_analysis(symbol, depth)

    def detect_dead_code(self) -> List[Node]:
        return self._graph.detect_dead_code()

    def get_graph_summary(self) -> Dict:
        return self._graph.get_graph_summary()

    def close(self):
        self._graph.close()


__all__ = [
    "SymbolIndexAdapter",
    "GraphRAGAdapter",
    "CompositionAdapter",
]
