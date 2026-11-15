#!/usr/bin/env python3
"""Refuse to publish a citation that does not resolve.

A text can cite a commit that exists only on the author's disk: a squash merge
rewrites history, the short hash dies, and every file-level gate stays green.
On 2026-11-15 the published post cited `4fc7404` three times; that commit is in
no remote branch, so all three links were dead.

Rule: a token is a *citation* only if it resolves to a commit object. Blobs and
trees (file digests) are noted, not failed. A hash followed by an ellipsis is a
truncated digest, not a link, and is skipped.

Usage:
    python scripts/check_cited_commits.py post.md
    git log -1 --format=%B | python scripts/check_cited_commits.py -

Exit codes: 0 all citations resolve · 1 dead citation · 2 no input / not a repo.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ALLOW_FILE = REPO / "scripts" / "cited_commits_allow.txt"
TOKEN = re.compile(r"\b[0-9a-f]{7,40}\b")
ELLIPSIS = ("…", "...")
SAMPLE_OK = "fixed in d37b796"
SAMPLE_BAD = "fixed in deadbeef"


def load_allowlist(path: Path = ALLOW_FILE) -> dict[str, str]:
    """`hash = reason` lines: citations that live in another repository."""
    if not path.is_file():
        return {}
    allowed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, reason = line.split("=", 1)
        allowed[key.strip()] = reason.strip()
    return allowed


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _object_type(token: str) -> str:
    """commit / blob / tree / '' when the object is unknown."""
    out = _git("cat-file", "-t", token)
    return out.stdout.strip() if out.returncode == 0 else ""


def _reachable(sha: str) -> bool:
    """Alive if any remote ref contains it, any ref contains it, or HEAD builds on it.

    A shallow CI checkout has no remote-tracking refs, so "no remote contains it"
    alone would fail a citation that is simply the HEAD of the pull request.
    """
    if _git("branch", "-r", "--contains", sha).stdout.strip():
        return True
    if _git("for-each-ref", "--contains", sha).stdout.strip():
        return True
    return _git("merge-base", "--is-ancestor", sha, "HEAD").returncode == 0


def find_citations(text: str) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return (ok, dead, unknown, elsewhere); blobs and ellipses are ignored."""
    allow = load_allowlist()
    ok: list[str] = []
    dead: list[str] = []
    unknown: list[str] = []
    elsewhere: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in TOKEN.finditer(line):
            tail = line[match.end():].lstrip()
            if tail.startswith(ELLIPSIS):
                continue
            token = match.group(0)
            if token in allow:
                elsewhere.append(f"line {number}: {token} — {allow[token]}")
                continue
            kind = _object_type(token)
            if kind == "commit":
                (ok if _reachable(token) else dead).append(f"line {number}: {token}")
            elif kind in ("blob", "tree"):
                continue
            else:
                unknown.append(f"line {number}: {token}")
    return ok, dead, unknown, elsewhere


def self_test() -> int:
    ok, dead, unknown, _ = find_citations(SAMPLE_OK + "\n" + SAMPLE_BAD + "\n")
    if not ok:
        print("SELFTEST FAIL: a reachable commit was not recognised", file=sys.stderr)
        return 1
    if not (dead or unknown):
        print("SELFTEST FAIL: an unresolvable hash was accepted", file=sys.stderr)
        return 1
    print(f"selftest OK: reachable={len(ok)} dead={len(dead)} unknown={len(unknown)}")
    return 0


def _read(sources: list[str]) -> tuple[str, int]:
    if not sources:
        return "", 2
    if sources == ["-"]:
        return sys.stdin.read(), 0
    parts: list[str] = []
    for source in sources:
        path = Path(source)
        if not path.is_file():
            print(f"ERR {source}: not a file", file=sys.stderr)
            return "", 2
        parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts), 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    if _git("rev-parse", "--git-dir").returncode != 0:
        print("ERR not a git repository", file=sys.stderr)
        return 2
    sources = [a for a in argv[1:] if a != "--self-test"]
    text, rc = _read(sources)
    if rc != 0:
        return 2
    ok, dead, unknown, elsewhere = find_citations(text)
    for line in elsewhere:
        print(f"OK-ELSEWHERE {line}")
    for line in dead:
        print(f"DEAD {line}: commit not reachable from any remote branch")
    for line in unknown:
        print(f"DEAD {line}: no such object")
    if dead or unknown:
        print(f"refused: {len(dead) + len(unknown)} citation(s) do not resolve")
        return 1
    print(f"clean: {len(ok)} citation(s) resolve, {len(elsewhere)} allowlisted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
