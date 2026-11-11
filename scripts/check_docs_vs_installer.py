"""Docs = code: every installer flag named in documentation must exist.

G7 rule: no sentence in the docs may describe behaviour the code does not have.
Full semantic verification is a human job; this guard covers the mechanical part
that already produced a real defect — `docs/*/INSTALL.md` documented
`install.py --uninstall`, a flag the installer never had.

What it checks:
  1. every `install.py --flag` mentioned in docs/ and README.md exists in
     install.py (source literal or the usage text);
  2. every `--client <name>` mentioned in docs is accepted by
     `adapters/clients/snippets.CLIENTS`;
  3. every documented client has a section in docs/en/CLIENTS.md.

Exit codes: 0 clean, 1 violations, 2 nothing to check (empty corpus is a
failure, not a pass — a guard that finds no files proves nothing).

Usage:
    python scripts/check_docs_vs_installer.py [--root .]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.clients.snippets import CLIENTS  # noqa: E402

FLAG_RE = re.compile(r"install\.py\s+((?:--[a-z][a-z0-9-]*\s*)+)")
CLIENT_RE = re.compile(r"--client\s+([a-z][a-z0-9-]*)")

DOC_GLOBS = ("README.md", "docs/*/INSTALL.md", "docs/*/CLIENTS.md", "docs/*/DATA_MAP.md", "docs/en/FAQ.md")


def install_flags(root: Path) -> set[str]:
    """Flags the installer actually knows about (string literals in install.py)."""
    text = (root / "install.py").read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r'"(--[a-z][a-z0-9-]*)"', text))


def doc_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in DOC_GLOBS:
        files.extend(sorted(root.glob(pattern)))
    return [p for p in files if p.is_file()]


def check(root: Path) -> tuple[list[str], int]:
    flags = install_flags(root)
    files = doc_files(root)
    if not files:
        return ["no documentation found to check"], 0

    problems: list[str] = []
    checked_flags = 0
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in FLAG_RE.finditer(text):
            for flag in match.group(1).split():
                checked_flags += 1
                if flag not in flags:
                    problems.append(f"{path.relative_to(root)}: unknown installer flag {flag}")
        for match in CLIENT_RE.finditer(text):
            client = match.group(1)
            if client not in CLIENTS and client != "<name>":
                problems.append(
                    f"{path.relative_to(root)}: unknown client {client!r}"
                    f" (known: {', '.join(CLIENTS)})"
                )

    en_clients = root / "docs" / "en" / "CLIENTS.md"
    if en_clients.is_file():
        body = en_clients.read_text(encoding="utf-8", errors="replace")
        for client in CLIENTS:
            if f"--client {client}" not in body:
                problems.append(f"docs/en/CLIENTS.md: no copy-paste section for {client!r}")

    return problems, checked_flags


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()

    problems, checked = check(Path(args.root).resolve())
    if checked == 0 and not problems:
        print("docs=code guard: no installer flags referenced in docs — nothing proven")
        return 2
    for problem in problems:
        print(f"  ✗ {problem}")
    print(f"docs=code guard: {checked} flag reference(s) checked, {len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
