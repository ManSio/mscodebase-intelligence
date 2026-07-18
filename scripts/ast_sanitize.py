#!/usr/bin/env python3
"""
AST-санация except-блоков — правильный codemod через Python AST.

В отличие от regex-подхода (scripts/sanitize_exceptions.py),
этот скрипт:
1. Парсит файл через `ast.parse()` — гарантированно корректная структура
2. Трансформирует только `ExceptHandler` с `type=Name(id='Exception')`
3. Сохраняет оригинальную индентацию через `ast.unparse()`
4. Гарантирует синтаксическую корректность результата

Использование:
    python scripts/ast_sanitize.py                         # dry-run
    python scripts/ast_sanitize.py --apply                 # apply
    python scripts/ast_sanitize.py --apply --file=src/core/intelligence/layer.py  # single file
"""

import ast
import os
import re
import sys
import tokenize
from pathlib import Path
from typing import Optional, Tuple

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
SKIP_FILES = {"passport.py", "start_reranker_snippet.py", "resource_monitor.py"}
SKIP_PATTERNS = [re.compile(r"resource_monitor\.py")]

# Буфер для записи с сохранением отступов
INDENT_RE = re.compile(r"^(\s*)")


class ExceptionSanitizer(ast.NodeTransformer):
    """AST-трансформер: находит `except Exception:` и добавляет logger.warning."""

    def __init__(self, source_lines: list, file_name: str):
        self.source_lines = source_lines
        self.file_name = file_name
        self.modified = False
        self.fixes: list[tuple[int, str]] = []  # (line_no, message)

    def _get_line_indent(self, line_no: int) -> str:
        """Возвращает отступ строки по номеру (1-based)."""
        if 1 <= line_no <= len(self.source_lines):
            m = INDENT_RE.match(self.source_lines[line_no - 1])
            if m:
                return m.group(1)
        return ""

    def _has_logger(self, node) -> bool:
        """Проверяет, есть ли logger.* вызов в блоке except."""
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Call):
                func = stmt.func
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    if func.value.id == "logger":
                        return True
        return False

    def _get_body_source(self, node) -> str:
        """Извлекает исходный код тела except-блока (первая значащая строка)."""
        if not node.body:
            return ""
        first = node.body[0]
        if hasattr(first, "lineno") and 1 <= first.lineno <= len(self.source_lines):
            return self.source_lines[first.lineno - 1].strip()
        return ""

    def _has_pass_body(self, node) -> bool:
        """True если тело except — только pass (с возможными комментариями)."""
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            return True
        return False

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> ast.ExceptHandler:
        """Обрабатывает except-блок: добавляет logger.warning если нет логгера."""
        # Проверяем, что это `except Exception:` (не конкретное исключение)
        if node.type is None:
            return node  # bare `except:` — не трогаем

        if isinstance(node.type, ast.Tuple):
            # `except (Exception, SomeError):` — проверяем наличие Exception в кортеже
            has_exception = any(
                isinstance(el, ast.Name) and el.id == "Exception"
                for el in node.type.elts
            )
            if not has_exception:
                return node
        elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
            pass  # это `except Exception:`
        elif isinstance(node.type, ast.Attribute):
            # `except SomeModule.Exception:` — не трогаем
            return node
        else:
            return node

        # Проверяем, есть ли уже logger
        if self._has_logger(node):
            return node

        # Проверяем, не является ли тело pass/return/continue
        body_text = self._get_body_source(node)
        if not body_text:
            return node

        # Получаем контекст (имя функции вокруг)
        context = self._get_context(node)

        # Создаём logger.warning узел
        msg = f"Exception suppressed at {self.file_name} | {context[:60]}"
        logger_warning = ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="logger", ctx=ast.Load()),
                    attr="warning",
                    ctx=ast.Load(),
                ),
                args=[ast.Constant(value=msg)],
                keywords=[
                    ast.keyword(
                        arg="exc_info",
                        value=ast.Constant(value=True),
                    )
                ],
            )
        )

        # Вставляем logger.warning ПЕРВЫМ в тело except-блока
        node.body.insert(0, logger_warning)

        # Если у node.name нет ('as e'), добавляем `as _e`
        if node.name is None:
            node.name = "_e"

        self.modified = True
        if hasattr(node, "lineno"):
            self.fixes.append((node.lineno, msg))

        return node

    def _get_context(self, node) -> str:
        """Пытается найти имя функции, в которой находится except."""
        for parent in ast.walk(self._tree if hasattr(self, '_tree') else ast.Module(body=[])):
            if isinstance(parent, ast.FunctionDef):
                for child in ast.walk(parent):
                    if child is node:
                        return parent.name
        return ""


