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
                # walk (TARGET_NODES) + SCM (tags.scm): функции
                "function_definition": NodeLabel.FUNCTION,
                "async_function_definition": NodeLabel.FUNCTION,
                "function_declaration": NodeLabel.FUNCTION,
                "function_item": NodeLabel.FUNCTION,
                "function_expression": NodeLabel.FUNCTION,
                "arrow_function": NodeLabel.FUNCTION,
                "macro_definition": NodeLabel.FUNCTION,
                "decorated_definition": NodeLabel.FUNCTION,
                "function": NodeLabel.FUNCTION,
                # методы
                "method_definition": NodeLabel.METHOD,
                "method_declaration": NodeLabel.METHOD,
                "method": NodeLabel.METHOD,
                # классы и им подобные контейнеры
                "class_definition": NodeLabel.CLASS,
                "class_declaration": NodeLabel.CLASS,
                "class_expression": NodeLabel.CLASS,
                "class": NodeLabel.CLASS,
                "struct_item": NodeLabel.CLASS,
                "struct_declaration": NodeLabel.CLASS,
                "object_declaration": NodeLabel.CLASS,  # Kotlin/Scala object
                # интерфейсы
                "interface_declaration": NodeLabel.INTERFACE,
                "interface": NodeLabel.INTERFACE,
                "trait_item": NodeLabel.INTERFACE,  # Rust
                "trait_declaration": NodeLabel.INTERFACE,  # PHP/Scala
                "protocol_declaration": NodeLabel.INTERFACE,  # Swift
                # enum / type
                "enum_item": NodeLabel.ENUM,
                "enum_declaration": NodeLabel.ENUM,
                "enum": NodeLabel.ENUM,
                "type_alias_declaration": NodeLabel.TYPE,
                "type": NodeLabel.TYPE,
                # свойства/поля (C#/Kotlin property из tags.scm)
                "property_declaration": NodeLabel.VARIABLE,
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
                properties={
                    "line": line,
                    "kind": kind,
                    "confidence": "EXTRACTED",
                    "evidence": f"{file_path}:{line}",
                },
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
            if not callee_nodes:
                # Методы хранятся с qualified name ("Class.method") —
                # точный LIKE по голому имени не находит их, и каждая
                # ссылка на метод превращалась в __extern__ заглушку.
                # Suffix-поиск резолвит методы в реальные узлы.
                callee_nodes = self._graph.find_nodes(
                    name_pattern=f"%.{callee}",
                    limit=5,
                )
            if callee_nodes:
                for cn in callee_nodes:
                    self._graph.add_edge(
                        source_qname=caller_qname,
                        target_qname=cn.qualified_name,
                        type=EdgeType.CALLS,
                        weight=1.0,
                        properties={
                            "line": line,
                            "file": file_path,
                            "confidence": "EXTRACTED",
                            "evidence": f"{file_path}:{line}",
                        },
                    )
            else:
                # callee ещё не проиндексирован — создаём placeholder
                callee_qname = f"{project_name}.__extern__.{callee}"
                self._graph.add_node(
                    name=callee,
                    label=NodeLabel.FUNCTION,
                    qualified_name=callee_qname,
                    file_path=file_path,
                    properties={
                        "line": line,
                        "file": file_path,
                        "placeholder": True,
                        "caller_node_id": caller_qname,
                        "line_number": line,
                        "raw_symbol_name": callee,
                    },
                )
                self._graph.add_edge(
                    source_qname=caller_qname,
                    target_qname=callee_qname,
                    type=EdgeType.CALLS,
                    weight=1.0,
                    properties={
                        "line": line,
                        "file": file_path,
                        "confidence": "EXTRACTED",
                        "evidence": f"{file_path}:{line}",
                    },
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

    # ── Imports ───────────────────────────────────────────

    def _pure_add_imports(self, file_path: str, imports: List[Dict]) -> None:
        """PropertyGraph контур: IMPORTS рёбра между File узлами.

        Каждый импорт создаёт ребро:
        (File:source) --[IMPORTS]--> (Module:target)

        Вызывается из SymbolIndexAdapter.add_imports() под self._lock.
        """
        project_name = self._get_project_name(file_path)
        file_qname = f"{project_name}.{file_path}"

        for imp in imports:
            target = imp.get("target_module", "")
            if not target:
                continue
            line = imp.get("line", 0)

            # Создаём или находим Module-узел для импортируемого модуля
            target_qname = f"{project_name}.__import__.{target}"
            if not self._graph.get_node(target_qname):
                self._graph.add_node(
                    name=target,
                    label=NodeLabel.MODULE,
                    qualified_name=target_qname,
                    file_path=file_path,
                    properties={"line": line, "imported": True},
                )

            # IMPORTS ребро: source_file -> target_module
            if self._graph.get_node(file_qname):
                self._graph.add_edge(
                    source_qname=file_qname,
                    target_qname=target_qname,
                    type=EdgeType.IMPORTS,
                    weight=1.0,
                    properties={
                        "line": line,
                        "text": imp.get("text", ""),
                        "confidence": "EXTRACTED",
                        "evidence": f"{file_path}:{line}",
                    },
                )

    # ── Decorators (DECORATES) ─────────────────────────────

    def _pure_add_decorators(self, file_path: str, decorators: List[Dict]) -> None:
        """PropertyGraph контур: DECORATES рёбра (декоратор → декорируемый символ).

        Декоратор представлен TYPE-узлом ("__decorator__.<имя>"), ребро идёт
        от декоратора к символу: (TYPE:property) --[DECORATES]--> (Function:get).
        Ребро создаётся только если декорируемый символ реально определён
        в графе (add_definitions уже отработал для этого файла).

        Вызывается из SymbolIndexAdapter.add_decorators() под self._lock.
        """
        project_name = self._get_project_name(file_path)

        for d in decorators:
            decorated = d.get("decorated", "")
            deco = d.get("decorator", "")
            line = d.get("line", 0)
            if not decorated or not deco:
                continue

            decorated_qname = f"{project_name}.{file_path}.{decorated}"
            deco_qname = f"{project_name}.__decorator__.{deco}"

            if not self._graph.get_node(deco_qname):
                self._graph.add_node(
                    name=deco,
                    label=NodeLabel.TYPE,
                    qualified_name=deco_qname,
                    properties={"line": line, "file": file_path, "decorator": True},
                )

            if self._graph.get_node(decorated_qname):
                self._graph.add_edge(
                    source_qname=deco_qname,
                    target_qname=decorated_qname,
                    type=EdgeType.DECORATES,
                    weight=1.0,
                    properties={
                        "line": line,
                        "file": file_path,
                        "confidence": "EXTRACTED",
                        "evidence": f"{file_path}:{line}",
                    },
                )

    # ── Overrides (OVERRIDES) ──────────────────────────────

    def _pure_add_overrides(self, file_path: str, overrides: List[Dict]) -> None:
        """PropertyGraph контур: OVERRIDES рёбра (Child.m → Base.m).

        Оба узла (переопределяющий и переопределяемый метод) — реальные
        Method-узлы того же файла; ребро создаётся только если оба существуют
        (add_definitions уже отработал). Same-file ограничение v1.

        Вызывается из SymbolIndexAdapter.add_overrides() под self._lock.
        """
        project_name = self._get_project_name(file_path)

        for ov in overrides:
            override = ov.get("override", "")
            overridden = ov.get("overridden", "")
            line = ov.get("line", 0)
            if not override or not overridden:
                continue

            src_qname = f"{project_name}.{file_path}.{override}"
            tgt_qname = f"{project_name}.{file_path}.{overridden}"

            if self._graph.get_node(src_qname) and self._graph.get_node(tgt_qname):
                self._graph.add_edge(
                    source_qname=src_qname,
                    target_qname=tgt_qname,
                    type=EdgeType.OVERRIDES,
                    weight=1.0,
                    properties={
                        "line": line,
                        "file": file_path,
                        "base": ov.get("base", ""),
                        "method": ov.get("method", ""),
                        "confidence": "EXTRACTED",
                        "evidence": f"{file_path}:{line}",
                    },
                )

    # ── Call Chain ────────────────────────────────────────

    def _graph_call_chain(self, node: Node, direction: str, max_depth: int,
                          extra_starts=None) -> Dict:
        """Call chain из PropertyGraph.

        extra_starts: qname'ы одноимённых узлов (real + extern-placeholder) —
        CALLS-рёбра при индексации могут уйти на любой из них в зависимости
        от порядка файлов; объединяем входящие/исходящие по всем (D1-D3).
        """
        result = {
            "symbol": node.name,
            "callers_chain": [],
            "callees_chain": [],
            "total_connected": 0,
        }
        starts = [node.qualified_name]
        if extra_starts:
            starts = list(dict.fromkeys([node.qualified_name] + list(extra_starts)))

        if direction in ("up", "both"):
            for qname in starts:
                for neighbor, edge, depth in self._graph.get_neighbors(
                    qname, edge_type=EdgeType.CALLS,
                    direction="incoming", max_depth=max_depth,
                ):
                    if neighbor.qualified_name == node.qualified_name:
                        continue
                    if self._is_one_off_script(neighbor.file_path):
                        continue
                    result["callers_chain"].append({
                        "symbol": neighbor.name, "file": neighbor.file_path,
                        "line": edge.properties.get("line", 0), "depth": depth,
                    })

        if direction in ("down", "both"):
            for qname in starts:
                for neighbor, edge, depth in self._graph.get_neighbors(
                    qname, edge_type=EdgeType.CALLS,
                    direction="outgoing", max_depth=max_depth,
                ):
                    if neighbor.qualified_name == node.qualified_name:
                        continue
                    result["callees_chain"].append({
                        "symbol": neighbor.name, "file": neighbor.file_path,
                        "line": edge.properties.get("line", 0), "depth": depth,
                    })

        result["total_connected"] = len(result["callers_chain"]) + len(result["callees_chain"])
        return result

    def _find_nodes_flexible(self, symbol: str, limit: int) -> List[Node]:
        """Находит узлы по символу: точное имя + qualified-name suffix (union).

        PropertyGraph хранит методы с qualified name ("Class.method"), а
        вызовы/поиски приходят с голым именем ("method"). Точный LIKE
        (name LIKE 'method') не матчит "Class.method", поэтому объединяем
        exact и suffix "%.method" — покрывает оба случая (D1-D3: иначе тень
        experiments/ в exact-выборке исключала src/ метод из суффикса).
        """
        exact = self._graph.find_nodes(name_pattern=symbol, limit=limit)
        suffix = self._graph.find_nodes(name_pattern=f"%.{symbol}", limit=limit)
        seen = {n.qualified_name for n in exact}
        merged = list(exact)
        for n in suffix:
            if n.qualified_name not in seen:
                seen.add(n.qualified_name)
                merged.append(n)
        return merged

    def _pick_best_node(self, nodes: List[Node], symbol: str):
        """Выбирает лучший узел-кандидат для символа (D1-D3, 2026-08-08).

        Ранжирование (в порядке убывания важности):
        - реальное определение (не placeholder, с file_path) >> placeholder (extern)
        - прод-код (src/) >> одноразовые скрипты (experiments/, scripts/)
        - точное имя (bare или qualified-suffix) >> прочие совпадения

        Без ранжирования build_call_graph/get_callers брали nodes[0] по порядку
        вставки: тень experiments/ опережала src/ (D1), placeholder с пустым
        file_path опережал реальное определение (D3).
        """
        if not nodes:
            return None
        sym = symbol

        def _rank(n: Node) -> int:
            props = n.properties or {}
            fp = (n.file_path or "").replace("\\", "/")
            score = 0
            if not props.get("placeholder") and fp:
                score += 100
            if "/src/" in fp:
                score += 50
            elif fp and ("/experiments/" in fp or "/scripts/" in fp):
                score -= 50
            if n.name == sym or n.name.endswith("." + sym):
                score += 20
            return score

        return max(nodes, key=_rank)

    def _candidate_starts(self, nodes: List[Node], best: Node) -> List[str]:
        """qname'ы для BFS по callers/callees: ВСЕ одноимённые узлы.

        CALLS-рёбра при индексации привязываются к тому узлу, который нашёлся
        первым exact-LIKE в момент обработки файла — реальные callers могут
        лежать на тени experiments//scripts/ или extern-placeholder, а не на
        src-определении. BFS по всем сохраняет их; одноразовые скрипты
        отфильтровываются на уровне записей (_is_one_off_script).
        """
        seen = {best.qualified_name}
        starts = [best.qualified_name]
        for n in nodes:
            if n.qualified_name not in seen:
                seen.add(n.qualified_name)
                starts.append(n.qualified_name)
        return starts

    @staticmethod
    def _is_one_off_script(file_path: str) -> bool:
        """True если путь — одноразовый скрипт (experiments/, scripts/).

        Такие файлы — бенчмарки/эксперименты (§0.6), их callers не являются
        прод-потребителями и не должны попадать в get_symbol_info/impact.
        """
        fp = (file_path or "").replace("\\", "/")
        return "/experiments/" in fp or "/scripts/" in fp

    def get_call_chain(self, symbol: str, direction: str = "both", max_depth: int = 3) -> Dict:
        """Цепочка вызовов: кто вызывает (up) / кого вызывает (down).

        Использует PropertyGraph.get_neighbors с BFS.
        """
        nodes = self._find_nodes_flexible(symbol, limit=20)
        node = self._pick_best_node(nodes, symbol)
        if node is not None:
            starts = self._candidate_starts(nodes, node)
            return self._graph_call_chain(node, direction, max_depth, starts)

        # HYBRID fallback
        with self._lock:
            return self._hybrid_call_chain(symbol, direction, max_depth)

    # ── Поиск ─────────────────────────────────────────────

    def find_definitions(self, symbol: str) -> List[SymbolRef]:
        """Где определён символ.

        Сначала PropertyGraph, fallback на in-memory HYBRID.
        """
        # Пробуем через PropertyGraph
        nodes = self._find_nodes_flexible(symbol, limit=20)
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
        nodes = self._find_nodes_flexible(symbol, limit=5)
        if nodes:
            # Один и тот же caller может быть найден через несколько узлов
            # (интерфейс + реализация метода) — дедуплицируем по (символ, файл, строка),
            # чтобы рендер '🔗 Вызывается из:' не дублировал один вызов.
            refs: List[SymbolRef] = []
            seen: set = set()
            for n in nodes:
                neighbors = self._graph.get_neighbors(
                    n.qualified_name, edge_type=EdgeType.CALLS, direction="incoming",
                )
                for neighbor, edge, _depth in neighbors:
                    ref = SymbolRef(
                        symbol=neighbor.name,
                        file_path=edge.properties.get("file", neighbor.file_path),
                        line=edge.properties.get("line", 0),
                        kind="call",
                        is_definition=False,
                    )
                    key = (ref.symbol, ref.file_path, ref.line)
                    if key not in seen:
                        seen.add(key)
                        refs.append(ref)
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
