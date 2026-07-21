"""
auto_doc_updater.py — автоматическое обновление документации.

По Тумблеру: чистая бизнес-логика, без MCP-зависимостей.

Триггеры:
1. После реиндекса (вызывается из слоя intelligence)
2. Pre-commit хук (через GitHooksInstaller)
3. Idle scheduler (фоновый поток)
4. По требованию (MCP-инструмент)

Что обновляет:
- docs/generated/MODULE_INDEX.md — документация из PropertyGraph
- README.md — tool count, языки, статус тестов
- KNOWN_ISSUES.md — синхронизация из AGENT_DIARY.md
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class BrokenRef:
    """Одна битая ссылка в документации."""
    file: str
    line: int
    reference: str
    suggestion: str = ""


class AutoDocUpdater:
    """Автоматическое обновление документации проекта.

    Usage:
        updater = AutoDocUpdater()
        report = updater.update_all("/path/to/project")
    """

    def __init__(self):
        self._doc_generator = None
        self._symbol_cache: Optional[Set[str]] = None

    # ─── Public API ────────────────────────────────────────

    def verify_references(self, project_root: str) -> str:
        """Проверяет code-референсы в .md документации на актуальность.

        Scans all .md files in docs/ (excluding generated/), extracts
        backtick-wrapped identifiers, and verifies each exists in src/.

        Returns:
            Отчёт: сколько файлов проверено, референсов найдено,
            сколько битых, с предложениями по фиксу.
        """
        root = Path(project_root).resolve()
        if not root.exists():
            return f"❌ Project root not found: {root}"

        start = datetime.now()
        broken = self._verify_doc_references(root)
        elapsed = (datetime.now() - start).total_seconds()

        # Статистика
        md_files = list(root.rglob("*.md"))
        doc_files = [f for f in md_files if "generated" not in f.parts]
        total_refs = self._count_references(doc_files)

        if not broken:
            return (
                f"✅ Doc reference check — {datetime.now().strftime('%H:%M:%S')}\n"
                f"📁 Checked {len(doc_files)} .md files, "
                f"{total_refs} code references, 0 broken.\n"
                f"⚡ {elapsed:.1f}s"
            )

        lines = [
            f"⚠️ Doc reference check — {datetime.now().strftime('%H:%M:%S')}",
            f"📁 Checked {len(doc_files)} .md files, "
            f"{total_refs} code references, {len(broken)} broken.",
            "",
            "📛 Broken references:",
        ]
        for b in broken[:20]:
            lines.append(f"  • `{b.reference}` in {b.file}:L{b.line}")
            if b.suggestion:
                lines.append(f"    💡 {b.suggestion}")
        if len(broken) > 20:
            lines.append(f"  ... +{len(broken) - 20} more")

        lines.extend([
            "",
            "📋 Fix suggestions:",
        ])
        # Группируем по файлам для удобных исправлений
        by_file: Dict[str, List[BrokenRef]] = {}
        for b in broken:
            by_file.setdefault(b.file, []).append(b)
        for file_path, refs in sorted(by_file.items()):
            refs_list = ", ".join(f"`{r.reference}`" for r in refs)
            lines.append(f"  • {file_path}: fix {refs_list}")

        lines.append(f"\n⚡ {elapsed:.1f}s")
        return "\n".join(lines)

    def update_all(self, project_root: str) -> str:
        """Запускает полное обновление документации.

        Args:
            project_root: Абсолютный путь к корню проекта.

        Returns:
            Отчёт: что обновлено, что пропущено, ошибки.
        """
        root = Path(project_root).resolve()
        if not root.exists():
            return f"❌ Project root not found: {root}"

        steps: List[str] = []
        errors: List[str] = []

        # Шаг 1: generate_docs
        try:
            doc_path = self._update_generated_docs(root)
            steps.append(f"✅ Module docs: {doc_path}")
        except Exception as e:
            errors.append(f"❌ Module docs: {e}")

        # Шаг 2: README.md
        try:
            readme_changed = self._update_readme(root)
            steps.append(f"✅ README.md: {'обновлён' if readme_changed else 'актуален'}")
        except Exception as e:
            errors.append(f"❌ README.md: {e}")

        # Шаг 3: KNOWN_ISSUES.md синхронизация
        try:
            known_changed = self._sync_known_issues(root)
            steps.append(f"✅ KNOWN_ISSUES.md: {'синхронизирован' if known_changed else 'актуален'}")
        except Exception as e:
            errors.append(f"❌ KNOWN_ISSUES.md: {e}")

        # Собираем отчёт
        report_lines = [
            f"📋 AutoDoc Update — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"📁 Проект: {root}",
            "",
            *steps,
        ]
        if errors:
            report_lines.extend(["", "⚠️ Ошибки:", *errors])

        report = "\n".join(report_lines)
        logger.info("AutoDoc update complete:\n%s", report)
        return report

    def check_staleness(self, project_root: str) -> str:
        """Проверяет, устарела ли документация, без изменений.

        Args:
            project_root: Абсолютный путь к корню проекта.

        Returns:
            Статус: актуально / что устарело.
        """
        root = Path(project_root).resolve()
        issues: List[str] = []

        # Проверка MODULE_INDEX.md
        doc_file = root / "docs" / "generated" / "MODULE_INDEX.md"
        if not doc_file.exists():
            issues.append("docs/generated/MODULE_INDEX.md не существует")
        else:
            age = datetime.now() - datetime.fromtimestamp(doc_file.stat().st_mtime)
            if age.days > 0 or age.seconds > 3600:
                issues.append(f"MODULE_INDEX.md старше 1ч ({age.seconds // 60}м)")

        # Проверка README tool count
        readme_path = root / "README.md"
        if readme_path.exists():
            text = readme_path.read_text(encoding="utf-8")
            actual_count = self._count_tools(root)
            if str(actual_count) not in text:
                issues.append(f"README.md: tool count устарел (ожидается {actual_count})")

        if not issues:
            return "✅ Документация актуальна"
        return "⚠️ Устарело:\n" + "\n".join(f"  • {i}" for i in issues)

    # ─── Internal: генерация docs ─────────────────────────

    def _update_generated_docs(self, root: Path) -> str:
        """Генерирует MODULE_INDEX.md."""
        from src.core.doc_generator import DocGenerator

        dg = DocGenerator()
        output_dir = str(root / "docs" / "generated")
        result = dg.generate(str(root), output_dir=output_dir)
        logger.info("Module docs generated: %s", result)
        return result

    # ─── Internal: обновление README.md ───────────────────

    def _count_tools(self, root: Path) -> int:
        """Считает количество MCP-инструментов по коду."""
        server_tools = root / "src" / "mcp" / "server_tools.py"
        if not server_tools.exists():
            return 0

        text = server_tools.read_text(encoding="utf-8")
        # Ищем паттерны регистрации инструментов
        tool_patterns = [
            r'@mcp\.tool\("',
            r'@mcp_app\.tool\("',
            r'name=name,',
            r'tool\(name=',
            r'class \w+Tool\b',
        ]
        count = 0
        for pattern in tool_patterns:
            count = max(count, text.count(pattern))
        return count

    def _update_readme(self, root: Path) -> bool:
        """Обновляет счетчики в README.md.

        Returns:
            True если были изменения.
        """
        readme_path = root / "README.md"
        if not readme_path.exists():
            return False

        text = readme_path.read_text(encoding="utf-8")

        # Собираем реальные метрики
        tool_count = self._count_tools(root)
        test_count = self._count_tests(root)
        lang_count = self._count_languages(root)

        # Обновляем tool count
        text = self._replace_between(
            text,
            "tools",
            str(tool_count),
        )

        # Обновляем test count (паттерн "N passed, 0 failed")
        test_match = re.search(r'\d+\s*passed', text)
        if test_match:
            old = test_match.group()
            new = f"{test_count} passed"
            if old != new:
                text = text.replace(old, new, 1)

        # Обновляем языки
        text = self._replace_between(
            text,
            "language",
            str(lang_count),
        )

        # Пишем только если были изменения
        old_text = readme_path.read_text(encoding="utf-8")
        if text != old_text:
            readme_path.write_text(text, encoding="utf-8")
            logger.info("README.md обновлён")
            return True
        return False

    def _count_tests(self, root: Path) -> int:
        """Считает количество тестовых функций."""
        tests_dir = root / "tests"
        if not tests_dir.exists():
            return 0
        count = 0
        for py_file in tests_dir.rglob("test_*.py"):
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            count += text.count("def test_")
            count += text.count("async def test_")
        return count

    def _count_languages(self, root: Path) -> int:
        """Считает поддерживаемые языки из parser.py."""
        parser_path = root / "src" / "core" / "indexing" / "parser.py"
        if not parser_path.exists():
            return 0
        text = parser_path.read_text(encoding="utf-8")
        # Ищем словарь LANGUAGES или PARSE_EXTENSIONS
        lang_match = re.search(r'LANGUAGES\s*=\s*\{([^}]+)\}', text, re.DOTALL)
        if lang_match:
            return lang_match.group(1).count(":") + 1
        return 0

    @staticmethod
    def _replace_between(text: str, marker: str, new_value: str) -> str:
        """Заменяет число после маркера."""
        pattern = rf'(\b{marker}[^\d]*?)(\d+)'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return text[:match.start(2)] + new_value + text[match.end(2):]
        return text

    # ─── Internal: синхронизация KNOWN_ISSUES.md ─────────

    def _sync_known_issues(self, root: Path) -> bool:
        """Синхронизирует KNOWN_ISSUES.md из AGENT_DIARY.md.

        Находит записи о багах/фиксах в AGENT_DIARY.md и добавляет
        их в KNOWN_ISSUES.md если их там ещё нет.
        """
        diary_path = root / "AGENT_DIARY.md"
        known_path = root / "KNOWN_ISSUES.md"

        if not diary_path.exists() or not known_path.exists():
            return False

        diary_text = diary_path.read_text(encoding="utf-8")
        known_text = known_path.read_text(encoding="utf-8")

        # Ищем записи об инцидентах в AGENT_DIARY
        new_entries: List[str] = []
        for match in re.finditer(
            r'## \[([^\]]+)\]\s*—\s*([^\n]+)\n(.*?)(?=\n## |\Z)',
            diary_text,
            re.DOTALL,
        ):
            date = match.group(1)
            title = match.group(2)
            body = match.group(3).strip()

            # Пропускаем если уже есть в KNOWN_ISSUES
            if title in known_text:
                continue
            # Пропускаем если не содержит информации о багах/фиксах
            if not any(kw in body.lower() for kw in ["fix", "баг", "bug", "исправлен"]):
                continue

            new_entries.append(
                f"\n## {date} — {title}\n\n"
                f"- **Источник:** AGENT_DIARY.md\n"
                f"- **Описание:** {body[:200]}...\n"
                f"- **Статус:** автоматически синхронизировано\n"
            )

        if not new_entries:
            return False

        # Добавляем новые записи перед последней строкой
        new_text = known_text.rstrip() + "\n" + "\n".join(new_entries) + "\n"
        known_path.write_text(new_text, encoding="utf-8")
        logger.info("KNOWN_ISSUES.md: добавлено %d записей", len(new_entries))
        return True

    # ─── Internal: верификация code-референсов в .md ──────

    _EXCLUDE_DIRS = {".git", "__pycache__", "venv", ".venv", "node_modules", ".codebase_indices"}

    # Паттерны для пропуска: не являются code-символами
    _EXCLUDE_PATTERNS = {
        # ENV переменные (UPPER_CASE с подчёркиваниями, иногда с точками)
        r'^[A-Z][A-Z0-9_]{2,}(\.[A-Z][A-Z0-9_]*)*$',
        # SQL таблицы/поля (заканчиваются на _fts, _idx и т.д.)
        r'^[a-z_]+_fts$',
        r'^[a-z_]+_idx$',
        r'^[a-z_]+_table$',
        # Файловые пути (содержат / или \ или {})
        r'.*[\\/{].*',
        r'.*\{[a-z_]+\}.*',
        # Файлы с расширениями (.py, .log, .md, .json, .exe, .dll)
        r'.*\.(py|log|md|json|exe|dll|bat|txt|yml|yaml|toml|cfg|env|gguf|onnx)$',
        # Декораторы (@something)
        r'^@[a-zA-Z_][a-zA-Z0-9_.]*$',
        # GitHub-style user/repo references
        r'^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$',
        # Версии (semver, X.Y.Z)
        r'^\d+\.\d+(\.\d+)?[a-zA-Z0-9]*$',
        # Порты (8080, 8081)
        r'^\d{4,5}$',
        # Символы с точкой: если начинаются с модуля вне проекта (asyncio, lancedb)
    }

    # Известные внешние библиотеки/модули — их символы не в нашем src/
    _EXTERNAL_MODULES = {
        'asyncio', 'json', 'os', 'sys', 're', 'math', 'time', 'datetime',
        'pathlib', 'typing', 'collections', 'functools', 'itertools',
        'logging', 'subprocess', 'threading', 'multiprocessing',
        'hashlib', 'uuid', 'tempfile', 'shutil', 'glob', 'argparse',
        'dataclasses', 'abc', 'enum', 'io', 'textwrap', 'contextlib',
        'inspect', 'traceback', 'pickle', 'socket', 'http', 'urllib',
        'queue', 'copy', 'random', 'statistics', 'base64', 'struct',
        'platform', 'ctypes', 'importlib', 'pkgutil', 'warnings',
        'signal', 'weakref', 'types', 'bisect', 'heapq', 'pprint',
        # Внешние зависимости проекта
        'lancedb', 'onnxruntime', 'httpx', 'fastmcp', 'pydantic',
        'pyarrow', 'numpy', 'tree_sitter', 'lz4', 'zstandard', 'pytest',
    }

    _STDLIB_SYMBOLS = {
        # Python builtins
        "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
        "callable", "chr", "classmethod", "compile", "complex", "delattr",
        "dict", "dir", "divmod", "enumerate", "eval", "exec", "filter",
        "float", "format", "frozenset", "getattr", "globals", "hasattr",
        "hash", "hex", "id", "input", "int", "isinstance", "issubclass",
        "iter", "len", "list", "locals", "map", "max", "memoryview",
        "min", "next", "object", "oct", "open", "ord", "pow", "print",
        "property", "range", "repr", "reversed", "round", "set",
        "setattr", "slice", "sorted", "staticmethod", "str", "sum",
        "super", "tuple", "type", "vars", "zip",
        # Common stdlib / pathlib methods
        "mkdir", "sleep", "read_text", "write_text", "read_bytes",
        "write_bytes", "exists", "is_dir", "is_file", "iterdir",
        "glob", "rglob", "unlink", "rmdir", "rename", "resolve",
        "relative_to", "with_suffix", "with_name", "parent", "name",
        "stem", "suffix", "cwd", "home", "stat", "lstat", "chmod",
        "joinpath", "samefile", "absolute", "as_posix", "as_uri",
        # Common asyncio functions used in docs
        "ensure_future", "create_task", "gather", "wait", "run",
        "run_coroutine_threadsafe", "get_event_loop", "get_running_loop",
        "new_event_loop", "set_event_loop", "all_tasks", "current_task",
        "shield", "sleep", "wait_for", "timeout",
        # Common lancedb classes used in docs
        "LanceError", "LanceTable", "LanceDataset",
        # Common pathlib functions used in docs
        "Path", "PurePath", "PurePosixPath", "PureWindowsPath",
        "PosixPath", "WindowsPath",
    }

    def _build_symbol_set(self, root: Path) -> Set[str]:
        """Строит множество всех определённых символов из src/.

        Собирает:
        - def function_names
        - class ClassNames
        - async def function_names
        - MCP tool names (@mcp.tool("name") или @mcp_app.tool("name"))
        - Class-based MCP tools (tool_name="...")
        - Из импортов: module.submodule (для Module.method ссылок)
        """
        if self._symbol_cache is not None:
            return self._symbol_cache

        symbols: Set[str] = set()
        src_dir = root / "src"
        if not src_dir.exists():
            self._symbol_cache = symbols
            return symbols

        for py_file in src_dir.rglob("*.py"):
            rel = str(py_file.relative_to(root))
            parts = Path(rel).parts
            if any(d in parts for d in self._EXCLUDE_DIRS):
                continue
            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            # 1. def / async def / class names
            for m in re.finditer(
                r'(?:^|\n)\s*(?:async\s+)?(?:def|class)\s+([a-zA-Z_][a-zA-Z0-9_]*)',
                text,
            ):
                symbols.add(m.group(1))

            # 2. MCP tool names: @mcp.tool("name") / @mcp_app.tool("name")
            for m in re.finditer(r'@\w+\.tool\("([a-z_][a-z0-9_]+)"\)', text):
                symbols.add(m.group(1))

            # 3. Class-based MCP tools: tool_name="name" in super().__init__
            for m in re.finditer(r'tool_name="([a-z_][a-z0-9_]+)"', text):
                symbols.add(m.group(1))

            # 4. Module-level assignments (CONSTANT, global vars used in docs)
            for m in re.finditer(
                r'(?:^|\n)([A-Z][A-Z0-9_]+)\s*=',
                text,
            ):
                symbols.add(m.group(1))

            # 5. Named submodules from imports: import x.y.z or from x import y
            for m in re.finditer(
                r'^import\s+([a-zA-Z_][a-zA-Z0-9_.]*)',
                text,
                re.MULTILINE,
            ):
                parts = m.group(1).split(".")
                # Добавляем module.submodule для dot-refs
                for i in range(1, len(parts) + 1):
                    symbols.add(".".join(parts[:i]))

            for m in re.finditer(
                r'^from\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+import',
                text,
                re.MULTILINE,
            ):
                parts = m.group(1).split(".")
                for i in range(1, len(parts) + 1):
                    symbols.add(".".join(parts[:i]))

        self._symbol_cache = symbols
        logger.debug("Symbol cache built: %d symbols", len(symbols))
        return symbols

    @staticmethod
    def _extract_doc_references(text: str) -> List[Tuple[str, int, str]]:
        """Извлекает code-референсы из Markdown-текста.

        Returns:
            Список (reference, line_number, full_match)
        """
        refs: List[Tuple[str, int, str]] = []
        lines = text.split("\n")
        in_code_block = False

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            # Пропускаем fenced code blocks
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue

            # Извлекаем всё внутри обратных кавычек: `identifier`
            for m in re.finditer(r'`([^`]+)`', line):
                raw = m.group(1).strip()

                # Пропускаем пустые, URL
                if not raw or len(raw) < 2:
                    continue
                if raw.startswith("http://") or raw.startswith("https://"):
                    continue
                if " " in raw:
                    continue

                # Отбрасываем file paths: содержат / или \ и file extension
                if ("/" in raw or "\\" in raw) and "." in raw:
                    continue

                # Отбрасываем Windows drive paths: C:\..., D:\...
                if re.match(r'^[A-Za-z]:\\', raw):
                    continue

                # Отбрасываем относительные/абсолютные Unix пути
                if raw.startswith("/") or raw.startswith("./"):
                    continue

                # Отбрасываем если это явно file path без расширения (содержит слеши)
                if "/" in raw or "\\" in raw:
                    continue

                # Чистим аргументы функций: `func_name(arg1)` → `func_name`
                if "(" in raw:
                    content = raw[:raw.index("(")].strip()
                else:
                    content = raw

                # Убираем $ префикс для env vars: `$VAR_NAME` → `VAR_NAME`
                if content.startswith("$"):
                    content = content[1:]
                    # Пропускаем shell-style env vars: `$ZED_WORKTREE_ROOT`
                    if content.isupper() and len(content) > 2:
                        continue

                # === Hard filters: reject non-code patterns ===

                # IP addresses: 127.0.0.1
                if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', content):
                    continue

                # IP:port: 0.0.0.0:8080
                if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$', content):
                    continue

                # File extensions (.py, .md, .json, .toml, .exe, .yml, .yaml, .txt, .cfg, .ini)
                # — но НЕ Class.method (part после . начинается с буквы, не с 2-3char ext)
                _file_exts = {"py", "md", "json", "toml", "exe", "yml", "yaml", "txt", "cfg", "ini", "env", "gitignore", "lock"}
                if "." in content and not content.startswith("."):
                    last_part = content.rsplit(".", 1)[1]
                    if last_part in _file_exts:
                        continue

                # Contains = (config assignment: PROVIDER=something)
                if "=" in content:
                    continue

                # Contains + (hotkey: Ctrl+Shift+P)
                if "+" in content:
                    continue

                # Contains - or digits-heavy: version tags, model names (bge-m3-Q4_K_M)
                if content.count("-") > 1 and any(c.isdigit() for c in content):
                    continue

                # Starts with digit: 3proxy, 4workers
                if content[0].isdigit():
                    continue

                # Looks like semver: 3.3.9
                if re.match(r'^\d+\.\d+\.\d+', content):
                    continue

                # === Positive filter: only "likely code identifiers" ===
                if not any([
                    "_" in content,
                    "." in content,
                    content[0].isupper() and content[0].isalpha(),
                    len(content) > 5 and content[0].islower() and any(c.isupper() for c in content[1:]),
                    content.isupper() and len(content) > 1,
                ]):
                    continue

                # Отбрасываем стоп-слова
                if content.lower() in {"is", "in", "on", "at", "to", "for", "by", "of", "or", "and", "not", "no", "if"}:
                    continue

                refs.append((content, line_num, m.group(0)))

        return refs

    def _verify_doc_references(self, root: Path) -> List[BrokenRef]:
        """Проверяет все code-референсы в .md файлах docs/.

        Returns:
            Список BrokenRef с битыми ссылками.
        """
        doc_dir = root / "docs"
        if not doc_dir.exists():
            logger.warning("docs/ directory not found at %s", doc_dir)
            return []

        # Строим кэш символов
        symbols = self._build_symbol_set(root)

        broken: List[BrokenRef] = []

        for md_file in sorted(doc_dir.rglob("*.md")):
            rel = str(md_file.relative_to(root))
            parts = Path(rel).parts

            # Пропускаем generated/
            if "generated" in parts:
                continue

            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.debug("Skip unreadable %s: %s", md_file.name, e)
                continue

            for ref_name, line_num, full_match in self._extract_doc_references(text):
                if self._is_reference_valid(ref_name, symbols):
                    continue

                suggestion = self._find_suggestion(ref_name, symbols)
                broken.append(BrokenRef(
                    file=rel,
                    line=line_num,
                    reference=ref_name,
                    suggestion=suggestion,
                ))

        return broken

    def _is_reference_valid(self, ref_name: str, symbols: Set[str]) -> bool:
        """Проверяет, существует ли референс в множестве символов.

        Пропускает:
        - stdlib/builtin имена
        - Внешние библиотеки (lancedb, onnxruntime, asyncio...)
        - ENV переменные (UPPER_CASE)
        - SQL таблицы/поля (_fts, _idx)
        - Файловые пути, декораторы, версии
        - Dot-ссылки: если первый компонент — внешний модуль
        """
        # Пропускаем по паттернам
        import re
        for pattern in self._EXCLUDE_PATTERNS:
            if re.match(pattern, ref_name):
                return True

        # Пропускаем stdlib/builtin имена
        if ref_name.lower() in self._STDLIB_SYMBOLS:
            return True

        # Пропускаем Python keywords
        if ref_name in {"True", "False", "None", "self", "cls", "super", "property"}:
            return True

        # Пропускаем self.x / cls.x — атрибуты экземпляра/класса
        if ref_name.startswith("self.") or ref_name.startswith("cls."):
            return True

        # Dot-ссылки: Module.attr — проверяем первый сегмент
        if "." in ref_name:
            parts = ref_name.split(".")
            # Если первый компонент — внешний модуль → пропускаем
            if parts[0].lower() in self._EXTERNAL_MODULES:
                return True
            # Проверяем каждый FQN уровень
            for i in range(len(parts), 0, -1):
                fqn = ".".join(parts[:i])
                if fqn in symbols:
                    return True
            # Fallback: проверяем последнюю часть (method name)
            last = parts[-1]
            if last in symbols:
                return True
            return False

        return ref_name in symbols

    def _find_suggestion(self, ref_name: str, symbols: Set[str]) -> str:
        """Ищет похожие символы для предложения замены."""
        # Fuzzy match: same prefix/suffix
        candidates = []
        lower_ref = ref_name.lower()
        for sym in symbols:
            lower_sym = sym.lower()
            # Same prefix (first 4 chars)
            if len(lower_ref) > 3 and lower_sym.startswith(lower_ref[:4]):
                candidates.append(sym)
            # Contains the ref name as substring
            elif lower_ref in lower_sym and len(sym) > len(ref_name):
                candidates.append(sym)

        # Sort by similarity
        candidates.sort(key=lambda x: abs(len(x) - len(ref_name)))
        if candidates:
            return f"Возможно, имелось в виду: `{candidates[0]}`"
        return ""

    def _count_references(self, md_files: List[Path]) -> int:
        """Считает общее количество code-референсов в .md файлах.

        Используется только для статистики в отчёте, без верификации.
        """
        total = 0
        for md_file in md_files:
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            refs = self._extract_doc_references(text)
            total += len(refs)
        return total
