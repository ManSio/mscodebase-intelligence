#!/usr/bin/env python3
"""
Скрипт «Иммунизация» — Фаза 1 Операции «Санация».

Заменяет немые `except Exception: pass` на логируемые конструкции,
чтобы вскрыть реальные ошибки, скрытые за 133 silent pass-блоками.

Логика замены:
  - `except Exception: pass` → `except Exception as _e: logger.warning("...: %s", _e)` + `pass`
  - `except Exception: return X` → аналогично + return
  - `except Exception: continue` → аналогично + continue

НЕ трогает:
  - Файлы, где уже есть `logger.*` в блоке except
  - `passport.py` (нет логгера)
  - `start_reranker_snippet.py` (нет логгера)
  - `base.py` (нет логгера)

Использование:
    python scripts/sanitize_exceptions.py          # preview (dry-run)
    python scripts/sanitize_exceptions.py --apply   # реальное применение
"""

import ast
import os
import re
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"

# Паттерны: ищем except с pass/return/continue на следующей строке
EXCEPT_RE = re.compile(
    r'^(\s+)except\s+Exception\s*(?:as\s+\w+)?\s*:\s*$',
    re.MULTILINE,
)

# Файлы, которые СКЛЕИВАЕМ (нет логгера или intentional fallback)
SKIP_FILES = {
    "passport.py",
    "start_reranker_snippet.py",
}

# Файлы, где except — intentional fallback chain (не трогать)
SKIP_PATTERNS = [
    r"resource_monitor\.py",  # 3-уровневый fallback получения RAM
]

# Файлы, которые нужно обработать особым способом (добавить импорт logging)
FILES_NEED_IMPORT = {
    "base.py",        # есть except, но нет logger — добавим
}


def file_has_logger(filepath: Path) -> bool:
    """Проверяет, есть ли logger = logging.getLogger(...) в файле."""
    content = filepath.read_text("utf-8", errors="replace")
    return bool(re.search(r'logger\s*=\s*(?:logging\.getLogger|get_logger)', content))


def add_logger_import(content: str) -> str:
    """Добавляет `logger = logging.getLogger(__name__)` если нет ни logger, ни logging."""
    if not re.search(r'^import\s+logging', content, re.MULTILINE):
        content = "import logging\n" + content
    if not re.search(r'logger\s*=\s*logging\.getLogger', content):
        # Вставляем после последнего import
        lines = content.split('\n')
        last_import = 0
        for i, line in enumerate(lines):
            if line.startswith('import ') or line.startswith('from '):
                last_import = i
        indent = ""
        lines.insert(last_import + 1, f'{indent}logger = logging.getLogger(__name__)')
        content = '\n'.join(lines)
    return content


def get_context_before(content: str, pos: int, context_lines: int = 3) -> str:
    """Возвращает контекст перед позицией для осмысленного сообщения."""
    lines = content[:pos].split('\n')
    context = []
    for line in lines[-context_lines:]:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            # Берём первые 60 символов функции/вызова
            short = stripped[:60]
            if short:
                context.append(short)
    return ' | '.join(context[-2:]) if context else 'unknown'


