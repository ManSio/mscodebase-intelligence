"""A published hash must resolve on the remote (P-045).

A squash merge rewrites history: the short hash that exists on the author's disk
is in no remote branch, so a cited link 404s while every file gate stays green.
On 2026-11-15 the post cited `4fc7404` three times in exactly this state.

The checker is called in-process: a subprocess-based test inherits whatever the
worker did to `subprocess.run` (a leaked stub made `stdout` None on Windows CI).
"""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_cited_commits.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_cited_commits", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _git(*args: str, with_identity: bool = False) -> str:
    prefix = ["-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid"] if with_identity else []
    out = subprocess.run(
        ["git", *prefix, *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def _run(tmp_path: Path, text: str, capsys) -> tuple[int, str]:
    body = tmp_path / "post.md"
    body.write_text(text, encoding="utf-8")
    code = _module().main(["check_cited_commits", str(body)])
    return code, capsys.readouterr().out


def test_reachable_commit_passes(tmp_path, capsys) -> None:
    head = _git("rev-parse", "--short=7", "HEAD")
    code, out = _run(tmp_path, f"fixed in {head}\n", capsys)
    assert code == 0, out
    assert "clean" in out


def test_unreachable_commit_is_refused(tmp_path, capsys) -> None:
    dangling = _git(
        "commit-tree", "HEAD^{tree}", "-m", "dangling fixture for P-045", with_identity=True
    )
    code, out = _run(tmp_path, f"fixed in {dangling[:7]}\n", capsys)
    assert code == 1, out
    assert "not reachable" in out


def test_unknown_hash_is_refused(tmp_path, capsys) -> None:
    code, out = _run(tmp_path, "see deadbeefdeadbeef\n", capsys)
    assert code == 1, out
    assert "no such object" in out


def test_allowlist_is_explicit(tmp_path, capsys) -> None:
    allowed = (REPO / "scripts" / "cited_commits_allow.txt").read_text(encoding="utf-8")
    token = next(
        line.split("=")[0].strip()
        for line in allowed.splitlines()
        if line.strip() and not line.startswith("#")
    )
    code, out = _run(tmp_path, f"in another repo {token}\n", capsys)
    assert code == 0, out
    assert "OK-ELSEWHERE" in out


def test_truncated_digest_is_skipped(tmp_path, capsys) -> None:
    code, out = _run(tmp_path, "hashes to `71395d45…` (a sha256 prefix)\n", capsys)
    assert code == 0, out


def test_stdin_is_supported(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("see deadbeefdeadbeef\n"))
    assert _module().main(["check_cited_commits", "-"]) == 1


def test_no_input_is_not_a_pass() -> None:
    assert _module().main(["check_cited_commits"]) == 2

def test_all_digit_token_is_skipped(tmp_path, capsys) -> None:
    """A 13-digit timestamp is not a commit hash (found in docs/blog)."""
    code, out = _run(tmp_path, "timestamp 1721234567890 and id 1234567890123\n", capsys)
    assert code == 0, out
