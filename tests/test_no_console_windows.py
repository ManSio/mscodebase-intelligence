"""Guard: ни один вызов `subprocess.*` не спавнит видимое окно консоли.

Windows-симптом: когда у родителя нет консоли (MCP-сервер, pytest под хостом
без окна, дочерний python), каждый `git`/`python`/`cmd` создаёт СВОЮ консоль
и мигает. Динамическая сеть — `src/core/silent_subprocess.apply()` (патчит
`Popen`/`run`/`check_*`), но она не действует на процесс, который её не
импортировал. Поэтому статический контракт: у каждого вызова явно есть
`creationflags` (или `startupinfo`).

Тест сканирует `src/`, `tests/`, `scripts/` через AST и падает со списком
`file:line`, если появился bare-вызов. Само-тест (`_scan`) доказывает, что
сканер умеет краснеть: тот же код без флага обязан быть найден.

Контракт — про содержимое репозитория, поэтому сканируются только файлы из
индекса git: gitignored scratch (`scripts/_diag_*.py`) не часть проекта и не
должен красить гейт. Без git — прежнее поведение (скан всех файлов).
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNED_DIRS = ("src", "tests", "scripts", "tools")
# корневые entry-скрипты (install.py и т.п.) — тоже часть контракта
SCANNED_ROOT_FILES = tuple(ROOT.glob("*.py"))
# pre-existing: файл не парсится (битый отступ, не связан с этой задачей)
UNPARSEABLE = {"scripts/live_search_audit.py"}
SUBPROCESS_FUNCS = {
    "run",
    "Popen",
    "call",
    "check_output",
    "check_call",
    "getoutput",
    "getstatusoutput",
}


def _scan(source: str) -> list[tuple[int, str]]:
    """Возвращает [(lineno, «subprocess.run»)] для вызовов без подавления окна."""
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
            and func.attr in SUBPROCESS_FUNCS
        ):
            continue
        names = {kw.arg for kw in node.keywords}
        if {"creationflags", "startupinfo"} & names or None in names:
            continue
        offenders.append((node.lineno, f"subprocess.{func.attr}"))
    return offenders


def _scan_file(path: Path) -> list[tuple[int, str]]:
    return _scan(path.read_text(encoding="utf-8-sig"))


def _tracked_files() -> set[str] | None:
    """Пути в индексе git (включая staged). None — git недоступен, скан без фильтра."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return {p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p}


def test_scanner_detects_a_bare_call():
    """Позитив-контроль: без флага вызов найден (иначе guard пуст)."""
    assert _scan("import subprocess\nsubprocess.run(['git', 'status'])\n") == [
        (2, "subprocess.run")
    ]


def test_scanner_accepts_a_flagged_call():
    """Негатив-контроль: с флагом вызов не считается нарушением."""
    src = (
        "import subprocess\n"
        "subprocess.run(['git', 'status'], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))\n"
        "subprocess.Popen(['git'], startupinfo=None)\n"
        "subprocess.run(['git'], **kwargs)\n"
    )
    assert _scan(src) == []


def test_no_subprocess_call_can_open_a_console():
    offenders: list[str] = []
    unparseable: list[str] = []
    paths = [p for rel in SCANNED_DIRS for p in sorted((ROOT / rel).rglob("*.py"))]
    paths += [p for p in SCANNED_ROOT_FILES if "__pycache__" not in p.parts]
    tracked = _tracked_files()
    if tracked is not None:
        paths = [p for p in paths if p.relative_to(ROOT).as_posix() in tracked]
    for path in paths:
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            found = _scan_file(path)
        except SyntaxError:
            if rel not in UNPARSEABLE:
                unparseable.append(rel)
            continue
        offenders.extend(f"{rel}:{line} {call}" for line, call in found)

    assert not unparseable, f"файлы не парсятся (сканер их не видит): {unparseable}"
    assert not offenders, (
        "вызов subprocess.* без creationflags/startupinfo — на Windows это "
        "мигающее окно консоли:\n  " + "\n  ".join(offenders)
    )
