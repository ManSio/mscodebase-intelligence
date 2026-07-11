"""
Парсинг кода через Tree-sitter с контекстным чанкингом и надежным fallback.
"""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.core.extensions import PARSE_EXTENSIONS

logger = logging.getLogger(__name__)


class CodeParser:
    """Парсит код и разбивает на семантически значимые чанки (функции, методы)."""

    SUPPORTED_EXTENSIONS = PARSE_EXTENSIONS

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
        "call_expression",  # Python, JS, Go, Rust
        "call",  # Альтернативные грамматики
        "function_invocation",  # Java
        "invocation_expression",  # Java (method invocation)
        "macro_invocation",  # Rust macros!
    }

    # Типы узлов, которые мы считаем "идентификаторами" при поиске вызовов
    CALL_IDENTIFIER_TYPES = {
        "identifier",
        "type_identifier",
        "field_expression",  # obj.method()
        "scoped_identifier",  # module::func()
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
    MAX_CHUNK_CHARS = (
        2000  # Максимальный размер семантического чанка в символах (≈512 токенов)
    )
    FALLBACK_CHUNK_LINES = 64  # ≈512 токенов для Python кода
    FALLBACK_OVERLAP_LINES = 16  # 25% перекрытие

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
            chunks, symbols = self._parse_markdown(file_path)
        elif ext in self.parsers:
            try:
                chunks, symbols = self._parse_with_tree_sitter(file_path, ext)
                if not chunks:
                    chunks, symbols = self._fallback_line_chunking(file_path)
            except Exception as e:
                logger.warning(
                    f"Ошибка Tree-sitter для {file_path}, используем fallback: {e}"
                )
                chunks, symbols = self._fallback_line_chunking(file_path)
        else:
            chunks, symbols = self._fallback_line_chunking(file_path)

        # v3.0: добавляем callees в metadata каждого чанка
        if chunks:
            try:
                calls = self.extract_calls(file_path)
                if calls:
                    callees_json = json.dumps(list(set(c["callee"] for c in calls)))
                    for ch in chunks:
                        ch["callees"] = callees_json
            except Exception:
                pass

        return chunks, symbols

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
                # v2.6.0: Contextual prefix с путём файла
                rel_path = str(file_path)
                if current_context:
                    prefix = f"// File: {rel_path} | Context: {current_context}\n"
                else:
                    prefix = f"// File: {rel_path}\n"

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
                        lines,
                        str(file_path),
                        start_offset,
                        prefix,
                        current_context,
                        symbol_name,
                    )
                    for sc in sub_chunks:
                        sc["symbol_name"] = symbol_name
                    chunks.extend(sub_chunks)
                else:
                    meta = self._build_chunk_metadata(
                        str(file_path), symbol_name, node.type, current_context
                    )
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
                            # Metadata (MCompassRAG + SproutRAG)
                            "layer": meta["layer"],
                            "module_name": meta["module_name"],
                            "hierarchy_level": meta["hierarchy_level"],
                            "is_public": meta["is_public"],
                            "symbol_type": meta["symbol_type"],
                            "parent_id": meta["parent_id"],
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

    @staticmethod
    def _build_chunk_metadata(
        file_path: str,
        symbol_name: str = "",
        node_type: str = "",
        context: str = "",
    ) -> Dict[str, Any]:
        """Строит метаданные чанка: архитектурный слой, модуль,
        уровень иерархии, публичность, parent_id.

        Args:
            file_path: Абсолютный или относительный путь к файлу.
            symbol_name: Имя символа (функции/метода).
            node_type: Тип узла AST (function_definition, method_definition, ...).
            context: Контекст — имя класса/структуры (если есть).

        Returns:
            Словарь с полями: layer, module_name, hierarchy_level,
            is_public, symbol_type, parent_id.
        """
        # Нормализация пути для детекции слоя
        path_lower = str(file_path).lower().replace("\\", "/")

        # --- Layer detection (MCompassRAG-style) ---
        if "/tests/" in path_lower:
            layer = "tests"
        elif "/src/core/" in path_lower:
            layer = "core"
        elif "/src/mcp/tools/" in path_lower:
            layer = "mcp_tools"
        elif "/src/mcp/" in path_lower:
            layer = "mcp"
        elif "/src/utils/" in path_lower:
            layer = "utils"
        elif "/docs/" in path_lower:
            layer = "docs"
        elif "/.agents/" in path_lower:
            layer = "agents"
        elif "/scripts/" in path_lower:
            layer = "scripts"
        elif "/.github/" in path_lower:
            layer = "ci"
        else:
            layer = "root"

        # --- Module name: из src/core/parser.py → core.parser ---
        m = re.search(r"(?:src|tests|scripts|docs)/(.+\.\w+)$", path_lower)
        if m:
            # Обрезаем расширение файла
            module_raw = m.group(1)
            dot_idx = module_raw.rfind(".")
            if dot_idx > 0:
                module_raw = module_raw[:dot_idx]
            module_name = module_raw.replace("/", ".")
        else:
            module_name = path_lower.replace("/", ".").strip(".")

        # --- is_public: символ не начинается с '_' ---
        is_public = bool(symbol_name) and not symbol_name.startswith("_")

        # --- hierarchy_level (SproutRAG-style) ---
        hierarchy_map = {
            "function_definition": "function",
            "function_item": "function",
            "function_declaration": "function",
            "method_definition": "method",
            "method_declaration": "method",
            "class_definition": "class",
            "impl_item": "impl",
            "fallback_lines": "lines",
            "giant_function_part": "function_part",
            "markdown_section": "section",
        }
        hierarchy_level = hierarchy_map.get(node_type, "other")

        # --- parent_id: детерминированный хеш родителя ---
        if context and hierarchy_level in ("method", "function"):
            # Метод внутри класса → parent = класс
            parent_key = f"{file_path}::{context}"
            parent_id = hashlib.md5(parent_key.encode()).hexdigest()
        elif hierarchy_level == "function_part" and symbol_name:
            # Часть гигантской функции → parent = функция
            parent_key = f"{file_path}::{context}::{symbol_name}"
            parent_id = hashlib.md5(parent_key.encode()).hexdigest()
        elif hierarchy_level in ("function", "method"):
            # Функция верхнего уровня → parent = модуль
            parent_id = hashlib.md5(f"{file_path}".encode()).hexdigest()
        else:
            parent_id = ""

        return {
            "layer": layer,
            "module_name": module_name,
            "hierarchy_level": hierarchy_level,
            "is_public": is_public,
            "symbol_type": node_type,
            "parent_id": parent_id,
        }

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
                calls.append(
                    {
                        "caller": current_function,
                        "callee": callee_name,
                        "line": node.start_point[0],
                        "file": str(file_path),
                    }
                )

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
                            return code[subchild.start_byte : subchild.end_byte].decode(
                                "utf-8", errors="ignore"
                            )
                        elif subchild.type == "property_identifier":
                            return code[subchild.start_byte : subchild.end_byte].decode(
                                "utf-8", errors="ignore"
                            )
                # Для scoped_identifier (module::func) берём последний сегмент
                elif child.type == "scoped_identifier":
                    parts = name.split("::")
                    return parts[-1] if parts else name
                else:
                    return name
        return ""

    # ── Assignment tracking for ASSIGNED_FROM edges ────────────

    def extract_assignments(self, file_path: Path) -> List[Dict]:
        """Извлекает ASSIGNED_FROM связи между переменными внутри функций.

        Использует Tree-sitter AST для отслеживания присваиваний
        внутри тел функций (интра-процедурный анализ).

        Returns:
            [
                {
                    "target": "x",
                    "source": "data",
                    "line": 10,
                    "file": "path/to/file.py",
                    "function": "process",
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

        assignments = []
        self._extract_assignments_recursive(
            tree.root_node,
            code,
            file_path,
            assignments,
            current_function="",
            assigned=None,
        )
        return assignments

    def _extract_assignments_recursive(
        self,
        node,
        code: bytes,
        file_path: Path,
        assignments: List[Dict],
        current_function: str,
        assigned: Optional[Set[str]] = None,
    ):
        """Рекурсивно обходит AST, отслеживая присваивания внутри функций.

        Использует scope stack: при входе в функцию пушит новый set(),
        при выходе — merge обратно. Корректно обрабатывает вложенные функции.

        Args:
            assigned: set[str] — имена уже присвоенных переменных
                      в текущем function scope. None → корневой scope.
        """
        if assigned is None:
            assigned = set()

        # ── Обнаружение входа в функцию → push scope ──
        pushed_scope = False
        if node.type in self.TARGET_NODES:
            name_node = (
                self._find_child_by_type(node, "identifier")
                or self._find_child_by_type(node, "name")
            )
            if name_node:
                current_function = code[
                    name_node.start_byte : name_node.end_byte
                ].decode("utf-8", errors="ignore")
            # Push: сохраняем родительский scope, создаём свежий для тела функции
            parent_assigned = assigned
            assigned = set()
            pushed_scope = True

        # ── a) Простое присваивание: x = <rhs> ──
        if node.type == "assignment":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left and left.type == "identifier" and right:
                self._process_rhs_for_assign(
                    target=code[left.start_byte : left.end_byte].decode(
                        "utf-8", errors="ignore"
                    ),
                    right=right,
                    code=code,
                    assigned=assigned,
                    assignments=assignments,
                    file_path=file_path,
                    line=node.start_point[0],
                    function=current_function,
                )

        # ── b) Составное присваивание: x += <rhs> ──
        elif node.type == "augmented_assignment":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left and left.type == "identifier" and right:
                target = code[left.start_byte : left.end_byte].decode(
                    "utf-8", errors="ignore"
                )
                self._process_rhs_for_assign(
                    target=target,
                    right=right,
                    code=code,
                    assigned=assigned,
                    assignments=assignments,
                    file_path=file_path,
                    line=node.start_point[0],
                    function=current_function,
                )

        # ── Рекурсивный обход детей ──
        for child in node.children:
            self._extract_assignments_recursive(
                child,
                code,
                file_path,
                assignments,
                current_function,
                assigned,
            )

        # ── Восстановление родительского scope при выходе из функции ──
        if pushed_scope:
            parent_assigned.update(assigned)

    def _process_rhs_for_assign(
        self,
        target: str,
        right,
        code: bytes,
        assigned: Set[str],
        assignments: List[Dict],
        file_path: Path,
        line: int,
        function: str,
    ):
        """Обрабатывает правую часть присваивания.

        Собирает identifier-ссылки в RHS, проверяет каждую против
        assigned set, создаёт ASSIGNED_FROM связи. Target всегда
        добавляется в assigned для последующего отслеживания.
        """
        # Собираем все identifier-ссылки в RHS
        ref_names = self._get_names_from_node(right, code)
        for ref in ref_names:
            if ref in assigned:
                assignments.append(
                    {
                        "target": target,
                        "source": ref,
                        "line": line,
                        "file": str(file_path),
                        "function": function,
                    }
                )

        # Target всегда помечается как assigned для chain-отслеживания
        assigned.add(target)

    def _get_names_from_node(self, node, code: bytes) -> List[str]:
        """Извлекает все identifier имена из поддерева узла.

        Собирает ТОЛЬКО identifier (не type_identifier),
        чтобы не путать с именами типов (int, str, List).
        Не заходит в function_definition/class_definition —
        их внутренние идентификаторы не относятся к текущему контексту.
        """
        names = []
        if node.type == "identifier":
            name = code[node.start_byte : node.end_byte].decode(
                "utf-8", errors="ignore"
            )
            names.append(name)
        # Не заходим в вложенные определения — их идентификаторы
        # относятся к внутреннему scope
        if node.type not in ("function_definition", "class_definition"):
            for child in node.children:
                names.extend(self._get_names_from_node(child, code))
        return names

    def _chunk_giant_text(
        self,
        lines: List[str],
        file_path: str,
        start_line_offset: int,
        prefix: str,
        context: str,
        symbol_name: str = "",
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
                # Метаданные для части гигантской функции
                meta = self._build_chunk_metadata(
                    str(file_path),
                    symbol_name=symbol_name,
                    node_type="giant_function_part",
                    context=context,
                )
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
                        # Metadata
                        "layer": meta["layer"],
                        "module_name": meta["module_name"],
                        "hierarchy_level": meta["hierarchy_level"],
                        "is_public": meta["is_public"],
                        "symbol_type": meta["symbol_type"],
                        "parent_id": meta["parent_id"],
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
        file_path_str = str(file_path)
        # v2.6.0: Contextual prefix для fallback-чанков
        fb_prefix = f"// File: {file_path_str}\n"
        # Единые метаданные для всех строк этого файла
        fallback_meta = self._build_chunk_metadata(
            file_path_str, symbol_name="", node_type="fallback_lines", context=""
        )
        for i in range(
            0, len(lines), self.FALLBACK_CHUNK_LINES - self.FALLBACK_OVERLAP_LINES
        ):
            chunk_lines = lines[i : i + self.FALLBACK_CHUNK_LINES]
            text = "".join(chunk_lines).strip()
            if text:
                compact = text[:500] + "\n..." if len(text) > 500 else text
                chunks.append(
                    {
                        "text": fb_prefix + text,
                        "text_compact": fb_prefix + compact,
                        "file": file_path_str,
                        "start_line": i,
                        "end_line": i + len(chunk_lines) - 1,
                        "type": "fallback_lines",
                        "context": "",
                        "symbol_name": "",
                        # Metadata
                        "layer": fallback_meta["layer"],
                        "module_name": fallback_meta["module_name"],
                        "hierarchy_level": fallback_meta["hierarchy_level"],
                        "is_public": fallback_meta["is_public"],
                        "symbol_type": fallback_meta["symbol_type"],
                        "parent_id": fallback_meta["parent_id"],
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
        file_path_str = str(file_path)
        # Единые метаданные для всех секций md-файла
        md_meta = self._build_chunk_metadata(
            file_path_str, symbol_name="", node_type="markdown_section", context=""
        )

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
                        # v2.6.0: Contextual prefix для .md
                        md_prefix = (
                            f"From {file_path_str}, section '{current_header}':\n"
                        )
                        chunks.append(
                            {
                                "text": md_prefix
                                + f"{current_header}\n\n{text}".strip(),
                                "text_compact": md_prefix
                                + f"{current_header}\n\n{compact}".strip(),
                                "file": file_path_str,
                                "start_line": current_start,
                                "end_line": i - 1,
                                "type": "markdown_section",
                                "context": "",
                                "symbol_name": "",
                                # Metadata
                                "layer": md_meta["layer"],
                                "module_name": md_meta["module_name"],
                                "hierarchy_level": md_meta["hierarchy_level"],
                                "is_public": md_meta["is_public"],
                                "symbol_type": md_meta["symbol_type"],
                                "parent_id": md_meta["parent_id"],
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
                md_prefix = f"From {file_path_str}, section '{current_header}':\n"
                chunks.append(
                    {
                        "text": md_prefix + f"{current_header}\n\n{text}".strip(),
                        "text_compact": md_prefix
                        + f"{current_header}\n\n{compact}".strip(),
                        "file": file_path_str,
                        "start_line": current_start,
                        "end_line": len(content.splitlines()) - 1,
                        "type": "markdown_section",
                        "context": "",
                        "symbol_name": "",
                        # Metadata
                        "layer": md_meta["layer"],
                        "module_name": md_meta["module_name"],
                        "hierarchy_level": md_meta["hierarchy_level"],
                        "is_public": md_meta["is_public"],
                        "symbol_type": md_meta["symbol_type"],
                        "parent_id": md_meta["parent_id"],
                    }
                )

        return chunks, []
