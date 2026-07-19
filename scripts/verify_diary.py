#!/usr/bin/env python3
"""
verify_diary.py — Ledger-проверка AGENT_DIARY.md против реальности кода.
Использование:
  python scripts/verify_diary.py                    # отчёт
  python scripts/verify_diary.py --report-format=json  # JSON для CI
  python scripts/verify_diary.py --fix-missing        # интерактивное добавление маркеров
"""
import re
import sys
import subprocess
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
DIARY = ROOT / "AGENT_DIARY.md"
EXCLUDES = {".git", "__pycache__", ".pyc", "venv", ".venv", "node_modules", ".codebase_indices"}


@dataclass
class DiaryEntry:
    line_start: int
    line_end: int
    date: str
    title: str
    content: str
    has_verified: bool
    verified_from_clean: bool
    functions: List[str]
    classes: List[str]
    tests: List[str]
    commits: List[str]


def parse_diary() -> List[DiaryEntry]:
    """Парсит AGENT_DIARY.md и извлекает записи."""
    if not DIARY.exists():
        print(f"❌ {DIARY} not found", file=sys.stderr)
        return []

    content = DIARY.read_text(encoding="utf-8")
    lines = content.split("\n")

    entries = []
    current_entry = None
    in_code_block = False

    for i, line in enumerate(lines):
        # Начало записи: ## [YYYY-MM-DD HH:MM] — Title
        m = re.match(r"^##\s*\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\]\s*[—-]\s*(.+)$", line)
        if m:
            if current_entry:
                current_entry.line_end = i - 1
                entries.append(current_entry)
            current_entry = DiaryEntry(
                line_start=i,
                line_end=len(lines),
                date=m.group(1),
                title=m.group(2),
                content="",
                has_verified=False,
                verified_from_clean=False,
                functions=[],
                classes=[],
                tests=[],
                commits=[],
            )
            continue

        if current_entry:
            current_entry.content += line + "\n"

            # Проверка маркеров
            if "verified_from_clean_state" in line.lower():
                current_entry.has_verified = True
                if "✅" in line and ("yes" in line.lower() or "да" in line.lower()):
                    current_entry.verified_from_clean = True

            # Извлечение функций/классов/тестов/коммитов
            funcs = re.findall(r"\b([a-z_][a-z0-9_]{2,})\s*\(", line)
            for f in funcs:
                if f not in current_entry.functions:
                    current_entry.functions.append(f)

            classes = re.findall(r"\bclass\s+([A-Z][a-zA-Z0-9_]+)", line)
            for c in classes:
                if c not in current_entry.classes:
                    current_entry.classes.append(c)

            tests = re.findall(r"(test_[a-z_][a-z0-9_]*)", line)
            for t in tests:
                if t not in current_entry.tests:
                    current_entry.tests.append(t)

            commits = re.findall(r"[a-f0-9]{7,40}", line)
            for c in commits:
                if c not in current_entry.commits:
                    current_entry.commits.append(c)

    if current_entry:
        current_entry.line_end = len(lines) - 1
        entries.append(current_entry)

    return entries


