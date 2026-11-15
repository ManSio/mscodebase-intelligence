"""A published hash must resolve on the remote (P-045).

A squash merge rewrites history: the short hash that exists on the author's disk
is in no remote branch, so a cited link 404s while every file gate stays green.
On 2026-11-15 the post cited `4fc7404` three times in exactly this state.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_cited_commits.py"


def _git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def _run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=stdin,
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def test_reachable_commit_passes(tmp_path: Path) -> None:
    head = _git("rev-parse", "--short=7", "HEAD")
    body = tmp_path / "post.md"
    body.write_text(f"fixed in {head}\n", encoding="utf-8")
    proc = _run(str(body))
    assert proc.returncode == 0, proc.stdout
    assert "clean" in proc.stdout


def test_unreachable_commit_is_refused(tmp_path: Path) -> None:
    dangling = _git("commit-tree", "HEAD^{tree}", "-m", "dangling fixture for P-045")
    body = tmp_path / "post.md"
    body.write_text(f"fixed in {dangling[:7]}\n", encoding="utf-8")
    proc = _run(str(body))
    assert proc.returncode == 1, proc.stdout
    assert "not reachable" in proc.stdout


def test_unknown_hash_is_refused(tmp_path: Path) -> None:
    body = tmp_path / "post.md"
    body.write_text("see deadbeefdeadbeef\n", encoding="utf-8")
    proc = _run(str(body))
    assert proc.returncode == 1, proc.stdout
    assert "no such object" in proc.stdout


def test_allowlist_is_explicit(tmp_path: Path) -> None:
    allowed = (REPO / "scripts" / "cited_commits_allow.txt").read_text(encoding="utf-8")
    token = next(
        line.split("=")[0].strip()
        for line in allowed.splitlines()
        if line.strip() and not line.startswith("#")
    )
    body = tmp_path / "post.md"
    body.write_text(f"in another repo {token}\n", encoding="utf-8")
    proc = _run(str(body))
    assert proc.returncode == 0, proc.stdout
    assert "OK-ELSEWHERE" in proc.stdout


def test_truncated_digest_is_skipped(tmp_path: Path) -> None:
    body = tmp_path / "post.md"
    body.write_text("hashes to `71395d45…` (a sha256 prefix)\n", encoding="utf-8")
    proc = _run(str(body))
    assert proc.returncode == 0, proc.stdout


def test_no_input_is_not_a_pass() -> None:
    assert _run().returncode == 2
