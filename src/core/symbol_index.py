"""
Symbol Index — отслеживание определений и использований символов между файлами.
"""

import logging
import os
import re
import threading
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)


# Типы символов, которые мы отслеживаем
SYMBOL_KINDS = {"function", "class", "method", "variable_exported"}


class SymbolRef:
    """Одно вхождение символа: определение или использование."""

    __slots__ = ("symbol", "file_path", "line", "kind", "is_definition")

    def __init__(
        self,
        symbol: str,
        file_path: str,
        line: int,
        kind: str,
        is_definition: bool = False,
    ):
        self.symbol = symbol
        self.file_path = file_path
        self.line = line
        self.kind = kind
        self.is_definition = is_definition

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "file": self.file_path,
            "line": self.line,
            "kind": self.kind,
            "is_def": self.is_definition,
        }


class SymbolIndex:
    """
    Индекс символов проекта.
    Хранит: какой файл определяет символ, какие файлы его используют.
    Поддерживает построение графа вызовов (Call Graph).
    """

    def __init__(self):
        self._lock = threading.RLock()
        # symbol -> list of SymbolRef
        self._definitions: Dict[str, List[SymbolRef]] = {}
        self._references: Dict[str, List[SymbolRef]] = {}
        # file_path -> set of symbols (быстрый lookup при удалении файла)
        self._file_to_symbols: Dict[str, Set[str]] = {}
        # file_path -> set of symbol names defined in this file
        self._file_to_defs: Dict[str, Set[str]] = {}
        # file_path -> set of symbol names called/used in this file
        self._file_to_calls: Dict[str, Set[str]] = {}

        # Регулярка для поиска идентификаторов в тексте
        self._id_pattern = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

    # --- Импорт из парсера ---

    def add_definitions(self, file_path: str, symbols: List[Dict]) -> None:
        """
        Добавляет определения символов из распаршенного файла.
        symbols: список {name, line, kind} от парсера.
        """
        from pathlib import Path

        # Нормализуем путь для единообразия (Windows -> POSIX)
        file_path = Path(file_path).resolve().as_posix()

        with self._lock:
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
                # Не дублируем одно и то же определение
                existing = {
                    r.line for r in self._definitions[name] if r.file_path == file_path
                }
                if sym["line"] not in existing:
                    self._definitions[name].append(ref)
                self._file_to_symbols[file_path].add(name)

            self._file_to_defs[file_path] = defined_names

    def add_references(self, file_path: str, calls: List[Dict]) -> None:
        """
        Добавляет связи вызовов (references) из распаршенного файла.

        calls: список {caller, callee, line, file} от parser.extract_calls().
        Строит двунаправленный граф: caller → callee (прямые связи)
        и callee ← caller (обратные связи для поиска callers).

        Args:
            file_path: Путь к файлу (относительный)
            calls: Список вызовов функций
        """
        from pathlib import Path

        # Нормализуем путь для единообразия
        file_path = Path(file_path).resolve().as_posix()

        with self._lock:
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

                # Прямая связь: caller вызывает callee
                # Добавляем callee в список вызываемых символов caller
                if callee not in self._references:
                    self._references[callee] = []

                # Не дублируем одну и ту же связь
                existing = {
                    (r.file_path, r.line)
                    for r in self._references[callee]
                    if r.symbol == caller
                }
                if (file_path, line) not in existing:
                    self._references[callee].append(
                        SymbolRef(
                            symbol=caller,
                            file_path=file_path,
                            line=line,
                            kind="call",
                            is_definition=False,
                        )
                    )

                # Обратная связь: caller вызывает callee
                # Добавляем callee в список вызовов файла
                self._file_to_calls[file_path].add(callee)
                self._file_to_symbols[file_path].add(caller)
                self._file_to_symbols[file_path].add(callee)

                # ВНИМАНИЕ: caller НЕ добавляется в _definitions здесь,
                # так как это создаёт фантомные пустые записи.
                # Дефинишены добавляются ТОЛЬКО через add_definitions.

    def remove_file(self, file_path: str) -> None:
        """Удаляет все записи о файле (при удалении/переиндексации)."""
        from pathlib import Path

        # Нормализуем путь для единообразия
        file_path = Path(file_path).resolve().as_posix()

        with self._lock:
            symbols = self._file_to_symbols.pop(file_path, set())
            self._file_to_defs.pop(file_path, None)
            self._file_to_calls.pop(file_path, None)
            for sym in symbols:
                # Удаляем определения
                if sym in self._definitions:
                    self._definitions[sym] = [
                        r for r in self._definitions[sym] if r.file_path != file_path
                    ]
                    if not self._definitions[sym]:
                        del self._definitions[sym]

                # Удаляем использования
                if sym in self._references:
                    self._references[sym] = [
                        r for r in self._references[sym] if r.file_path != file_path
                    ]
                    if not self._references[sym]:
                        del self._references[sym]

    # --- Поиск ---

    def find_definitions(self, symbol: str) -> List[SymbolRef]:
        """Где определён символ (файл + строка)."""
        with self._lock:
            return list(self._definitions.get(symbol, []))

    def find_references(self, symbol: str) -> List[SymbolRef]:
        """Где используется символ."""
        with self._lock:
            return list(self._references.get(symbol, []))

    def get_symbols_in_file(self, file_path: str) -> List[str]:
        """Возвращает список имён символов, определённых в файле.

        Args:
            file_path: Путь к файлу

        Returns:
            Список имён символов (уникальные)
        """
        from pathlib import Path

        file_path = Path(file_path).resolve().as_posix()

        with self._lock:
            return list(self._file_to_defs.get(file_path, set()))

    def get_symbol_context(self, symbol: str) -> Dict:
        """
        Возвращает контекст символа для обогащения результатов поиска.
        Включает определения, вызовы и граф вызовов.
        """
        with self._lock:
            defs = self._definitions.get(symbol, [])
            refs = self._references.get(symbol, [])

            if not defs and not refs:
                return {}

            unique_files_using = set(r.file_path for r in refs if not r.is_definition)

            # Находим callees (кого вызывает этот символ)
            callees = []
            for callee_sym, callee_refs in self._references.items():
                for ref in callee_refs:
                    if ref.symbol == symbol and not ref.is_definition:
                        callees.append(
                            {
                                "symbol": callee_sym,
                                "file": ref.file_path,
                                "line": ref.line,
                            }
                        )

            return {
                "symbol": symbol,
                "defined_in": [
                    {"file": d.file_path, "line": d.line, "kind": d.kind} for d in defs
                ],
                "used_in_count": len(unique_files_using),
                "used_in_files": list(unique_files_using)[:10],  # топ-10
                "calls_count": len(callees),
                "calls": callees[:10],  # топ-10 вызовов
            }

    def get_call_chain(
        self, symbol: str, direction: str = "both", max_depth: int = 3
    ) -> Dict:
        """Возвращает цепочку вызовов для символа.

        Args:
            symbol: Имя символа
            direction: 'up' (callers), 'down' (callees), 'both'
            max_depth: Максимальная глубина обхода

        Returns:
            {
                'symbol': str,
                'callers_chain': [...],  # Кто вызывает (вверх по стеку)
                'callees_chain': [...],  # Кого вызывает (вниз по стеку)
                'total_connected': int,  # Всего связанных символов
            }
        """
        with self._lock:
            result = {
                "symbol": symbol,
                "callers_chain": [],
                "callees_chain": [],
                "total_connected": 0,
            }

            visited: Set[str] = set()

            # Callers (вверх — кто вызывает)
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
                                    {
                                        "symbol": r.symbol,
                                        "file": r.file_path,
                                        "line": r.line,
                                        "depth": d + 1,
                                    }
                                )
                                next_level.add(r.symbol)
                    current_level = next_level
                    if not current_level:
                        break

            # Callees (вниз — кого вызывает)
            if direction in ("down", "both"):
                current_level = {symbol}
                visited_callees: Set[str] = set()
                for d in range(max_depth):
                    next_level = set()
                    for sym in current_level:
                        if sym in visited_callees:
                            continue
                        visited_callees.add(sym)
                        # Ищем все callee для sym
                        for callee_sym, callee_refs in self._references.items():
                            if callee_sym in visited_callees:
                                continue
                            for ref in callee_refs:
                                if ref.symbol == sym and not ref.is_definition:
                                    result["callees_chain"].append(
                                        {
                                            "symbol": callee_sym,
                                            "file": ref.file_path,
                                            "line": ref.line,
                                            "depth": d + 1,
                                        }
                                    )
                                    next_level.add(callee_sym)
                    current_level = next_level
                    if not current_level:
                        break

            result["total_connected"] = len(result["callers_chain"]) + len(
                result["callees_chain"]
            )
            return result

    def search_symbols(self, query: str, top_k: int = 10) -> List[SymbolRef]:
        """
        Поиск символов по имени (частичное совпадение).
        Возвращает плоский список SymbolRef (определения + использования),
        отсортированный по популярности символа.
        """
        query_lower = query.lower()
        scored: List[Tuple[int, str]] = []

        with self._lock:
            for name in self._definitions:
                if query_lower in name.lower():
                    refs = self._references.get(name, [])
                    unique_users = len(set(r.file_path for r in refs))
                    scored.append((unique_users, name))

        # Сортируем по популярности
        scored.sort(key=lambda x: -x[0])

        results: List[SymbolRef] = []
        for _, name in scored[:top_k]:
            with self._lock:
                defs = self._definitions.get(name, [])
                refs = self._references.get(name, [])
            results.extend(defs)
            results.extend(refs)

        return results

    # --- Граф вызовов (Call Graph) ---

    def build_call_graph(self, symbol: str, depth: int = 2) -> Dict:
        """Строит двунаправленный граф вызовов для символа с заданной глубиной.

        Алгоритм BFS (breadth-first search):
        - Уровень 0: сам символ + его определения
        - Уровень 1: прямые callers (кто вызывает) + callees (кого вызывает)
        - Уровень 2+: рекурсивно расширяем граф на прямых соседей

        Возвращает:
        - definition: где определён символ
        - callers: кто вызывает этот символ (обратные связи)
        - callees: какие символы вызывает этот символ (прямые связи)
        - call_chain: цепочка вызовов для контекста
        - impact_files: файлы, которые затронет изменение символа
        - depth_reached: фактическая глубина обхода
        """
        with self._lock:
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
                depth = 5  # Защита от слишком глубокого обхода

            # Множество обработанных символов для избежания циклов
            visited_callers: Set[str] = set()
            visited_callees: Set[str] = set()

            # 1. Определение символа
            defs = self._definitions.get(symbol, [])
            for d in defs:
                result["definition"].append(
                    {
                        "file": d.file_path,
                        "line": d.line,
                        "kind": d.kind,
                    }
                )
                result["impact_files"].add(d.file_path)

            # 2. BFS для callers (кто вызывает этот символ)
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

                        caller_entry = {
                            "symbol": caller_sym,
                            "file": r.file_path,
                            "line": r.line,
                            "kind": r.kind,
                            "depth": level + 1,
                        }
                        # Дедупликация
                        if not any(
                            c.get("symbol") == caller_sym
                            and c.get("file") == r.file_path
                            for c in result["callers"]
                        ):
                            result["callers"].append(caller_entry)
                            result["impact_files"].add(r.file_path)
                            next_level_callers.add(caller_sym)

                current_level_callers = next_level_callers
                if not current_level_callers:
                    break
                result["depth_reached"] = level + 1

            # 3. BFS для callees (кого вызывает этот символ)
            current_level_callees = {symbol}
            for level in range(depth):
                next_level_callees = set()
                for sym in current_level_callees:
                    if sym in visited_callees:
                        continue
                    visited_callees.add(sym)

                    # Ищем все символы, которые вызывает sym
                    # Для этого ищем в _references записи где sym является caller
                    for callee_sym, callee_refs in self._references.items():
                        if callee_sym == symbol:
                            continue
                        for ref in callee_refs:
                            if ref.symbol == sym and not ref.is_definition:
                                callee_entry = {
                                    "symbol": callee_sym,
                                    "file": ref.file_path,
                                    "line": ref.line,
                                    "kind": ref.kind,
                                    "depth": level + 1,
                                }
                                # Дедупликация
                                if not any(
                                    c.get("symbol") == callee_sym
                                    for c in result["callees"]
                                ):
                                    result["callees"].append(callee_entry)
                                    result["impact_files"].add(ref.file_path)
                                    next_level_callees.add(callee_sym)

                current_level_callees = next_level_callees
                if not current_level_callees:
                    break

            # 4. Строим call_chain для контекста (путь вызовов)
            if result["callers"]:
                top_callers = sorted(
                    result["callers"],
                    key=lambda c: c.get("depth", 99),
                )[:5]
                result["call_chain"] = [
                    f"{c['symbol']} ({c['file']}:{c['line']})" for c in top_callers
                ]

            result["impact_files"] = sorted(result["impact_files"])
            return result

    def get_impact_analysis(self, symbol: str, depth: int = 3) -> Dict:
        """Анализ влияния изменения/удаления символа на проект.

        Расширяет build_call_graph метриками риска и агрегированной статистикой.

        Args:
            symbol: Имя символа для анализа
            depth: Глубина обхода графа (1-5)

        Returns:
            {
                'symbol': str,
                'direct_callers': int,
                'transitive_callers': int,
                'direct_callees': int,
                'transitive_callees': int,
                'affected_files': List[str],
                'affected_modules': List[str],
                'risk_level': str,        # 'low' | 'medium' | 'high' | 'critical'
                'risk_score': int,        # 0-100
                'call_graph': Dict,       # Полный граф из build_call_graph
            }
        """
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

        if risk_score >= 70:
            risk_level = "critical"
        elif risk_score >= 50:
            risk_level = "high"
        elif risk_score >= 25:
            risk_level = "medium"
        else:
            risk_level = "low"

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
        """Анализирует влияние изменений в файлах на архитектуру проекта.

        Возвращает:
        - added_symbols: новые символы в изменённых файлах
        - affected_callers: кто зависит от изменённых файлов
        - impact_summary: текстовое резюме для AI
        """
        with self._lock:
            added_symbols = []
            affected_callers = []
            all_impact_files = set()

            for file_path in changed_files:
                defs = self._file_to_defs.get(file_path, set())
                for sym_name in defs:
                    sym_defs = self._definitions.get(sym_name, [])
                    for sd in sym_defs:
                        if sd.file_path == file_path:
                            added_symbols.append(
                                {
                                    "symbol": sym_name,
                                    "kind": sd.kind,
                                    "line": sd.line,
                                }
                            )

                    # Кто ещё использует этот символ?
                    refs = self._references.get(sym_name, [])
                    for r in refs:
                        if r.file_path != file_path:
                            affected_callers.append(
                                {
                                    "symbol": sym_name,
                                    "called_from": r.file_path,
                                    "line": r.line,
                                }
                            )
                            all_impact_files.add(r.file_path)

            # Формируем текстовое резюме
            summary_parts = []
            for sym in added_symbols[:10]:
                callers = [c for c in affected_callers if c["symbol"] == sym["symbol"]]
                if callers:
                    files = list(set(c["called_from"] for c in callers))[:3]
                    summary_parts.append(
                        f"{sym['kind'].upper()} {sym['symbol']} -> используется в {', '.join(files)}"
                    )
                else:
                    summary_parts.append(
                        f"{sym['kind'].upper()} {sym['symbol']} (нет внешних зависимостей)"
                    )

            return {
                "changed_files": changed_files,
                "added_symbols": added_symbols,
                "affected_callers": affected_callers,
                "impact_files": sorted(all_impact_files),
                "impact_summary": "\n".join(summary_parts),
            }

    # --- Статистика ---

    def stats(self) -> Dict:
        """Возвращает статистику индекса символов."""
        with self._lock:
            total_defs = sum(len(v) for v in self._definitions.values())
            total_refs = sum(len(v) for v in self._references.values())
            unique_symbols = len(self._definitions)
            return {
                "total_symbols": unique_symbols,
                "total_definitions": total_defs,
                "total_references": total_refs,
                "tracked_files": len(self._file_to_symbols),
            }

    def get_symbol_count(self) -> int:
        """Возвращает общее количество уникальных символов."""
        with self._lock:
            return len(self._definitions)

    # --- Методы для совместимости с Intelligence Layer ---

    def get_callers(self, symbol: str) -> List["SymbolRef"]:
        """Кто вызывает этот символ (обратные связи).

        Возвращает список SymbolRef для всех символов, которые вызывают данный символ.
        """
        return [r for r in self.find_references(symbol) if not r.is_definition]

    def get_callees(self, symbol: str) -> List[Dict]:
        """Кого вызывает этот символ (прямые связи).

        Возвращает список символов, которые вызываются данным символом.
        """
        graph = self.build_call_graph(symbol, depth=1)
        return graph.get("callees", [])

    def get_references(self, symbol: str) -> List["SymbolRef"]:
        """Все упоминания символа (определения + использования).

        Возвращает полный список всех ссылок на символ.
        """
        return self.find_references(symbol)

    def index_project(self, project_path: str, parser) -> None:
        """
        Индексирует проект с помощью парсера (Tree-sitter).

        Извлекает:
        - Определения символов (definitions)
        - Вызовы функций (references/calls) для построения графа вызовов

        Args:
            project_path: Корневая директория проекта
            parser: Экземпляр CodeParser для парсинга файлов
        """
        import os
        from pathlib import Path

        project_root = Path(project_path).resolve()

        # Обходим все файлы в проекте
        for root, dirs, files in os.walk(str(project_root)):
            # Фильтрация директорий
            dirs[:] = [d for d in dirs if not self._should_skip_dir(d)]

            for file in files:
                abs_file_path = Path(root) / file

                # Парсим файл (parser.parse_file возвращает кортеж (chunks, symbols))
                chunks, symbols = parser.parse_file(abs_file_path)

                # Относительный путь для индекса - строго нормализуем через resolve()
                rel_path = abs_file_path.relative_to(project_root).as_posix()

                # Удаляем старые данные об этом файле перед добавлением новых
                self.remove_file(rel_path)

                # Добавляем определения
                if symbols:
                    self.add_definitions(rel_path, symbols)

                # Извлекаем и добавляем вызовы функций для графа вызовов
                if hasattr(parser, "extract_calls"):
                    calls = parser.extract_calls(abs_file_path)
                    if calls:
                        # Нормализуем пути в calls
                        for call in calls:
                            call["file"] = rel_path
                        self.add_references(rel_path, calls)

    def _should_skip_dir(self, dir_name: str) -> bool:
        """Определяет, следует ли пропускать директорию."""
        skip_dirs = {
            ".git",
            "node_modules",
            "venv",
            ".venv",
            "__pycache__",
            "dist",
            "build",
            "target",
            ".tox",
            ".mypy_cache",
            ".ruff_cache",
            ".pytest_cache",
            "htmlcov",
            ".coverage",
            ".codebase_index",
            ".codebase_models",
            ".zed",
            ".idea",
            ".vscode",
            "out",
        }
        return dir_name in skip_dirs

    def compute_repo_rank(
        self, damping: float = 0.85, iterations: int = 20
    ) -> Dict[str, float]:
        """Вычисляет PageRank для символов на графе вызовов.

        Алгоритм PageRank адаптирован для графа вызовов:
        - Узлы: символы (функции, классы)
        - Рёбра: вызовы (caller → callee)
        - Вес: количество вызовов

        Символы с высоким RepoRank — "сердце" проекта.
        Они используются чаще всего и критически важны.

        Args:
            damping: Коэффициент затухания (стандартный 0.85)
            iterations: Количество итераций

        Returns:
            {symbol: score} — нормализованные скоры (0-1)
        """
        with self._lock:
            # Собираем все символы
            all_symbols = set(self._definitions.keys())
            for sym, refs in self._references.items():
                all_symbols.add(sym)
                for r in refs:
                    all_symbols.add(r.symbol)

            if not all_symbols:
                return {}

            # Инициализируем скоры
            n = len(all_symbols)
            scores = {sym: 1.0 / n for sym in all_symbols}

            # Строим обратный граф: для каждого symbol — кто его вызывает
            # (нужно для PageRank — голоса идут ОТ callers К callee)
            incoming = {sym: [] for sym in all_symbols}
            for callee, refs in self._references.items():
                for ref in refs:
                    if not ref.is_definition and ref.symbol in incoming:
                        incoming[callee].append(ref.symbol)

            # Итерации PageRank
            for _ in range(iterations):
                new_scores = {}
                for sym in all_symbols:
                    rank_sum = 0.0
                    for caller in incoming.get(sym, []):
                        # Количество исходящих связей caller'а
                        out_degree = len(self._references.get(caller, []))
                        if out_degree > 0:
                            rank_sum += scores[caller] / out_degree
                    new_scores[sym] = (1 - damping) / n + damping * rank_sum
                scores = new_scores

            # Нормализация (максимальный = 1.0)
            if scores:
                max_score = max(scores.values())
                if max_score > 0:
                    scores = {k: v / max_score for k, v in scores.items()}

            return scores

    def get_repo_map(self, project_root: str) -> Dict:
        """
        Возвращает карту репозитория: структуру директорий + символы в файлах.

        Args:
            project_root: Корневая директория проекта

        Returns:
            Словарь с ключами:
            - "structure": список директорий и файлов
            - "symbols_by_file": словарь file_path -> список символов
            - "all_symbols": список всех уникальных символов
        """
        with self._lock:
            # Структура директорий
            structure = []
            symbols_by_file = {}
            all_symbols = []

            # Нормализуем project_root (POSIX, lowercase) для сравнения
            try:
                norm_project = (
                    Path(project_root).resolve().as_posix().lower().rstrip("/") + "/"
                )
            except Exception:
                norm_project = project_root.replace("\\", "/").lower().rstrip("/") + "/"

            # Фильтруем файлы — только те, что относятся к этому проекту
            # SymbolIndex может содержать файлы из extension + из разных проектов
            def _belongs_to_project(fp: str) -> bool:
                """Проверяет, принадлежит ли файл проекту.

                На Windows пути могут храниться как с backslash (D:\...\file.py),
                так и с forward slash (D:/.../file.py). Используем os.path.isabs()
                для корректного определения абсолютности на любой платформе.
                """
                import os
                from pathlib import Path

                # Относительный путь (без диска) — всегда включаем
                if not os.path.isabs(fp):
                    return True
                # Абсолютный путь — проверяем что внутри project_root
                norm_fp = Path(fp).resolve().as_posix().lower()
                return norm_fp.startswith(norm_project)

            all_files = {
                fp for fp in self._file_to_symbols.keys() if _belongs_to_project(fp)
            }

            def _to_rel_path(fp: str) -> str:
                """Преобразует абсолютный путь в относительный от project_root."""
                if _belongs_to_project(fp) and (
                    len(fp) > 2 and (fp[0] == "/" or fp[1] == ":")
                ):
                    try:
                        return str(
                            Path(fp).resolve().relative_to(Path(project_root).resolve())
                        )
                    except (ValueError, Exception):
                        pass
                return fp.replace("\\", "/").lstrip("/")

            # Строим иерархическую структуру
            dir_structure = {}
            for file_path in sorted(all_files):
                rel_path = _to_rel_path(file_path)
                parts = rel_path.replace("\\", "/").split("/")

                current = dir_structure
                for part in parts[:-1]:
                    if part not in current:
                        current[part] = {"__dirs__": [], "__files__": []}
                    current = current[part]

                # Добавляем файл
                filename = parts[-1]
                if "__files__" not in current:
                    current["__files__"] = []
                current["__files__"].append(filename)

                # Собираем символы для этого файла
                file_symbols = []
                for symbol_name in self._file_to_symbols.get(file_path, []):
                    defs = self._definitions.get(symbol_name, [])
                    refs = self._references.get(symbol_name, [])

                    # Находим определения в этом файле
                    file_defs = [d for d in defs if d.file_path == file_path]
                    file_refs = [r for r in refs if r.file_path == file_path]

                    if file_defs or file_refs:
                        symbol_info = {
                            "name": symbol_name,
                            "kind": file_defs[0].kind if file_defs else "unknown",
                            "definitions": [
                                {"line": d.line, "context": d.kind} for d in file_defs
                            ],
                            "references": [{"line": r.line} for r in file_refs],
                            "total_definitions": len(file_defs),
                            "total_references": len(file_refs),
                        }
                        file_symbols.append(symbol_info)
                        all_symbols.append(symbol_name)

                symbols_by_file[file_path] = file_symbols

            # Преобразуем иерархическую структуру в плоский список
            def flatten_structure(node, path=""):
                items = []
                for key, value in node.items():
                    if key == "__dirs__":
                        continue
                    elif key == "__files__":
                        for filename in value:
                            items.append(
                                {
                                    "type": "file",
                                    "name": filename,
                                    "path": f"{path}/{filename}" if path else filename,
                                }
                            )
                    else:
                        dir_path = f"{path}/{key}" if path else key
                        items.append(
                            {
                                "type": "directory",
                                "name": key,
                                "path": dir_path,
                            }
                        )
                        items.extend(flatten_structure(value, dir_path))
                return items

            structure = flatten_structure(dir_structure)

            return {
                "structure": structure,
                "symbols_by_file": symbols_by_file,
                "all_symbols": list(set(all_symbols)),
                "total_files": len(all_files),
                "total_symbols": len(all_symbols),
            }