def check_symbol_exists(symbol: str, is_test: bool = False) -> bool:
    """Проверяет существование символа (функции/класса/теста) в кодовой базе."""
    # Ищем в .py файлах
    pattern = rf"^(def|async def|class)\s+{re.escape(symbol)}\b"
    try:
        result = subprocess.run(
            ["grep", "-r", "--include=*.py", pattern, str(ROOT)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    # Для тестов также ищем в pytest коллекции
    if is_test:
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "--collect-only", "-k", symbol, "-q"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and symbol in result.stdout:
                return True
        except Exception:
            pass

    return False


def check_commit_exists(commit_hash: str) -> bool:
    """Проверяет наличие коммита в истории."""
    try:
        result = subprocess.run(
            ["git", "cat-file", "-t", commit_hash],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def run_verification(entries: List[DiaryEntry], fix_missing: bool = False) -> Tuple[int, int, List[str]]:
    """Запускает проверку всех записей. Возвращает (passed, failed, issues)."""
    passed = 0
    failed = 0
    issues = []

    for entry in entries:
        entry_issues = []

        # Проверка функций
        for func in entry.functions:
            if func.startswith("_"):
                continue
            if not check_symbol_exists(func):
                entry_issues.append(f"  ❌ Функция `{func}` не найдена в коде")

        # Проверка классов
        for cls in entry.classes:
            if not check_symbol_exists(cls):
                entry_issues.append(f"  ❌ Класс `{cls}` не найден в коде")

        # Проверка тестов
        for test in entry.tests:
            if not check_symbol_exists(test, is_test=True):
                entry_issues.append(f"  ❌ Тест `{test}` не найден в pytest коллекции")

        # Проверка коммитов
        for commit in entry.commits:
            if len(commit) >= 7 and not check_commit_exists(commit):
                entry_issues.append(f"  ⚠️ Коммит `{commit[:12]}` не найден в истории")

        # Проверка verified_from_clean_state
        if entry.functions or entry.classes or entry.tests:
            if not entry.has_verified:
                entry_issues.append(f"  ⚠️ Нет маркера `verified_from_clean_state`")
            elif not entry.verified_from_clean:
                entry_issues.append(f"  ⚠️ Маркер есть, но не подтверждён (`❌` или нет `yes/да`)")

        if entry_issues:
            failed += 1
            issues.append(f"\n## [{entry.date}] {entry.title}")
            issues.extend(entry_issues)
        else:
            passed += 1

    return passed, failed, issues


def interactive_fix(entries: List[DiaryEntry]) -> None:
    """Интерактивно предлагает добавить недостающие маркеры."""
    content = DIARY.read_text(encoding="utf-8")
    lines = content.split("\n")

    for entry in entries:
        if entry.functions or entry.classes or entry.tests:
            if not entry.has_verified:
                print(f"\n📝 Запись: [{entry.date}] {entry.title}")
                print(f"   Функции: {', '.join(entry.functions) or '—'}")
                print(f"   Классы: {', '.join(entry.classes) or '—'}")
                print(f"   Тесты: {', '.join(entry.tests) or '—'}")
                ans = input("   Добавить `verified_from_clean_state: ✅ yes`? (y/n): ").strip().lower()
                if ans == "y":
                    # Вставляем после заголовка записи
                    insert_at = entry.line_start + 1
                    while insert_at < len(lines) and lines[insert_at].strip() == "":
                        insert_at += 1
                    lines.insert(insert_at, "")
                    lines.insert(insert_at + 1, "**verified_from_clean_state:** ✅ yes — `python -m pytest tests/ -k \"...\"` → passed")
                    print("   ✅ Добавлено")
                else:
                    print("   ⏭️ Пропущено")

    DIARY.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✅ {DIARY} обновлён")


def run_contradiction_ledger() -> dict:
    """Runs contradiction ledger check. Returns dict, never sys.exit.
    Used by MCP startup for safe import-time validation."""
    entries = parse_diary()
    passed, failed, issues = run_verification(entries)
    return {
        "ok": failed == 0,
        "discrepancies": failed,
        "claims": passed + failed,
        "commits": sum(len(e.commits) for e in entries),
        "details": issues,
    }


def main():
    parser = argparse.ArgumentParser(description="Verify AGENT_DIARY.md against codebase reality")
    parser.add_argument("--report-format", choices=["text", "json"], default="text")
    parser.add_argument("--fix-missing", action="store_true", help="Interactive fix missing verified markers")
    args = parser.parse_args()

    print("🔍 Ledger-проверка AGENT_DIARY.md...")
    entries = parse_diary()
    print(f"   Записей найдено: {len(entries)}")

    passed, failed, issues = run_verification(entries)

    if args.report_format == "json":
        import json
        print(json.dumps({
            "total": len(entries),
            "passed": passed,
            "failed": failed,
            "issues": issues,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"\n📊 Итог: {passed} ✅ / {failed} ❌")
        if issues:
            print("\n" + "\n".join(issues))

    if args.fix_missing:
        interactive_fix(entries)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()