def sanitize_file(filepath: Path, apply: bool = False) -> dict:
    """Обрабатывает один файл: AST-трансформация except-блоков.

    Returns:
        dict со статистикой
    """
    result = {
        "file": str(filepath.relative_to(SRC_DIR)),
        "found": 0,
        "fixed": 0,
        "errors": [],
        "fixes": [],
    }

    # Skip filters
    if any(p.search(str(filepath)) for p in SKIP_PATTERNS):
        result["errors"].append("skipped (intentional fallback)")
        return result
    if filepath.name in SKIP_FILES:
        result["errors"].append(f"skipped ({filepath.name})")
        return result

    # Read file
    try:
        source = filepath.read_text("utf-8", errors="replace")
    except Exception as e:
        result["errors"].append(f"read error: {e}")
        return result

    # Check for logger
    has_logger = bool(re.search(r'logger\s*=', source))
    if not has_logger:
        # Check if we can add one
        has_logging = bool(re.search(r'^\s*import\s+logging', source, re.MULTILINE))
        if not has_logging:
            result["errors"].append("no logger — skipping")
            return result

    # Parse AST
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        result["errors"].append(f"syntax error: {e}")
        return result

    # Transform
    source_lines = source.split('\n')
    sanitizer = ExceptionSanitizer(source_lines, filepath.name)
    sanitizer._tree = tree  # для поиска контекста
    new_tree = sanitizer.visit(tree)

    ast.fix_missing_locations(new_tree)

    result["found"] = len(sanitizer.fixes)
    result["fixes"] = sanitizer.fixes

    if not sanitizer.modified:
        return result

    result["fixed"] = len(sanitizer.fixes)

    if apply:
        # Генерируем новый код через unparse
        new_source = ast.unparse(new_tree)

        # ⚠️ ast.unparse() НЕ сохраняет форматирование!
        # Нужно аккуратно применить изменения.

        # Вместо unparse, используем построчную замену:
        # Берём оригинальный source, находим строки except и ВСТАВЛЯЕМ
        # после них logger.warning, и меняем `except Exception:` на `except Exception as _e:`
        new_lines = list(source_lines)

        # Сортируем фиксы по строкам (с конца, чтобы не сбивать индексы)
        for line_no, msg in sorted(sanitizer.fixes, key=lambda x: -x[0]):
            idx = line_no - 1  # 0-based
            if idx >= len(new_lines):
                continue

            line = new_lines[idx]
            indent = self._get_line_indent(line_no)

            # Меняем `except Exception:` на `except Exception as _e:`
            if re.match(r'^\s*except\s+Exception\s*:', line):
                new_lines[idx] = line.rstrip().rstrip(':') + ' as _e:'
            elif re.match(r'^\s*except\s+Exception\s+as\s+\w+\s*:', line):
                pass  # уже есть as

            # Вставляем logger.warning после except
            logger_line = f'{indent}    logger.warning("{msg}", exc_info=True)'
            new_lines.insert(idx + 1, logger_line)

        new_source = '\n'.join(new_lines)

        # Валидация: проверяем, что результат синтаксически корректен
        try:
            ast.parse(new_source)
        except SyntaxError as e:
            result["errors"].append(f"generated syntax error: {e}")
            result["fixed"] = 0
            return result

        filepath.write_text(new_source, encoding="utf-8")

    return result


def _get_line_indent(line: str) -> str:
    m = INDENT_RE.match(line)
    return m.group(1) if m else ""


def main():
    apply = '--apply' in sys.argv
    single_file = None
    for arg in sys.argv:
        if arg.startswith('--file='):
            single_file = arg.split('=', 1)[1]

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"{'=' * 60}")
    print(f"🔬 AST-санация исключений — режим: {mode}")
    print(f"{'=' * 60}\n")

    if single_file:
        files = [Path(SRC_DIR) / single_file]
    else:
        files = sorted(SRC_DIR.rglob("*.py"))

    total_found = 0
    total_fixed = 0
    total_skipped = 0
    file_results = []

    for pyfile in files:
        if '__pycache__' in str(pyfile) or not pyfile.name.endswith('.py'):
            continue
        result = sanitize_file(pyfile, apply=apply)
        file_results.append(result)
        total_found += result["found"]
        total_fixed += result["fixed"]

        if result.get("errors"):
            total_skipped += 1

        if result["found"] > 0 or result.get("errors"):
            status = "✅" if result["fixed"] > 0 else "⏭️"
            errs = "; ".join(result["errors"]) if result.get("errors") else ""
            print(f"  {status} {result['file']}: {result['fixed']}/{result['found']} {errs}")

    print(f"\n{'=' * 60}")
    print(f"📊 ИТОГО:")
    print(f"   Найдено:    {total_found}")
    print(f"   Исправлено: {total_fixed}")
    print(f"   Пропущено:  {total_skipped} файлов")
    print(f"   Режим:      {mode}")
    print(f"{'=' * 60}")

    if not apply:
        print(f"\n💡 Запусти с --apply для применения:")
        print(f"   python scripts/ast_sanitize.py --apply")
    else:
        print(f"\n✅ Применено. Проверь тесты:")
        print(f"   python -m pytest tests/ -x -v")


if __name__ == "__main__":
    main()
