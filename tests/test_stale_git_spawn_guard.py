"""Regression: the stale scan must not use capture_output for git.

2026-11-08: `stale_detector` hung forever inside the MCP and froze the whole
server, because the scan called `subprocess.run(capture_output=True)` for
`git diff` / `git ls-files` while the MCP's stdout is the JSON-RPC pipe. The
same scan took 1.2 s in a plain process — the child git was stuck, not the
scan. This is the fourth instance of the class (health check_output, ledger
per-hash spawns, predict_change timeout, this one), so the site is pinned.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "stale_detector" / "stale_check.py"


def test_checker_does_not_use_capture_output():
    import ast

    tree = ast.parse(CHECKER.read_text(encoding="utf-8"))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "capture_output" and getattr(kw.value, "value", None) is True
    ]
    assert not offenders, (
        "stale_check.py must spawn git with Popen(+communicate); "
        f"capture_output deadlocks when MCP stdout is the JSON-RPC pipe (lines {offenders})"
    )


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    def run(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=tmp_path, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (tmp_path / "doc.md").write_text("# doc\n", encoding="utf-8")
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    run("add", "doc.md", "code.py")
    return tmp_path


def test_staged_markdown_files_returns_only_md(git_repo: Path):
    from tools.stale_detector.stale_check import staged_markdown_files

    files = staged_markdown_files(git_repo)

    assert [f.name for f in files] == ["doc.md"]


def test_tracked_markdown_files_returns_tracked_md(git_repo: Path):
    from tools.stale_detector.stale_check import tracked_markdown_files

    assert tracked_markdown_files(git_repo) == {"doc.md"}
