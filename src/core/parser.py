"""
Парсинг кода через Tree-sitter с контекстным чанкингом и надежным fallback.
"""

import logging
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


class CodeParser:
    """Парсит код и разбивает на семантически значимые чанки (функции, методы)."""

    SUPPORTED_EXTENSIONS = {".py", ".rs", ".ts", ".tsx", ".js", ".jsx", ".go", ".md"}

    # Узлы, которые мы извлекаем как чанки
    TARGET_NODES = {
        "function_definition",
        "method_definition",
        "function_item",
        "impl_item",
        "method_declaration",
        "function_declaration",
    }

    # Узлы вызовов функций — для построения графа вызовов
    CALL_NODES = {
        "call_expression",      # Python, JS, Go, Rust
        "call",                  # Альтернативные грамматики
        "function_invocation",   # Java
        "invocation_expression", # Java (method invocation)
        "macro_invocation",      # Rust macros!
    }

    # Типы узлов, которые мы считаем "идентификаторами" при поиске вызовов
    CALL_IDENTIFIER_TYPES = {
        "identifier",
        "type_identifier",
        "field_expression",     # obj.method()
        "scoped_identifier",     # module::func()
    }

    # Узлы-контейнеры, чьи имена мы запоминаем для контекста
    CONTAINER_NODES = {
        "class_definition",
        "struct_item",
        "impl_item",
        "class_declaration",
        "interface_declaration",
    }

    # Настройки Fallback-чанкера и защиты от гигантских функций
    MAX_CHUNK_CHARS = 3000  # Максимальный размер семантического чанка в символах
    FALLBACK_CHUNK_LINES = 100
    FALLBACK_OVERLAP_LINES = 20

    def __init__(self):
        self.parsers = {}
        self._init_tree_sitter()

    def _init_tree_sitter(self):
        """Инициализирует Tree-sitter парсеры с поддержкой разных версий API."""
        try:
            from tree_sitter import Language, Parser

            # Python
            try:
                import tree_sitter_python as tspython

                parser = Parser()
                # Поддержка старого и нового API tree-sitter-python
                if hasattr(tspython, "LANGUAGE"):
                    parser.language = Language(tspython.LANGUAGE)  # type: ignore[attr-defined]
                else:
                    parser.language = Language(tspython.language())
                self.parsers[".py"] = parser
            except ImportError:
                logger.debug("Tree-sitter Python недоступен.")

            # Rust
            try:
                import tree_sitter_rust as tsrust

                parser = Parser()
                parser.language = Language(tsrust.language())
                self.parsers[".rs"] = parser
            except ImportError:
                logger.debug("Tree-sitter Rust недоступен.")

            # TypeScript / TSX
            try:
                import tree_sitter_typescript as tstypescript

                parser_ts = Parser()
                parser_ts.language = Language(tstypescript.language_typescript())
                self.parsers[".ts"] = parser_ts

                parser_tsx = Parser()
                parser_tsx.language = Language(tstypescript.language_tsx())
                self.parsers[".tsx"] = parser_tsx
            except ImportError:
                logger.debug("Tree-sitter TypeScript недоступен.")

            logger.info(f"✅ Tree-sitter готов для: {list(self.parsers.keys())}")

        except ImportError as e:
            logger.warning(f"⚠️ Модуль Tree-sitter не установлен: {e}")

    def parse_file(self, file_path: Path) -> tuple:
        """Главный метод парсинга файла. Возвращает (chunks, symbols)."""
        ext = file_path.suffix.lower()

        if ext not in self.SUPPORTED_EXTENSIONS:
            return [], []

        if ext == ".md":
            return self._parse_markdown(file_path)

        if ext in self.parsers:
            try:
                chunks, symbols = self._parse_with_tree_sitter(file_path, ext)
                if chunks:
                    return chunks, symbols
            except Exception as e:
                logger.warning(
                    f"Ошибка Tree-sitter для {file_path}, используем fallback: {e}"
                )

        # Надежный Fallback (Line-based)
        return self._fallback_line_chunking(file_path)

    def _parse_with_tree_sitter(self, file_path: Path, ext: str) -> tuple:
        """Парсинг через AST с сохранением контекста и извлечением символов.
        Возвращает (chunks, symbols).
        """
        parser = self.parsers[ext]

        try:
            with open(file_path, "rb") as f:
                code = f.read()
        except Exception as e:
            logger.warning(f"Ошибка чтения файла {file_path}: {e}")
            return [], []

        if not code.strip():
            return [], []

        tree = parser.parse(code)
        chunks = []
        symbols = []

        # Запускаем обход
        self._walk_node(
            tree.root_node, code, file_path, chunks, symbols, parent_context=""
        )

        if not chunks:
            return self._fallback_line_chunking(file_path)

        return chunks, symbols

    def _walk_node(
        self,
        node,
        code: bytes,
        file_path: Path,
        chunks: List,
        symbols: List,
        parent_context: str,
    ):
        """Рекурсивно обходит AST. Извлекает функции и символы.

        Ключевая оптимизация токенов: чанк = только сигнатура + 3 строки тела,
        полное тело сохраняется отдельно для релевантности при поиске.
        """
        current_context = parent_context

        # 1. Извлекаем контекст (имя класса/структуры)
        if node.type in self.CONTAINER_NODES:
            name_node = self._find_child_by_type(
                node, "identifier"
            ) or self._find_child_by_type(node, "type_identifier")
            if name_node:
                class_name = code[name_node.start_byte : name_node.end_byte].decode(
                    "utf-8", errors="ignore"
                )
                current_context = (
                    f"{parent_context}.{class_name}" if parent_context else class_name
                )

        # 2. Если это целевой узел (функция/метод)
        if node.type in self.TARGET_NODES:
            text = code[node.start_byte : node.end_byte].decode(
                "utf-8", errors="ignore"
            )
            if text.strip():
                prefix = f"// Context: {current_context}\n" if current_context else ""

                # Извлекаем имя функции/метода для SymbolIndex
                name_node = self._find_child_by_type(
                    node, "identifier"
                ) or self._find_child_by_type(node, "name")
                symbol_name = ""
                if name_node:
                    symbol_name = code[
                        name_node.start_byte : name_node.end_byte
                    ].decode("utf-8", errors="ignore")
                    full_symbol = (
                        f"{current_context}.{symbol_name}"
                        if current_context
                        else symbol_name
                    )
                    symbols.append(
                        {
                            "name": full_symbol,
                            "line": node.start_point[0],
                            "kind": node.type,
                        }
                    )

                # ТОКЕН-ЭФФЕКТИВНЫЙ ЧАНК:
                # Сигнатура (первая строка) + короткий превью тела
                lines = text.splitlines(keepends=True)
                signature = lines[0] if lines else text
                body_preview = "".join(lines[1:4]) if len(lines) > 1 else ""

                compact_text = signature + body_preview
                if len(compact_text) > self.MAX_CHUNK_CHARS:
                    compact_text = compact_text[: self.MAX_CHUNK_CHARS] + "\n..."

                # Защита от гигантских функций
                if len(text) > self.MAX_CHUNK_CHARS:
                    start_offset = node.start_point[0]
                    sub_chunks = self._chunk_giant_text(
                        lines, str(file_path), start_offset, prefix, current_context
                    )
                    for sc in sub_chunks:
                        sc["symbol_name"] = symbol_name
                    chunks.extend(sub_chunks)
                else:
                    chunks.append(
                        {
                            "text": prefix + text,
                            "text_compact": prefix + compact_text,
                            "file": str(file_path),
                            "start_line": node.start_point[0],
                            "end_line": node.end_point[0],
                            "type": node.type,
                            "context": current_context,
                            "symbol_name": symbol_name,
                        }
                    )

        # 3. Идем глубже в детей
        for child in node.children:
            self._walk_node(child, code, file_path, chunks, symbols, current_context)

    def _find_child_by_type(self, node, node_type: str):
        """Утилита для поиска дочернего узла по типу."""
        for child in node.children:
            if child.type == node_type:
                return child
        return None

    def extract_calls(self, file_path: Path) -> List[Dict]:
        """Извлекает все вызовы функций из файла для построения графа вызовов.

        Возвращает список словарей:
        [
            {
                "caller": "function_name",   # кто вызывает
                "callee": "called_function",  # кого вызывают
                "line": 42,                    # строка вызова
                "file": "path/to/file.py",     # файл
            },
            ...
        ]
        """
        ext = file_path.suffix.lower()
        if ext not in self.parsers or ext == ".md":
            return []

        try:
            with open(file_path, "rb") as f:
                code = f.read()
        except Exception:
            return []

        if not code.strip():
            return []

        parser = self.parsers[ext]
        tree = parser.parse(code)

        calls = []
        self._extract_calls_recursive(
            tree.root_node, code, file_path, calls, current_function=""
        )
        return calls

    def _extract_calls_recursive(
        self,
        node,
        code: bytes,
        file_path: Path,
        calls: List[Dict],
        current_function: str,
    ):
        """Рекурсивно извлекает вызовы функций из AST.

        Args:
            node: Текущий узел AST
            code: Исходный код файла
            file_path: Путь к файлу
            calls: Накопитель результатов
            current_function: Имя текущей функции (контекст вызова)
        """
        # Обновляем контекст текущей функции
        if node.type in self.TARGET_NODES:
            name_node = self._find_child_by_type(
                node, "identifier"
            ) or self._find_child_by_type(node, "name")
            if name_node:
                current_function = code[
                    name_node.start_byte : name_node.end_byte
                ].decode("utf-8", errors="ignore")

        # Если это узел вызова — извлекаем имя вызываемой функции
        if node.type in self.CALL_NODES:
            callee_name = self._extract_callee_name(node, code)
            if callee_name and current_function:
                calls.append({
                    "caller": current_function,
                    "callee": callee_name,
                    "line": node.start_point[0],
                    "file": str(file_path),
                })

        # Рекурсивно обходим детей
        for child in node.children:
            self._extract_calls_recursive(
                child, code, file_path, calls, current_function
            )

    def _extract_callee_name(self, call_node, code: bytes) -> str:
        """Извлекает имя вызываемой функции из узла вызова.

        Поддерживает:
        - Простые вызовы: func() → "func"
        - Методы объектов: obj.method() → "method"
        - Цепочки: a.b.c() → "c"
        - Scoped: module::func() → "func"
        """
        # Ищем идентификатор среди прямых детей
        for child in call_node.children:
            if child.type in self.CALL_IDENTIFIER_TYPES:
                name = code[child.start_byte : child.end_byte].decode(
                    "utf-8", errors="ignore"
                )
                # Для field_expression (obj.method) берём последнюю часть
                if child.type == "field_expression":
                    # field_expression: obj.field → ищем identifier внутри
                    for subchild in child.children:
                        if subchild.type == "identifier":
                            return code[
                                subchild.start_byte : subchild.end_byte
                            ].decode("utf-8", errors="ignore")
                        elif subchild.type == "property_identifier":
                            return code[
                                subchild.start_byte : subchild.end_byte
                            ].decode("utf-8", errors="ignore")
                # Для scoped_identifier (module::func) берём последний сегмент
                elif child.type == "scoped_identifier":
                    parts = name.split("::")
                    return parts[-1] if parts else name
                else:
                    return name
        return ""

    def _chunk_giant_text(
        self,
        lines: List[str],
        file_path: str,
        start_line_offset: int,
        prefix: str,
        context: str,
    ) -> List[Dict]:
        """Разбивает слишком большой кусок кода (например, огромную функцию) на части.
        Каждая часть = токен-эффективное preview."""
        chunks = []
        step = self.FALLBACK_CHUNK_LINES - self.FALLBACK_OVERLAP_LINES
        for i in range(0, len(lines), step):
            chunk_lines = lines[i : i + self.FALLBACK_CHUNK_LINES]
            text = "".join(chunk_lines).strip()
            if text:
                part_num = i // step + 1
                compact = text[:500] + "\n..." if len(text) > 500 else text
                chunks.append(
                    {
                        "text": f"{prefix}// [Part {part_num}]\n{text}",
                        "text_compact": f"{prefix}// [Part {part_num}]\n{compact}",
                        "file": file_path,
                        "start_line": start_line_offset + i,
                        "end_line": start_line_offset + i + len(chunk_lines) - 1,
                        "type": "giant_function_part",
                        "context": context,
                        "symbol_name": "",
                    }
                )
        return chunks

    def _fallback_line_chunking(self, file_path: Path) -> tuple:
        """Безопасный Fallback: нарезка по строкам с перекрытием (overlap).
        Возвращает (chunks, symbols)."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception as e:
            logger.warning(f"Ошибка чтения {file_path}: {e}")
            return [], []

        if not lines:
            return [], []

        chunks = []
        for i in range(
            0, len(lines), self.FALLBACK_CHUNK_LINES - self.FALLBACK_OVERLAP_LINES
        ):
            chunk_lines = lines[i : i + self.FALLBACK_CHUNK_LINES]
            text = "".join(chunk_lines).strip()
            if text:
                compact = text[:500] + "\n..." if len(text) > 500 else text
                chunks.append(
                    {
                        "text": text,
                        "text_compact": compact,
                        "file": str(file_path),
                        "start_line": i,
                        "end_line": i + len(chunk_lines) - 1,
                        "type": "fallback_lines",
                        "context": "",
                        "symbol_name": "",
                    }
                )
        return chunks, []

    def _parse_markdown(self, file_path: Path) -> tuple:
        """Улучшенный парсинг Markdown с защитой блоков кода.
        Возвращает (chunks, symbols)."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return [], []

        if not content.strip():
            return [], []

        chunks = []
        current_section = []
        current_header = ""
        current_start = 0
        in_code_block = False

        for i, line in enumerate(content.splitlines()):
            stripped = line.strip()

            # Отслеживаем, находимся ли мы внутри блока кода
            if stripped.startswith("```"):
                in_code_block = not in_code_block

            # Разбиваем секции только если символ `#` вне блока кода
            if not in_code_block and stripped.startswith("#"):
                # Сохраняем предыдущий блок
                if current_section:
                    text = "\n".join(current_section).strip()
                    if text:
                        compact = text[:500] + "\n..." if len(text) > 500 else text
                        chunks.append(
                            {
                                "text": f"{current_header}\n\n{text}".strip(),
                                "text_compact": f"{current_header}\n\n{compact}".strip(),
                                "file": str(file_path),
                                "start_line": current_start,
                                "end_line": i - 1,
                                "type": "markdown_section",
                                "context": "",
                                "symbol_name": "",
                            }
                        )
                current_header = stripped
                current_section = []
                current_start = i
            else:
                current_section.append(line)

        # Сохраняем последний блок
        if current_section:
            text = "\n".join(current_section).strip()
            if text:
                compact = text[:500] + "\n..." if len(text) > 500 else text
                chunks.append(
                    {
                        "text": f"{current_header}\n\n{text}".strip(),
                        "text_compact": f"{current_header}\n\n{compact}".strip(),
                        "file": str(file_path),
                        "start_line": current_start,
                        "end_line": len(content.splitlines()) - 1,
                        "type": "markdown_section",
                        "context": "",
                        "symbol_name": "",
                    }
                )

        return chunks, []
