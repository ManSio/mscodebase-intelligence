#!/usr/bin/env python3
"""Refuse to publish text that carries a local machine layout.

The repository gates scan *files*; a PR body, an issue comment or a blog post is
not a file, so `tests/test_no_personal_paths.py` never sees it. On 2026-11-15 a
PR body shipped a global-interpreter path and a venv path from this machine to a
public repository, and every local gate stayed green.

Usage:
    python scripts/check_public_text.py pr_body.md
    git log -1 --format=%B | python scripts/check_public_text.py -

Exit codes: 0 clean · 1 leak found · 2 no input / unreadable.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERNS = {
    "windows-abs-path": re.compile(r"\b[A-Za-z]:[\\/]"),
    "windows-users-path": re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]", re.IGNORECASE),
    "posix-home-path": re.compile(r"/(?:home|Users)/[^/\s\"'`]+"),
    "local-project-root": re.compile(
        r"\b[A-Za-z]:[\\/]+(?:Project|Projects|work|src)\b", re.IGNORECASE
    ),
}

SAMPLE_BAD = r"interpreter: D:\Project\repo\venv\Scripts\python.exe"
SAMPLE_GOOD = "interpreter: <repo>/venv/bin/python (Python 3.14.10)"


def find_leaks(text: str) -> list[tuple[int, str]]:
    """Return [(line_no, kind)] for every line that looks like a local layout."""
    hits: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        kinds = [kind for kind, pattern in PATTERNS.items() if pattern.search(line)]
        for kind in dict.fromkeys(kinds):
            hits.append((number, kind))
    return hits


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


def self_test() -> int:
    """Both controls: the detector must fire on a leak and stay silent on clean text."""
    if not find_leaks(SAMPLE_BAD):
        print("SELFTEST FAIL: positive control was not detected", file=sys.stderr)
        return 1
    if find_leaks(SAMPLE_GOOD):
        print("SELFTEST FAIL: negative control was flagged", file=sys.stderr)
        return 1
    print("selftest OK: 1 positive detected, 1 negative clean")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    sources = [a for a in argv[1:] if a != "--self-test"]
    text, rc = _read(sources)
    if rc != 0:
        return 2
    leaks = find_leaks(text)
    if not leaks:
        print(f"clean: {len(sources)} source(s), 0 leaks")
        return 0
    for line_no, kind in leaks:
        print(f"LEAK line {line_no}: {kind}")
    print(f"refused: {len(leaks)} hit(s) carry a local path; mask it before publishing")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
