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
    """

    def __init__(self):
        self._lock = threading.RLock()
        # symbol -> list of SymbolRef
        self._definitions: Dict[str, List[SymbolRef]] = {}
        self._references: Dict[str, List[SymbolRef]] = {}
        # file_path -> set of symbols (быстрый lookup при удалении файла)
        self._file_to_symbols: Dict[str, Set[str]] = {}

        # Регулярка для поиска идентификаторов в тексте
        self._id_pattern = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

    # --- Импорт из парсера ---

    def add_definitions(self, file_path: str, symbols: List[Dict]) -> None:
        """
        Добавляет определения символов из распаршенного файла.
        symbols: список {name, line, kind} от парсера.
        """
        with self._lock:
            if file_path not in self._file_to_symbols:
                self._file_to_symbols[file_path] = set()

            for sym in symbols:
                name = sym["name"]
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

    def remove_file(self, file_path: str) -> None:
        """Удаляет все записи о файле (при удалении/переиндексации)."""
        with self._lock:
            symbols = self._file_to_symbols.pop(file_path, set())
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

    def search_symbols(self, query: str, top_k: int = 10) -> List[Dict]:
        """
        Поиск символов по имени (частичное совпадение).
        Возвращает символы, отсортированные по числу использований (популярности).
        """
        query_lower = query.lower()
        scored: List[Tuple[int, str]] = []

        with self._lock:
            for name, defs in self._definitions.items():
                if query_lower in name.lower():
                    # Популярность = сколько файлов используют
                    refs = self._references.get(name, [])
                    unique_users = len(set(r.file_path for r in refs))
                    scored.append((unique_users, name))

        # Сортируем по популярности
        scored.sort(key=lambda x: -x[0])

        results = []
        for _, name in scored[:top_k]:
            ctx = self.get_symbol_context(name)
            if ctx:
                results.append(ctx)

        return results

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
