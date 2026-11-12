"""Docs = code, part 2: every environment variable in CONFIGURATION.md must exist.

`check_docs_vs_installer.py` covers installer flags and client names. This guard
covers the other mechanical class of drift: a documented setting the code never
reads. It was written after finding `MSCODEBASE_MAX_FILE_SIZE_MB` in
`docs/*/CONFIGURATION.md` while `src/config/settings.py:425` reads
`MAX_FILE_SIZE_MB` (no prefix) — a name a user would copy and get nothing from.

Scope: names in the first column of the tables in `docs/en/CONFIGURATION.md`,
looked up in the code corpus (src/, scripts/, adapters/, .opencode/, .githooks/,
.env.example, install.py). Defaults are not compared here: they live in lambdas
and conditional expressions, and a wrong comparison is worse than none.

Exit: 0 clean, 1 violations, 2 nothing to check (a guard that finds no variables
proves nothing).

Usage:
    python scripts/check_docs_vs_config.py [--root .]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VAR_RE = re.compile(r"`([A-Z][A-Z0-9_]{2,})`")

CORPUS_GLOBS = (
    "src/**/*.py",
    "scripts/**/*.py",
    "adapters/**/*.py",
    "install.py",
    ".env.example",
    ".opencode/**/*.ts",
    ".githooks/*",
)

# Tokens that look like variables but are documentation artefacts, not settings.
IGNORED = {
    "README",
    "JSON",
    "JSONC",
    "MCP",
    "LSP",
    "CI",
    "API",
    "HTTP",
    "SQL",
    "CPU",
    "GPU",
    "OS",
    "URL",
    "URI",
    "ID",
    "TTL",
    "LRU",
    "FTS",
    "BM25",
    "RCE",
    "AST",
    "VOR",
}


def documented_vars(config_doc: Path) -> list[str]:
    names: list[str] = []
    for line in config_doc.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("|"):
            continue
        first_cell = line.strip().strip("|").split("|")[0]
        for name in VAR_RE.findall(first_cell):
            if name in IGNORED or name in names:
                continue
            names.append(name)
    return names


def corpus(root: Path) -> str:
    chunks: list[str] = []
    for pattern in CORPUS_GLOBS:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return "\n".join(chunks)


def check(root: Path) -> tuple[list[str], int]:
    doc = root / "docs" / "en" / "CONFIGURATION.md"
    if not doc.is_file():
        return ["docs/en/CONFIGURATION.md not found"], 0
    names = documented_vars(doc)
    if not names:
        return ["no environment variables found in CONFIGURATION.md"], 0
    blob = corpus(root)
    missing = [n for n in names if n not in blob]
    return [f"CONFIGURATION.md documents {n!r}, the code never reads it" for n in missing], len(names)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()

    problems, checked = check(Path(args.root).resolve())
    if checked == 0 and problems:
        for problem in problems:
            print(f"  ✗ {problem}")
        print("docs=config guard: nothing proven")
        return 2
    for problem in problems:
        print(f"  ✗ {problem}")
    print(f"docs=config guard: {checked} variable(s) checked, {len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
