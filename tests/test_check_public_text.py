"""Outward text must not carry a local machine layout (P-044).

File gates cannot see a PR body, an issue comment or a blog post, so a body that
shipped `C:\\...\\python.exe` passed every local check on 2026-11-15. This guard
is run by hand (or by the publish step) on the text itself.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_public_text.py"

LEAKY = (
    "interpreter: D:\\Project\\repo\\venv\\Scripts\\python.exe\n"
    "home: /home/alice/work/repo\n"
    "users: C:\\Users\\alice\\AppData\n"
    "root: D:/Project/repo\n"
)
CLEAN = (
    "interpreter: <repo>/venv/bin/python (Python 3.14.10)\n"
    "run: python scripts/count_map.py\n"
    "the bench-B worktree sits next to the repository\n"
)


def _run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=stdin,
        timeout=60,
        # Windows: без флага дочерний python открывает свою консоль и мигает
        # (контракт tests/test_no_console_windows.py).
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def test_leaky_text_is_refused(tmp_path: Path) -> None:
    body = tmp_path / "pr_body.md"
    body.write_text(LEAKY, encoding="utf-8")
    proc = _run(str(body))
    assert proc.returncode == 1, proc.stdout
    reported = {
        line.strip() for line in proc.stdout.splitlines() if line.startswith("LEAK line")
    }
    assert "LEAK line 1: windows-abs-path" in reported, proc.stdout
    assert "LEAK line 2: posix-home-path" in reported, proc.stdout
    assert "LEAK line 3: windows-users-path" in reported, proc.stdout
    assert "LEAK line 4: local-project-root" in reported, proc.stdout


def test_clean_text_passes(tmp_path: Path) -> None:
    body = tmp_path / "pr_body.md"
    body.write_text(CLEAN, encoding="utf-8")
    proc = _run(str(body))
    assert proc.returncode == 0, proc.stdout
    assert "clean" in proc.stdout


def test_stdin_is_supported() -> None:
    proc = _run("-", stdin=LEAKY)
    assert proc.returncode == 1, proc.stdout
    assert "LEAK" in proc.stdout


def test_no_input_is_not_a_pass() -> None:
    proc = _run()
    assert proc.returncode == 2, "no input must fail closed, not print 'clean'"


def test_self_test_has_both_controls() -> None:
    proc = _run("--self-test")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "positive" in proc.stdout and "negative" in proc.stdout
