#!/usr/bin/env python
"""
ruff_gate.py — гейт ruff в pre-commit hook.

Закрывает дыру: pre-commit локально не гонял ruff, а CI (`ruff check src/ tests/`,
ci.yml) ловил lint-ошибки уже после пуша (прецеденты CI red: 5a771789, b121ab19,
3dd79ba2). Скрипт вызывается run_script("scripts/ruff_gate.py", "ruff_gate")
в PRE_COMMIT_HOOK (git_hooks_installer.py).

Exit:
  0 — ruff чист, или ruff не установлен (advisory-пропуск: CI всё равно проверяет)
  1 — ruff найден lint-ошибки
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ENCODING SAFETY (Windows §5.9)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent

    try:
        import ruff  # noqa: F401
    except ImportError:
        print("  ⚠️ ruff не установлен — пропуск (CI всё равно проверяет)")
        return 0

    proc = subprocess.Popen(
        [sys.executable, "-m", "ruff", "check", "src/", "tests/"],
        cwd=str(project_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        stdout, _ = proc.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("  ❌ ruff: таймаут (300s)")
        return 1

    if proc.returncode != 0:
        print(f"  ❌ ruff: exit {proc.returncode}")
        if stdout:
            for line in stdout.splitlines()[-15:]:
                print(f"    {line}")
        return 1
    print("  ✅ ruff: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
