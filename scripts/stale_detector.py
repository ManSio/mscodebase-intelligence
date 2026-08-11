#!/usr/bin/env python3
"""
Stale Detector — detects documentation drift from codebase.

Реальная реализация: `tools/stale_detector/stale_check.py` (version-string drift,
severity error/warn, конфиг tools/stale_detector/stale_config.json).
Этот файл — тонкая обёртка с правильным project-root (по Тумблеру: обёртка,
не дубль логики).

Было (2026-08-08..11): placeholder «No drifts detected (placeholder implementation)»,
всегда exit 0 — класс «guard структурно неспособен упасть» (EXP-5B, KNOWN_ISSUES
2026-08-11). Заменено на делегирование реальному чекеру.

Usage:
    python scripts/stale_detector.py [--report-format human|json] [--config PATH]

Exit code: 0 = нет critical-дрейфов; 1 = найдены severity=error дрейфы;
2 = чекер не найден/таймаут.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHECKER = PROJECT_ROOT / "tools" / "stale_detector" / "stale_check.py"


def main() -> int:
    if not CHECKER.exists():
        print(f"Stale Detector: checker not found: {CHECKER}")
        return 2

    # §5.16: Popen + communicate (не capture_output) — защита от pipe-deadlock;
    # cwd=PROJECT_ROOT — config по умолчанию резолвится от project-root.
    cmd = [
        sys.executable,
        str(CHECKER),
        "--project-root",
        str(PROJECT_ROOT),
        *sys.argv[1:],
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout, stderr = proc.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        print("Stale Detector: TIMEOUT (>120s)")
        return 2

    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
