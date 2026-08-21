"""
Doc Generator — генерация Markdown-документации из исходников (не из графа).

Для любого проекта (не только MSCodeBase):
  1. Сканирует .py файлы через CodeParser (skip build-каталогов + .gitignore)
  2. Извлекает символы (функции/классы) и их вызовы
  3. Генерирует Markdown-таблицу: файл → символы → callers → callees

Usage:
    from src.core.doc_generator import DocGenerator
    md = DocGenerator().generate("/path/to/project")
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DocGenerator:
    """Генератор Markdown-документации из AST-графа любого проекта."""

    def __init__(self):
        self._parser = None
        self._symbol_index = None

    def _get_parser(self):
        """Ленивая инициализация CodeParser."""
        if self._parser is None:
            from src.core.indexing.parser import CodeParser
            self._parser = CodeParser()
        return self._parser

    def _get_callees_for_file(self, file_path: Path) -> Dict[str, List[str]]:
        """Извлекает callees для каждого символа в файле."""
        parser = self._get_parser()
        try:
            calls = parser.extract_calls(file_path)
        except Exception:
            return {}

        callees: Dict[str, List[str]] = {}
        for c in calls:
            caller = c.get("caller", "")
            callee = c.get("callee", "")
            if not caller or not callee:
                continue
            if caller not in callees:
                callees[caller] = []
            if callee not in callees[caller]:
                callees[caller].append(callee)
        return callees

    @staticmethod
    def _md_cell(text: str, max_len: int = 200) -> str:
        """Экранирует значение для ячейки Markdown-таблицы.

        Заменяет `|` на литеральные `\\|`, склеивает переводы строк пробелом,
        обрезает до max_len символов.
        """
        collapsed = " ".join(text.splitlines()).strip()
        if len(collapsed) > max_len:
            collapsed = collapsed[: max_len - 3].rstrip() + "..."
        return collapsed.replace("|", "\\|")

    def _build_callers_index(
        self, all_files: List[Path]
    ) -> Dict[str, List[str]]:
        """Строит обратный индекс: символ → кто его вызывает."""
        callers: Dict[str, List[str]] = {}
        for fp in all_files:
            callees = self._get_callees_for_file(fp)
            for caller, clist in callees.items():
                for callee in clist:
                    if callee not in callers:
                        callers[callee] = []
                    if caller not in callers[callee]:
                        callers[callee].append(caller)
        return callers

    def generate(self, project_root: str, output_dir: Optional[str] = None) -> str:
        """Генерирует Markdown-документацию для проекта.

        Args:
            project_root: Путь к корню проекта.
            output_dir: Если указан — сохраняет .md файлы сюда (по одному на директорию).

        Returns:
            Markdown-строка (если output_dir не указан) или имя файла.
        """
        root = Path(project_root).resolve()
        if not root.exists():
            raise FileNotFoundError(f"Project root not found: {root}")

        # Собираем все .py файлы
        py_files = sorted(root.rglob("*.py"))
        # Фильтруем служебные директории: список синхронизирован с
        # SymbolIndex._should_skip_dir (build-артефакты dist/build/target и пр.) —
        # иначе те же файлы попадали в docs/ сгенерированными дважды
        # (инцидент infrawise 2026-08-16: dist/context/scanner.py == src/...).
        skip_dirs = {
            ".git", "__pycache__", "venv", ".venv", "node_modules",
            ".codebase_indices", "dist", "build", "target", ".tox",
            ".mypy_cache", ".pytest_cache", ".ruff_cache",
        }
        py_files = [
            f for f in py_files
            if not any(d in f.parts for d in skip_dirs)
        ]
        # Уважаем .gitignore (как FileGuard): dist/ и пр. build-артефакты,
        # исключённые владельцем проекта, не исходники. Сломанный .gitignore
        # не должен ронять генерацию — fail-open.
        try:
            from src.core.gitignore_parser import (
                is_file_excluded_by_gitignore,
                load_gitignore_patterns,
            )

            gi_patterns = load_gitignore_patterns(root)
            if gi_patterns:
                py_files = [
                    f for f in py_files
                    if not is_file_excluded_by_gitignore(f, root, gi_patterns)
                ]
        except Exception:  # noqa: BLE001 - fail-open
            pass

        if not py_files:
            return "# Doc Generator\n\nNo Python files found."

        # Строим callers-индекс по всем файлам
        callers_index = self._build_callers_index(py_files)

        # Группируем файлы по директориям
        from collections import defaultdict
        dirs: Dict[str, List[Path]] = defaultdict(list)
        for fp in py_files:
            rel = fp.relative_to(root)
            dir_name = str(rel.parent) if rel.parent != "." else "root"
            dirs[dir_name].append(fp)

        # Генерируем Markdown по директориям
        parts: List[str] = []
        for dir_name in sorted(dirs.keys()):
            files = dirs[dir_name]
            parts.append(f"# {dir_name}\n")
            parts.append(f"\nTotal: {len(files)} files\n")

            for fp in files:
                rel = fp.relative_to(root)
                # Извлекаем символы
                parser = self._get_parser()
                ext = fp.suffix.lower()
                if ext not in parser.parsers:
                    continue

                try:
                    _, symbols = parser._parse_with_tree_sitter(fp, ext)
                except Exception:
                    continue

                if not symbols:
                    continue

                # Callees для этого файла
                callees = self._get_callees_for_file(fp)

                parts.append(f"\n## {rel}\n")
                parts.append(
                    "| Symbol | Kind | Signature | Description | Line | Callers | Callees |\n"
                )
                parts.append(
                    "|--------|------|-----------|-------------|------|---------|--------|\n"
                )

                for s in symbols[:20]:  # макс 20 символов на файл
                    name = s["name"]
                    kind = s.get("kind", "?").replace("_", " ")
                    signature = self._md_cell(s.get("signature") or "")
                    desc = self._md_cell(s.get("docstring") or "", max_len=100)
                    line = s["line"]
                    c_list = callers_index.get(name, [])
                    callers_str = ", ".join(c_list[:5]) if c_list else "—"
                    callee_list = callees.get(name, [])
                    callees_str = ", ".join(callee_list[:5]) if callee_list else "—"
                    parts.append(
                        f"| `{name}` | {kind} | {signature} | {desc} | {line} "
                        f"| {callers_str} | {callees_str} |\n"
                    )

                if len(symbols) > 20:
                    parts.append(
                        f"| ... и ещё {len(symbols) - 20} символов | | | | | | |\n"
                    )

            parts.append("\n---\n")

        md = "".join(parts)

        if output_dir:
            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            filepath = out_path / "MODULE_INDEX.md"
            filepath.write_text(md, encoding="utf-8")
            logger.info(f"DocGenerator: saved to {filepath}")
            return str(filepath)

        return md
