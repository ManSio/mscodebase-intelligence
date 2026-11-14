"""The line-ending gate must catch a CRLF blob and must not blame a CRLF working tree.

The distinction is the whole point: a Windows checkout with core.autocrlf=true is
CRLF in the working tree while the index stays LF, and that is fine. Only a file
committed with CRLF breaks byte-for-byte checks on another OS.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_eol.py"


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return done.stdout


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "eol@example.invalid")
    _git(repo, "config", "user.name", "eol")
    return repo


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(repo)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_crlf_in_the_index_fails(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "crlf.txt").write_bytes(b"one\r\ntwo\r\n")
    _git(repo, "add", "crlf.txt")
    _git(repo, "commit", "-q", "-m", "crlf")

    result = _run(repo)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "crlf.txt" in result.stdout


def test_lf_in_the_index_passes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "lf.txt").write_bytes(b"one\ntwo\n")
    _git(repo, "add", "lf.txt")
    _git(repo, "commit", "-q", "-m", "lf")

    result = _run(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_crlf_working_tree_with_lf_index_passes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "file.txt").write_bytes(b"one\ntwo\n")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-q", "-m", "lf")

    # Same bytes the checkout writes on Windows; the index is still LF.
    (repo / "file.txt").write_bytes(b"one\r\ntwo\r\n")
    assert "w/crlf" in _git(repo, "ls-files", "--eol", "--", "file.txt")

    result = _run(repo)

    assert result.returncode == 0, result.stdout + result.stderr
