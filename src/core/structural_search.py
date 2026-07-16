"""
MSCodebase Intelligence — Structural Search (поиск по AST-паттернам).

Позволяет искать код не по тексту, а по структуре AST:
  • "все классы наследующие от Base"
  • "все функции с декоратором @app.get"
  • "все async def с await"
  • "все классы с __init__ принимающий self, name: str"

Использует Tree-sitter queries для точного структурного поиска.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class StructuralMatch:
    """Одно совпадение структурного поиска."""
    file_path: str
    start_line: int
    end_line: int
    text: str
    match_type: str          # "class", "function", "decorator", "pattern"
    context: str = ""        # Имя класса/функции
    matched_pattern: str = "" # Какой паттерн сработал


@dataclass
class SearchResult:
    """Результат структурного поиска."""
    pattern: str
    matches: List[StructuralMatch] = field(default_factory=list)
    files_scanned: int = 0
    duration_ms: float = 0.0

    @property
    def total_matches(self) -> int:
        return len(self.matches)


class StructuralSearcher:
    """Поиск по AST-паттернам через Tree-sitter queries."""

    # Предопределённые паттерны для разных языков
    PATTERNS = {
        "class_inheritance": {
            "query": """
                (class_definition
                    name: (identifier) @class_name
                    superclasses: (argument_list
                        (identifier) @parent_class)
                )
            """,
            "description": "Классы с наследованием",
        },
        "class_with_decorator": {
            "query": """
                (decorated_definition
                    (decorator
                        [
                            (identifier) @decorator_name
                            (call
                                (attribute
                                    (identifier) @decorator_obj
                                    (identifier) @decorator_method)
                            ) @decorator_call
                        ]
                    )
                    (class_definition
                        name: (identifier) @class_name)
                )
            """,
            "description": "Классы с декораторами",
        },
        "function_with_decorator": {
            "query": """
                (decorated_definition
                    (decorator
                        [
                            (identifier) @decorator_name
                            (call
                                (attribute
                                    (identifier) @decorator_obj
                                    (identifier) @decorator_method)
                            ) @decorator_call
                        ]
                    )
                    (function_definition
                        name: (identifier) @func_name)
                )
            """,
            "description": "Функции с декораторами",
        },
        "async_function": {
            "query": """
                (function_definition
                    "async"
                    name: (identifier) @func_name
                )
            """,
            "description": "Async функции",
        },
        "method_with_type_hints": {
            "query": """
                (function_definition
                    name: (identifier) @func_name
                    parameters: (parameters
                        (typed_parameter) @param)
                    return_type: (type)? @return_type
                )
            """,
            "description": "Методы с аннотациями типов",
        },
        "class_with_init": {
            "query": """
                (class_definition
                    name: (identifier) @class_name
                    body: (block
                        (function_definition
                            name: (identifier) @init_method
                        )
                    )
                )
            """,
            "description": "Классы с __init__",
        },
        "import_from": {
            "query": """
                (import_from_statement
                    (dotted_name) @module
                    (dotted_name) @symbol
                )
            """,
            "description": "Импорты from X import Y",
        },
        "try_except": {
            "query": """
                (try_statement
                    (block) @try_body
                    (except_clause
                        (identifier)? @exception_type
                    ) @handler
                )
            """,
            "description": "Try/except блоки",
        },
        "list_comprehension": {
            "query": """
                (list_comprehension
                    (identifier) @body
                    (for_in_clause
                        (identifier) @var
                        (expression) @iterable
                    )
                )
            """,
            "description": "List comprehensions",
        },
        "dict_comprehension": {
            "query": """
                (dictionary_comprehension
                    (pair) @pair
                )
            """,
            "description": "Dict comprehensions",
        },
        "lambda": {
            "query": """
                (lambda
                    parameters: (lambda_parameters)? @params
                    body: (expression) @body
                )
            """,
            "description": "Лямбда-функции",
        },
        "with_statement": {
            "query": """
                (with_statement
                    (with_clause
                        (with_item
                            value: (expression) @context_manager))
                    body: (block) @body
                )
            """,
            "description": "With statements (менеджеры контекста)",
        },
        "comprehension": {
            "query": """
                (list_comprehension
                    (identifier) @body
                    (for_in_clause) @clause
                )
            """,
            "description": "List comprehensions (most common)",
        },
    }

    def __init__(self, parser=None):
        """Инициализирует серчер с существующим CodeParser или создаёт новый."""
        if parser is None:
            from src.core.indexing.parser import CodeParser
            parser = CodeParser()
        self.parser = parser
        self._query_cache: Dict[str, Any] = {}
        self._validate_patterns()

    def _validate_patterns(self) -> None:
        """Валидирует PATTERNS и удаляет невалидные паттерны."""
        from tree_sitter import Query

        invalid = []
        for name, info in self.PATTERNS.items():
            ext = ".py"  # Проверяем на Python как базовом
            if ext not in self.parser.parsers:
                continue
            try:
                Query(self.parser.parsers[ext].language, info["query"])
            except Exception as e:
                logger.warning(f"Невалидный паттерн '{name}': {e}")
                invalid.append(name)

        for name in invalid:
            del self.PATTERNS[name]
            logger.info(f"Паттерн '{name}' удалён (невалидный Tree-sitter query)")

        if invalid:
            logger.info(f"Валидных паттернов: {len(self.PATTERNS)}")

    def search(
        self,
        project_path: Path,
        pattern_name: Optional[str] = None,
        custom_query: Optional[str] = None,
        file_extensions: Optional[List[str]] = None,
        max_results: int = 50,
    ) -> SearchResult:
        """Выполняет структурный поиск по проекту.

        Args:
            project_path: Корневая директория проекта
            pattern_name: Имя предопределённого паттерна (из PATTERNS)
            custom_query: Кастомный Tree-sitter query (если pattern_name не задан)
            file_extensions: Расширения файлов для поиска (по умолчанию все поддерживаемые)
            max_results: Максимальное число результатов

        Returns:
            SearchResult с найденными совпадениями
        """
        import time
        start_time = time.time()

        # Определяем паттерн
        if pattern_name and pattern_name in self.PATTERNS:
            pattern = self.PATTERNS[pattern_name]
            query_str = pattern["query"]
            description = pattern["description"]
        elif custom_query:
            query_str = custom_query
            description = "Custom pattern"
        else:
            return SearchResult(pattern="unknown", files_scanned=0)

        # Определяем расширения
        if file_extensions is None:
            file_extensions = list(self.parser.parsers.keys())

        # Собираем файлы
        files_to_scan = []
        for ext in file_extensions:
            files_to_scan.extend(project_path.rglob(f"*{ext}"))

        # Исключаем мусор
        files_to_scan = [
            f for f in files_to_scan
            if self._should_scan_file(f)
        ]

        result = SearchResult(pattern=description)

        # Сканируем файлы
        for file_path in files_to_scan:
            if result.total_matches >= max_results:
                break

            ext = file_path.suffix.lower()
            if ext not in self.parser.parsers:
                continue

            try:
                matches = self._search_in_file(file_path, ext, query_str, description)
                result.matches.extend(matches)
            except Exception as e:
                logger.debug(f"Ошибка сканирования {file_path}: {e}")

            result.files_scanned += 1

        result.duration_ms = (time.time() - start_time) * 1000
        return result

    def _search_in_file(
        self, file_path: Path, ext: str, query_str: str, description: str
    ) -> List[StructuralMatch]:
        """Ищет совпадения в одном файле."""
        parser = self.parser.parsers.get(ext)
        if not parser:
            return []

        try:
            with open(file_path, "rb") as f:
                code = f.read()
        except Exception:
            return []

        if not code.strip():
            return []

        tree = parser.parse(code)

        # Компилируем query (кэшируем)
        cache_key = f"{ext}:{query_str}"
        if cache_key not in self._query_cache:
            try:
                from tree_sitter import Query, QueryCursor
                self._query_cache[cache_key] = (Query(parser.language, query_str), QueryCursor)
            except Exception as e:
                logger.warning(f"Невалидный Tree-sitter query: {e}")
                return []

        query, QueryCursorClass = self._query_cache[cache_key]

        try:
            cursor = QueryCursorClass(query)
            raw_matches = cursor.matches(tree.root_node)
        except Exception:
            return []

        matches = []
        seen_ranges = set()  # Защита от дубликатов

        for pattern_index, captures_dict in raw_matches:
            for capture_name, nodes in captures_dict.items():
                for node in nodes:
                    range_key = (node.start_point[0], node.end_point[0], capture_name)
                    if range_key in seen_ranges:
                        continue
                    seen_ranges.add(range_key)

                    text = code[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

                    # Определяем контекст
                    context = self._extract_context(node, code)

                    match = StructuralMatch(
                        file_path=str(file_path),
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        text=text[:500],  # Ограничиваем длину
                        match_type=description,
                        context=context,
                        matched_pattern=capture_name,
                    )
                    matches.append(match)

        return matches

    def _extract_context(self, node, code: bytes) -> str:
        """Извлекает контекст (имя класса/функции) для узла."""
        # Ищем ближайший идентификатор
        current = node
        while current:
            for child in current.children:
                if child.type in ("identifier", "type_identifier"):
                    try:
                        return code[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                    except Exception as _e:
                        logger.warning("exception", exc_info=True)
                        pass
            current = current.parent

        return ""

    def _should_scan_file(self, file_path: Path) -> bool:
        """Проверяет стоит ли сканировать файл."""
        # Пропускаем бинарники и мусор
        skip_dirs = {
            "__pycache__", "node_modules", ".git", "venv", ".venv",
            ".tox", ".eggs", "*.egg-info", "build", "dist",
        }

        for part in file_path.parts:
            if part in skip_dirs:
                return False

        # Пропускаем слишком большие файлы (>1MB)
        try:
            if file_path.stat().st_size > 1_000_000:
                return False
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        return True

    def list_patterns(self) -> Dict[str, str]:
        """Возвращает список доступных паттернов."""
        return {
            name: info["description"]
            for name, info in self.PATTERNS.items()
        }

    def format_results(self, result: SearchResult) -> str:
        """Форматирует результаты для вывода."""
        if result.total_matches == 0:
            return f"🔍 Паттерн '{result.pattern}' не найден (просканировано {result.files_scanned} файлов за {result.duration_ms:.0f}ms)"

        lines = [
            f"🔍 Найдено {result.total_matches} совпадений для '{result.pattern}'",
            f"   (просканировано {result.files_scanned} файлов за {result.duration_ms:.0f}ms)\n",
        ]

        # Группируем по файлам
        by_file: Dict[str, List[StructuralMatch]] = {}
        for match in result.matches:
            by_file.setdefault(match.file_path, []).append(match)

        for file_path, file_matches in list(by_file.items())[:10]:  # Максимум 10 файлов
            lines.append(f"📄 {file_path}")
            for match in file_matches[:5]:  # Максимум 5 совпадений на файл
                context_str = f" ({match.context})" if match.context else ""
                lines.append(f"   └─ Строка {match.start_line}-{match.end_line}{context_str}")
                # Показываем первые 2 строки совпадения
                text_preview = match.text.split("\n")[0][:80]
                lines.append(f"      {text_preview}")
            if len(file_matches) > 5:
                lines.append(f"   ... и ещё {len(file_matches) - 5} совпадений")
            lines.append("")

        if len(by_file) > 10:
            lines.append(f"... и ещё в {len(by_file) - 10} файлах")

        return "\n".join(lines)
