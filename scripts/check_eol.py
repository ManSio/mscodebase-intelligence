"""Gate: no tracked file is committed with CRLF line endings.

Why: byte-for-byte comparisons and sha256 manifests are computed over LF. A file
committed with CRLF passes on Windows and fails on Linux (the same class as
AgentFactory KI-18). The working tree may be CRLF - that is what a Windows
checkout with core.autocrlf=true looks like - so only the index is checked.

Exit codes
    0  PASS
    2  FAIL: at least one tracked file is stored with CRLF (or mixed) endings
    3  IO / usage error (not a git checkout, git missing)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BAD = {"i/crlf", "i/mixed"}


def scan(root: Path) -> list[tuple[str, str]]:
    done = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--eol"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or "git ls-files --eol failed")
    offenders: list[tuple[str, str]] = []
    for line in done.stdout.splitlines():
        head, _, path = line.partition("\t")
        index_eol = next((field for field in head.split() if field.startswith("i/")), "")
        if index_eol in BAD:
            offenders.append((path, index_eol))
    return offenders


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail when a tracked file is stored with CRLF.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)

    try:
        offenders = scan(args.root)
    except (OSError, RuntimeError) as exc:
        print(f"EOL GATE: ERROR {exc}", file=sys.stderr)
        return 3

    if offenders:
        print(f"EOL GATE: FAIL  {len(offenders)} tracked file(s) stored with CRLF")
        for path, index_eol in offenders[:50]:
            print(f"  ! {index_eol}  {path}")
        print("  fix: git add --renormalize <path> (or set '* text=auto eol=lf' in .gitattributes)")
        return 2

    total = len(
        subprocess.run(
            ["git", "-C", str(args.root), "ls-files"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout.splitlines()
    )
    print(f"EOL GATE: PASS  tracked={total}  stored=LF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
