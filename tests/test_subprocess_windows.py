"""Windows subprocess safety tests (AGENTS.md §5.16).

Guards:
1. Все console-спавны (powershell/wsl/wmic/netstat/taskkill/nvidia-smi) в src
   на Windows обязаны нести creationflags=CREATE_NO_WINDOW — иначе под pythonw
   они открывают видимое окно cmd (P-001; рецидивы 2026-08-14, 2026-09-06).
2. В daemon-потоках запрещён subprocess.run(capture_output=True) — pipe-deadlock.
"""

import os
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
_WINDOWS_ONLY = ("win32", "cygwin")

_CONSOLE_BINARIES = ("powershell", "wsl", "wmic", "netstat", "taskkill", "nvidia-smi")
_SPAWN = re.compile(r"subprocess\.(check_output|run|call|Popen)\(")


def _iter_py_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if p.is_file())


@pytest.mark.skipif(not re.match(r"win32|cygwin", os.sys.platform), reason="Windows-only P-001 guard")
def test_windows_console_spawns_have_create_no_window():
    """Каждый консольный подпроцесс несёт CREATE_NO_WINDOW (P-001 guard)."""
    offenders: list[str] = []
    for path in _iter_py_files():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            if _SPAWN.search(line) is None:
                continue
            # Юнион-проверка: место вызова содержит консольный бинар в этой
            # или следующей строке (квилы списков: Python, llama, git, sysctl,
            # ss, ruff, zstandard, onnx_server, runner.py — не консоль-спавны).
            block = "\n".join(lines[max(0, i - 2) : i + 2]).lower()
            if not any(bin_name in block for bin_name in _CONSOLE_BINARIES):
                continue
            window_guard = any(
                "CREATE_NO_WINDOW" in line or "CREATE_NO_WINDOW" in lines[j]
                for j in range(max(0, i - 2), min(len(lines), i + 6))
            )
            if not window_guard:
                offenders.append(f"{path.relative_to(SRC)}:{i + 1}: {line.strip()}")
    assert not offenders, (
        "Console spawns in src must set CREATE_NO_WINDOW (P-001, cmd-окна под pythonw):\n"
        + "\n".join(offenders)
    )


def test_daemon_thread_no_capture_output():
    """Daemon-потоки: Popen+communicate, не run(capture_output=True)."""
    offenders: list[str] = []
    for path in _iter_py_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), start=1):
            if "capture_output=True" not in line:
                continue
            # Ближайшие 3 строки выше — thread/daemon запуск (попадание).
            above = "\n".join(text.splitlines()[max(0, i - 4) : i - 1]).lower()
            if any(k in above for k in ("daemon=True", "thread(", "start()")):
                offenders.append(f"{path.relative_to(SRC)}:{i}: {line.strip()}")
    assert not offenders, (
        "Daemon threads must use Popen+communicate (pipe-deadlock, §5.16):\n"
        + "\n".join(offenders)
    )
