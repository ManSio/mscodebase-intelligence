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
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
DIARY = ROOT / "AGENT_DIARY.md"
EXCLUDES = {".git", "__pycache__", ".pyc", "venv", ".venv", "node_modules", ".codebase_indices"}

# Стандартные функции Python/builtins, которые могут встречаться в diary-примерах
# (не являются функциями нашего проекта)
_STDLIB_FUNCTIONS = {
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
    # Path / os / time / re / json / subprocess — часто в примерах
    "mkdir", "sleep", "read_text", "write_text", "read_bytes",
    "write_bytes", "exists", "is_dir", "is_file", "iterdir",
    "glob", "rglob", "unlink", "rmdir", "rename", "resolve",
    "relative_to", "with_suffix", "with_name", "parent", "name",
    "stem", "suffix", "cwd", "home", "stat", "lstat", "chmod",
    "joinpath", "samefile", "absolute", "as_posix", "as_uri",
    "split", "strip", "replace", "find", "startswith", "endswith",
    "contains", "decode", "encode", "format", "json", "dumps",
    "loads", "dump", "load", "run", "Popen", "check_call",
    "check_output", "pytest", "main",
    # Common Python stdlib / methods — часто в diary-примерах как `obj.method()`
    "add_columns", "box_close", "box_fail", "box_ok", "box_step",
    "communicate", "connect", "count_rows", "cpp",
    "create_index", "create_table", "create_subprocess_exec",
    "debug", "decompress", "drop_table",
    "predict_eta", "run_health_check",
    "from_pretrained",
    "getdefaultlocale", "get_inputs", "get_objects", "getrusage",
    "is_relative_to",
    "kill",
    "optimize",
    "reindexing", "rmtree", "run_in_executor",
    "safe_close",
    "terminate", "threads", "time",
    "to_arrow", "to_pandas", "to_thread",
    "tool", "upper",
    "wait", "wait_for", "warn", "warning", "where", "which",
    "verify_claim",
    # MCP tool registration names — пойманы через @mcp.tool() regex выше
    "registered",
}


class SymbolCache:
    """Pre-built cache: один проход по .py файлам, потом O(1) проверка.

    Заменяет ~600-1200 grep -r вызовов на один проход + set lookup.
    """

    _instance: Optional["SymbolCache"] = None

    def __init__(self):
        self._funcs: Set[str] = set()
        self._classes: Set[str] = set()
        self._build()

    def _build(self):
        """Сканирует все .py файлы, собирает def/class имена."""
        py_files = list(ROOT.rglob("*.py"))
        for fp in py_files:
            rel = str(fp.relative_to(ROOT))
            parts = Path(rel).parts
            if any(d in parts for d in EXCLUDES):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            # Без якоря ^ — ловим методы классов (с отступом).
            # MULTILINE + ^ не работал для `    def method(self)`.
            for m in re.finditer(r'(?:^|\n)\s*(?:async\s+)?(?:def|class)\s+([a-zA-Z_][a-zA-Z0-9_]+)', text):
                name = m.group(1)
                if name[0].isupper():
                    self._classes.add(name)
                else:
                    self._funcs.add(name)
            # MCP tool names: @mcp.tool("name") или @mcp_app.tool("name")
            # В diary упоминается intel_trigger_reindex, но def — trigger_reindex
            for m in re.finditer(r'@\w+\.tool\("([a-z_][a-z0-9_]+)"\)', text):
                self._funcs.add(m.group(1))
            # Class-based MCP tools: tool_name="graph_query" в super().__init__()
            # Эти имена — публичные MCP-инструменты, не Python-функции
            for m in re.finditer(r'tool_name="([a-z_][a-z0-9_]+)"', text):
                self._funcs.add(m.group(1))

    def has_function(self, name: str) -> bool:
        return name in self._funcs

    def has_class(self, name: str) -> bool:
        return name in self._classes

    @classmethod
    def get_instance(cls) -> "SymbolCache":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def _extract_code_functions(line: str) -> List[str]:
    """Извлекает имена функций ТОЛЬКО из backtick-кода в строке.

    Пример: `` `hybrid_search()` `` → ["hybrid_search"]
    `` text `set_reindexing()` more `` → ["set_reindexing"]
    `` prose word( `` → [] (prose без backtick)
    """
    result = []
    # Находим все backtick-блоки
    for m in re.finditer(r'`([^`]+)`', line):
        content = m.group(1)
        # Ищем function_name( внутри backtick
        for fm in re.finditer(r'\b([a-z_][a-z0-9_]{2,})\s*\(', content):
            result.append(fm.group(1))
    return result


def _extract_code_classes(line: str) -> List[str]:
    """Извлекает имена классов из backtick-кода.

    `` `class Indexer` `` → ["Indexer"]
    """
    result = []
    for m in re.finditer(r'`([^`]+)`', line):
        content = m.group(1)
        for cm in re.finditer(r'\bclass\s+([A-Z][a-zA-Z0-9_]+)', content):
            result.append(cm.group(1))
    return result


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
            if "verified_from_clean_state" in line.lower() or "verified from clean state" in line.lower():
                current_entry.has_verified = True
                if "✅" in line and ("yes" in line.lower() or "да" in line.lower()):
                    current_entry.verified_from_clean = True

            # Извлечение символов — ТОЛЬКО из backtick-кода (`code`), чтобы не
            # выдёргивать английские слова из прозы ("lock", "which", "print" и т.д.)
            # Функции: ищем pattern(`) внутри backtick-пар
            bt_funcs = _extract_code_functions(line)
            for f in bt_funcs:
                if f not in current_entry.functions:
                    current_entry.functions.append(f)

            # Классы: class Name внутри backtick-пар
            bt_classes = _extract_code_classes(line)
            for c in bt_classes:
                if c not in current_entry.classes:
                    current_entry.classes.append(c)

            # Тесты: test_xxx — уникальные имена, можно из любого контекста
            tests = re.findall(r"(test_[a-z_][a-z0-9_]*)", line)
            for t in tests:
                # Фильтр: test__ (двойное подчёркивание) — regex артефакт
                if "__" in t:
                    continue
                if t not in current_entry.tests:
                    current_entry.tests.append(t)

            # Коммиты: hex-хеши
            commits = re.findall(r"[a-f0-9]{7,40}", line)
            for c in commits:
                if c not in current_entry.commits:
                    current_entry.commits.append(c)

    if current_entry:
        current_entry.line_end = len(lines) - 1
        entries.append(current_entry)

    return entries