def process_file(filepath: Path, apply: bool = False) -> dict:
    """Обрабатывает один файл: находит и заменяет немые except.

    Returns:
        dict со статистикой по файлу
    """
    result = {"file": str(filepath.relative_to(SRC_DIR.parent)), "found": 0, "fixed": 0, "errors": []}

    if any(p.search(str(filepath)) for p in [re.compile(sk) for sk in SKIP_PATTERNS]):
        result["errors"].append("skipped (intentional fallback)")
        return result

    if filepath.name in SKIP_FILES:
        result["errors"].append(f"skipped ({filepath.name})")
        return result

    content = filepath.read_text("utf-8", errors="replace")
    
    # Проверяем, есть ли логгер, и добавляем если нужно
    has_logger = file_has_logger(filepath)
    if not has_logger and filepath.name in FILES_NEED_IMPORT:
        if apply:
            content = add_logger_import(content)
        has_logger = True

    if not has_logger:
        result["errors"].append("no logger — skipping")
        return result

    lines = content.split('\n')
    modified = False
    fixes = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Ищем `except Exception:` или `except Exception as X:`
        m = re.match(r'^(\s*)except\s+Exception(\s+as\s+\w+)?\s*:\s*$', stripped)
        if not m:
            i += 1
            continue

        indent = m.group(1)
        except_var = m.group(2) or ' as _e'
        if not except_var.strip():
            except_var = ' as _e'

        # Смотрим следующие строки
        j = i + 1
        next_lines = []
        while j < len(lines) and (not lines[j].strip() or lines[j].startswith(('#',))):
            next_lines.append(j)
            j += 1

        if j >= len(lines):
            i += 1
            continue

        next_line = lines[j]
        next_stripped = next_line.strip()

        # Определяем действие после except
        if next_stripped.startswith('pass') or next_stripped.startswith('return') or next_stripped.startswith('continue'):
            action = next_stripped.split()[0]
            
            # Проверяем, не логируется ли уже ошибка
            has_log = False
            for k in range(i + 1, min(j + 1, len(lines))):
                if 'logger.' in lines[k] or 'logging.' in lines[k]:
                    has_log = True
                    break

            if has_log:
                i += 1
                continue

            # Контекст для сообщения
            ctx = get_context_before(content, content.find(line) if line in content else 0)
            msg = f"Exception suppressed at {filepath.name} | {ctx[:60]}"

            # Добавляем logger.warning перед pass/return/continue
            logger_line = f"{indent}logger.warning(\"{msg}\")"
            lines.insert(j, logger_line)
            
            # Меняем except на именованную переменную
            lines[i] = line.rstrip()
            if 'as ' not in stripped:
                lines[i] = lines[i].rstrip(':') + f' as _e:'

            result["found"] += 1
            result["fixed"] += 1
            fixes.append((i, msg))
            modified = True
            i = j + 2  # Пропускаем вставленную строку
            continue
        else:
            # Другое действие — не трогаем, если нет logger, добавляем предупреждение
            has_log = False
            for k in range(i + 1, min(j + 2, len(lines))):
                if 'logger.' in lines[k] or 'logging.' in lines[k]:
                    has_log = True
                    break
            
            if not has_log:
                # Добавляем logger.warning с exc_info=True
                ctx = get_context_before(content, content.find(line) if line in content else 0)
                msg = f"Exception caught at {filepath.name} | {ctx[:60]}"
                logger_line = f"{indent}logger.warning(\"{msg}\", exc_info=True)"
                lines.insert(i + 1, logger_line)
                
                if 'as ' not in stripped:
                    lines[i] = lines[i].rstrip(':') + f' as _e:'

                result["found"] += 1
                result["fixed"] += 1
                fixes.append((i, msg))
                modified = True
                i = j + 2
                continue

        i += 1

    if modified and apply:
        filepath.write_text('\n'.join(lines), encoding="utf-8")

    result["fixes"] = fixes
    return result


def main():
    apply = '--apply' in sys.argv
    mode = "APPLY" if apply else "DRY-RUN"

    print(f"{'=' * 60}")
    print(f"🧬 Санация исключений — режим: {mode}")
    print(f"{'=' * 60}\n")

    total_found = 0
    total_fixed = 0
    total_skipped = 0
    file_results = []

    for pyfile in sorted(SRC_DIR.rglob("*.py")):
        # Пропускаем __pycache__
        if '__pycache__' in str(pyfile):
            continue

        result = process_file(pyfile, apply=apply)
        file_results.append(result)
        total_found += result["found"]
        total_fixed += result["fixed"]

        if result["errors"]:
            total_skipped += 1

        if result["found"] > 0 or result["errors"]:
            status = "✅" if result["fixed"] > 0 else "⏭️"
            short = str(pyfile.relative_to(SRC_DIR))
            errs = "; ".join(result["errors"]) if result["errors"] else ""
            print(f"  {status} {short}: {result['fixed']}/{result['found']} {errs}")

    print(f"\n{'=' * 60}")
    print(f"📊 ИТОГО:")
    print(f"   Найдено:    {total_found}")
    print(f"   Исправлено: {total_fixed}")
    print(f"   Пропущено:  {total_skipped} файлов")
    print(f"   Режим:      {mode}")
    print(f"{'=' * 60}")

    if not apply:
        print(f"\n💡 Запусти с --apply для применения изменений:")
        print(f"   python scripts/sanitize_exceptions.py --apply")
    else:
        print(f"\n✅ Все изменения применены. Запусти тесты:")
        print(f"   python -m pytest tests/ -x --timeout=60 -v")

    # Генерируем отчёт
    report_path = SRC_DIR.parent / "docs" / "SANATION_REPORT.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Отчёт о санации исключений\n\n")
        f.write(f"**Дата:** 2026-07-14\n")
        f.write(f"**Режим:** {mode}\n")
        f.write(f"**Всего найдено:** {total_found}\n")
        f.write(f"**Всего исправлено:** {total_fixed}\n\n")
        f.write(f"## Изменённые файлы\n\n")
        f.write(f"| Файл | Найдено | Исправлено |\n")
        f.write(f"|------|---------|------------|\n")
        for r in file_results:
            if r["fixed"] > 0:
                f.write(f"| {r['file']} | {r['found']} | {r['fixed']} |\n")
        f.write(f"\n## Пропущенные файлы\n\n")
        for r in file_results:
            if r["errors"] and r["found"] == 0:
                f.write(f"- {r['file']}: {r['errors'][0]}\n")
        f.write(f"\n---\n*Сгенерировано скриптом `scripts/sanitize_exceptions.py`*\n")

    print(f"\n📄 Отчёт сохранён: docs/SANATION_REPORT.md")


if __name__ == "__main__":
    main()
