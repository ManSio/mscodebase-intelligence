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

import os
import shutil
import subprocess
import sys
from pathlib import Path

# ENCODING SAFETY (Windows §5.9)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def ruff_cmd() -> list[str] | None:
    """Resolve a ruff that actually runs.

    2026-10-03: `python -m ruff` in this venv printed NOTHING and exited 1 — the
    installed `ruff` package has no `__main__`. The gate called exactly that, so
    it was permanently red and mute: it looked like "lint is broken", and the
    only visible effect was that commits could not be made.

    Order matters: availability is decided by importability first (no
    subprocess at all), because a subprocess probe here would fire inside other
    tests that stub `subprocess.Popen`. The dead module form is only used when
    no console script exists, and it is then proven with `--version`.
    """
    try:
        import ruff  # noqa: F401
    except ImportError:
        return None

    exe = shutil.which("ruff")
    if not exe:
        # console scripts live next to the interpreter inside a venv
        cand = Path(sys.executable).parent / ("ruff.exe" if os.name == "nt" else "ruff")
        if cand.exists():
            exe = str(cand)
    if exe:
        return [exe, "check"]

    # No console script: the module form is the last resort, but only if it can
    # actually report a version (this venv's copy cannot).
    try:
        probe = subprocess.run([sys.executable, "-m", "ruff", "--version"],
                              capture_output=True, encoding="utf-8",
                              errors="replace", timeout=60)
        if probe.returncode == 0 and "ruff" in (probe.stdout or "").lower():
            return [sys.executable, "-m", "ruff", "check"]
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent

    cmd = ruff_cmd()
    if cmd is None:
        print("  ⚠️ ruff не найден ни одним из способов — пропуск (CI всё равно проверяет)")
        return 0

    proc = subprocess.Popen(
        [*cmd, "src/", "tests/"],
        cwd=str(project_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
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
        print(f"  ❌ ruff: exit {proc.returncode}  ({' '.join(cmd)})")
        if stdout and stdout.strip():
            for line in stdout.splitlines()[-15:]:
                print(f"    {line}")
        else:
            # A tool that fails without saying anything is not a lint verdict.
            print("    ПУСТОЙ вывод ruff при ненулевом коде — это не lint-ошибка, "
                  "а сломанный запуск инструмента. Проверьте, что ruff вообще "
                  "исполняется: `ruff --version`.")
        return 1
    print("  ✅ ruff: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