def check_symbol_exists(symbol: str, is_test: bool = False) -> bool:
    """Проверяет существование символа (функции/класса/теста) в кодовой базе.

    Использует SymbolCache (один проход по файлам) вместо grep -r (600-1200 вызовов).
    """
    if is_test:
        return _check_test_file_exists(symbol)

    # Пропускаем stdlib/builtin имена — они не из нашего проекта
    if symbol in _STDLIB_FUNCTIONS:
        return True

    cache = SymbolCache.get_instance()
    return cache.has_function(symbol) or cache.has_class(symbol)


def _check_test_file_exists(test_name: str) -> bool:
    """Проверяет существование тестового файла прямым поиском по диску.

    Заменяет pytest -k (B5): keyword match по именам тестов даёт false-negatives
    для файлов с несколькими тест-методами внутри класса.

    Args:
        test_name: Имя теста (может быть test_xxx или xxx)

    Returns:
        True если файл tests/test_<name>.py существует
    """
    base = test_name.replace("test_", "", 1) if test_name.startswith("test_") else test_name
    candidates = [
        ROOT / "tests" / f"{test_name}.py",
        ROOT / "tests" / f"test_{base}.py",
    ]
    return any(p.exists() for p in candidates)


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


def gate_zero_full_suite() -> Tuple[bool, str]:
    """Level-0: полный pytest tests/ без фильтров.

    Если тест-сьют не проходит — ledger бессмысленен.
    Возвращает (passed, output_snippet).
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line", "--no-header"],
            cwd=str(ROOT),
            capture_output=True, text=True, timeout=120,
        )
        output = result.stdout.strip()
        # Извлекаем итоговую строку
        lines = [l for l in output.split("\n") if "passed" in l or "failed" in l]
        summary = lines[-1] if lines else output[-200:]
        return result.returncode == 0, summary
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT: pytest tests/ > 120s"
    except Exception as e:
        return False, f"ERROR: {e}"


def run_verification(entries: List[DiaryEntry], fix_missing: bool = False) -> Tuple[int, int, List[str]]:
    """Запускает проверку всех записей. Возвращает (passed, failed, issues)."""
    # Протокол AGENTS.md §7.7 введён 2026-07-19 — записи ДО этой даты не обязаны
    # иметь verified_from_clean_state (legacy).
    _PROTOCOL_DATE = "2026-07-19"
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

        # Проверка verified_from_clean_state (§7.7) — только для записей после введения протокола
        if (entry.functions or entry.classes or entry.tests) and entry.date >= _PROTOCOL_DATE:
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


def run_contradiction_ledger(project_root: Optional[Path] = None) -> dict:
    """Runs contradiction ledger check. Returns dict, never sys.exit.
    Used by MCP startup for safe import-time validation.

    Args:
        project_root: опциональный путь к проекту (если не указан — использует ROOT).
    """
    global ROOT
    def run_contradiction_ledger(project_root: Optional[str] = None, skip_gate_zero: bool = True) -> dict:
        """API для вызова из MCP-сервера.

        Args:
            project_root: путь к проекту.
            skip_gate_zero: True (по умолч.) — не гонять pytest tests/,
                            False — полная проверка (как в CLI main()).
        """
        if project_root is not None:
            ROOT = Path(project_root).resolve()
            # Обновляем DIARY для нового ROOT
            global DIARY
            DIARY = ROOT / "AGENT_DIARY.md"
        # Gate-zero: full test suite — ТОЛЬКО для CLI, не для старта сервера.
        # На сервере pytest tests/ создаёт лишние процессы на 120 секунд.
        if not skip_gate_zero:
            gate_ok, gate_summary = gate_zero_full_suite()
            if not gate_ok:
                return {
                    "ok": False,
                    "discrepancies": 1,
                    "claims": 0,
                    "commits": 0,
                    "details": [f"🚨 GATE 0 FAILED: {gate_summary}"],
                }
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
    parser.add_argument("--skip-gate-zero", action="store_true", help="Skip full test suite check")
    args = parser.parse_args()

    print("🔍 Ledger-проверка AGENT_DIARY.md...")

    # Gate-zero: full test suite first
    if not args.skip_gate_zero:
        print("\n🚧 Gate-zero: полный pytest tests/...")
        gate_ok, gate_summary = gate_zero_full_suite()
        if gate_ok:
            print(f"   ✅ {gate_summary}")
        else:
            print(f"   ❌ {gate_summary}")
            print("   🚨 GATE 0 FAILED: ledger проверка блокирована.")
            print("   Исправь тесты, затем запусти снова (--skip-gate-zero для обхода).")
            sys.exit(1)

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