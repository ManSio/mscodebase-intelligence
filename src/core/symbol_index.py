"""
Symbol Index — отслеживание определений и использований символов между файлами.
"""

import logging
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
        Также строит связи вызовов: какие символы данный файл использует.
        """
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

            # Строим связи вызовов: какие определённые в проекте символы
            # используются в этом файле (кроме собственных определений)
            calls_in_file = set()
            for name in defined_names:
                # Ищем использования этого символа в других файлах
                if name in self._references:
                    for ref in self._references[name]:
                        if ref.file_path != file_path:
                            calls_in_file.add(name)
                            break
            self._file_to_calls[file_path] = calls_in_file

    def remove_file(self, file_path: str) -> None:
        """Удаляет все записи о файле (при удалении/переиндексации)."""
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
        with self._lock:
            return list(self._file_to_defs.get(file_path, set()))

    def get_symbol_context(self, symbol: str) -> Dict:
        """
        Возвращает контекст символа для обогащения результатов поиска.
        Используется search_code чтобы показать "эта функция используется в N файлах".
        """
        with self._lock:
            defs = self._definitions.get(symbol, [])
            refs = self._references.get(symbol, [])

            if not defs and not refs:
                return {}

            unique_files_using = set(r.file_path for r in refs)

            return {
                "symbol": symbol,
                "defined_in": [
                    {"file": d.file_path, "line": d.line, "kind": d.kind} for d in defs
                ],
                "used_in_count": len(unique_files_using),
                "used_in_files": list(unique_files_using)[:10],  # топ-10
            }

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
        """Строит граф вызовов для символа.

        Возвращает:
        - definition: где определён символ
        - callers: кто вызывает этот символ (обратные связи)
        - callees: какие символы вызывает этот символ (прямые связи)
        - impact_files: файлы, которые затронет изменение символа
        """
        with self._lock:
            result = {
                "symbol": symbol,
                "definition": [],
                "callers": [],
                "callees": [],
                "impact_files": set(),
            }

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

            # 2. Кто вызывает этот символ (callers)
            refs = self._references.get(symbol, [])
            caller_files = set()
            for r in refs:
                if not r.is_definition:
                    result["callers"].append(
                        {
                            "file": r.file_path,
                            "line": r.line,
                            "kind": r.kind,
                        }
                    )
                    caller_files.add(r.file_path)
                    result["impact_files"].add(r.file_path)

            # 3. Какие символы вызывает файл, где определён этот символ (callees)
            for d in defs:
                file_calls = self._file_to_calls.get(d.file_path, set())
                for called_sym in file_calls:
                    if called_sym == symbol:
                        continue
                    called_defs = self._definitions.get(called_sym, [])
                    for cd in called_defs:
                        result["callees"].append(
                            {
                                "symbol": called_sym,
                                "file": cd.file_path,
                                "line": cd.line,
                                "kind": cd.kind,
                            }
                        )
                        result["impact_files"].add(cd.file_path)

            # 4. Если depth > 1, рекурсивно ищем кто вызывает callers
            if depth > 1 and caller_files:
                for caller_file in list(caller_files)[:5]:  # лимит чтобы не раздувать
                    file_defs = self._file_to_defs.get(caller_file, set())
                    for sym_name in file_defs:
                        sym_refs = self._references.get(sym_name, [])
                        for sr in sym_refs:
                            if not sr.is_definition and sr.file_path != caller_file:
                                result["callers"].append(
                                    {
                                        "symbol": sym_name,
                                        "file": sr.file_path,
                                        "line": sr.line,
                                        "kind": "indirect_caller",
                                    }
                                )
                                result["impact_files"].add(sr.file_path)

            result["impact_files"] = sorted(result["impact_files"])
            return result

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

    def index_project(self, project_path: str, parser) -> None:
        """
        Индексирует проект с помощью парсера (Tree-sitter).

        Args:
            project_path: Корневая директория проекта
            parser: Экземпляр CodeParser для парсинга файлов
        """
        import os
        from pathlib import Path

        project_root = Path(project_path)

        # Обходим все файлы в проекте
        for root, dirs, files in os.walk(project_path):
            # Фильтрация директорий
            dirs[:] = [d for d in dirs if not self._should_skip_dir(d)]

            for file in files:
                file_path = Path(root) / file

                # Парсим файл (parser.parse_file возвращает кортеж (chunks, symbols))
                chunks, symbols = parser.parse_file(file_path)

                if symbols:
                    # Добавляем определения в индекс
                    rel_path = str(file_path.relative_to(project_root))
                    # Удаляем старые данные об этом файле перед добавлением новых
                    self.remove_file(rel_path)
                    self.add_definitions(rel_path, symbols)

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

            # Собираем все файлы, которые мы отслеживаем
            all_files = set(self._file_to_symbols.keys())

            # Строим иерархическую структуру
            dir_structure = {}
            for file_path in all_files:
                # Относительный путь от project_root
                rel_path = file_path.replace(project_root, "").lstrip("/\\")
                parts = rel_path.split("/") if "/" in rel_path else rel_path.split("\\")

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
