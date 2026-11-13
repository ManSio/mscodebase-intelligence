#!/usr/bin/env python
"""Mechanical form of «документация = код»: a changed .md must cite a real fact.

The rule in `AGENTS.md §8` says every documentation change points at the code it
describes. Two guards check *whole files*: installer flags
(`check_docs_vs_installer.py`) and environment variables (`check_docs_vs_config.py`).
Neither looks at the *change*, so "правка только цифры без ссылки" depended on a
human reviewer. This gate reads the diff and requires that a changed markdown
file adds at least one **verifiable** code reference:

    src/core/search/engine.py             path exists inside the repo
    src/core/search/engine.py::Searcher   symbol is DECLARED in that file
    src/core/search/engine.py:288         line number is inside the file
    install.py::_clean_cli                installer function exists
    install.py --with-models              flag is known to the installer
    MSCODEBASE_DOCS_MARGIN                name is read from the environment in code

Verification, not pattern matching: a fabricated path, a real path with an
invented or merely-mentioned symbol, a line past the end of the file, or a name
that is only a prefix of a real setting all fail.

Cosmetic edits are allowed when the file already cited code and the added lines
add no *new* claim: a line carrying digits/paths/flags counts as new unless the
exact same text already existed in the file before the change (moved lines are
not new claims).

Exit codes: 0 clean / not applicable, 1 violations, 3 internal limit exceeded or
unreadable input. Empty markdown input is reported explicitly, never silently.

Usage:
    python scripts/check_docs_refs.py --base origin/main
    python scripts/check_docs_refs.py --staged
    python scripts/check_docs_refs.py --diff-file change.diff
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

MAX_FILES = 200
MAX_ADDED_LINES = 20_000

# Registries, historical material and experiment artefacts are logs of runs,
# not descriptions of today (AGENTS §0.6: experiments are not indexed either).
EXEMPT_PREFIXES = (
    "docs/archive/",
    "docs/blog/",
    "docs/research/",
    "experiments/",
)
# Matched against the file NAME, so `docs/{en,ru,zh}/CHANGELOG.md` is covered too.
EXEMPT_NAMES = {
    "AGENT_DIARY.md",
    "KNOWN_ISSUES.md",
    "EXPERIMENTS_LOG.md",
    "WISDOM.md",
    "ISSUE.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "LICENSE.md",
}

PATH_RE = re.compile(
    r"(?P<path>(?:src|scripts|tests|adapters|tools)/[A-Za-z0-9_./-]+\.(?:py|sh|toml|json|yml|yaml))"
    r"(?:::(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)|:(?P<line>\d+))?"
)
INSTALLER_RE = re.compile(r"install\.py(?:::(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)|:(?P<line>\d+))?")
HOOK_RE = re.compile(r"(?P<path>\.githooks/[A-Za-z0-9_-]+|\.opencode/plugin/[A-Za-z0-9_.-]+)")
FLAG_RE = re.compile(r"install\.py\s+(--[a-z][a-z0-9-]*)")
VAR_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
CLAIM_RE = re.compile(
    r"(\d|--[a-z][a-z0-9-]*|(?:src|scripts|tests|adapters|tools)/|install\.py|"
    r"MSCODEBASE_|MSCB_|\.githooks/|\.opencode/)"
)

# A setting is a name the code actually reads from the environment.
ENV_READ_RE = re.compile(
    r"""(?:os\.getenv|os\.environ\.get|os\.environ\[|getenv|process\.env)(?:\(|\[|\.)\s*['"]?([A-Z][A-Z0-9_]{2,})"""
)

CORPUS_GLOBS = (
    "src/**/*.py",
    "scripts/**/*.py",
    "adapters/**/*.py",
    "install.py",
    ".opencode/**/*.ts",
    ".githooks/*",
)


@dataclass
class FileChange:
    path: str
    added: list[tuple[int, str]] = field(default_factory=list)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:200]}")
    return proc.stdout


def load_diff(repo: Path, *, staged: bool, base: str | None, diff_file: Path | None) -> str:
    if diff_file is not None:
        # Not every tool writes UTF-8 (PowerShell `>` writes UTF-16): say so
        # instead of raising a traceback (2026-11-14, found by feeding a real diff).
        try:
            return diff_file.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError as e:
            raise RuntimeError(f"{diff_file} is not UTF-8: {e}") from e
    args = ["diff", "--unified=0", "--no-color", "--", "*.md"]
    if staged:
        args.insert(1, "--cached")
        return _git(repo, *args)
    assert base, "either --staged, --base or --diff-file is required"
    merge_base = _git(repo, "merge-base", base, "HEAD").strip() or base
    return _git(repo, "diff", "--unified=0", "--no-color", merge_base, "HEAD", "--", "*.md")


def unquote_git_path(raw: str) -> str:
    """Decode git's C-quoted path (`"b/docs/ru/\\320\\244..."`)."""
    raw = raw.strip()
    if len(raw) < 2 or not (raw.startswith('"') and raw.endswith('"')):
        return raw
    body = raw[1:-1]
    out = bytearray()
    i = 0
    escapes = {"n": b"\n", "t": b"\t", "r": b"\r", "a": b"\a",
               "b": b"\b", "f": b"\f", "v": b"\v", '"': b'"', "\\": b"\\"}
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            oct_digits = body[i + 1: i + 4]
            if len(oct_digits) == 3 and all(c in "01234567" for c in oct_digits):
                out.append(int(oct_digits, 8))
                i += 4
                continue
            nxt = body[i + 1]
            out += escapes.get(nxt, nxt.encode("utf-8", "replace"))
            i += 2
            continue
        out += ch.encode("utf-8")
        i += 1
    return out.decode("utf-8", "replace")


def parse_diff(text: str) -> tuple[list[FileChange], int]:
    changes: list[FileChange] = []
    current: FileChange | None = None
    new_line = 0
    headers = 0
    for raw in text.splitlines():
        if raw.startswith("+++ "):
            headers += 1
            target = raw[4:].strip()
            if target == "/dev/null":
                current = None
                continue
            target = unquote_git_path(target)
            if target.startswith("b/"):
                target = target[2:]
            current = FileChange(path=target)
            changes.append(current)
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            new_line = int(m.group(1)) if m else 0
            continue
        if current is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            current.added.append((new_line, raw[1:]))
            new_line += 1
    return [c for c in changes if c.added], headers


def is_exempt(path: str) -> bool:
    return Path(path).name in EXEMPT_NAMES or path.startswith(EXEMPT_PREFIXES)


def corpus(repo: Path) -> str:
    chunks: list[str] = []
    for pattern in CORPUS_GLOBS:
        for p in repo.glob(pattern):
            if p.is_file():
                try:
                    chunks.append(p.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
    return "\n".join(chunks)


def env_names(text: str) -> set[str]:
    """Names the code actually reads from the environment (not any uppercase word)."""
    return set(ENV_READ_RE.findall(text))


def symbol_declared(body: str, symbol: str) -> bool:
    """A definition, not a mention: comments and docstrings must not count."""
    s = re.escape(symbol)
    patterns = (
        rf"(?m)^\s*(?:async\s+)?def\s+{s}\b",
        rf"(?m)^\s*class\s+{s}\b",
        rf"(?m)^\s*{s}\s*(?::[^=\n]+)?=",
        rf"(?m)^\s*{s}\s*:",
        rf"""(?m)^\s*['"]{s}['"]\s*:""",
    )
    return any(re.search(p, body) for p in patterns)


def _inside(repo: Path, candidate: Path) -> bool:
    try:
        resolved = candidate.resolve()
    except OSError:
        return False
    return resolved == repo.resolve() or repo.resolve() in resolved.parents


def _file_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def verify_reference(line: str, repo: Path, envs: set[str], flags: set[str]) -> str | None:
    """Return a description of the first verified reference in the line."""
    for m in FLAG_RE.finditer(line):
        if m.group(1) in flags:
            return f"flag {m.group(1)}"

    for m in HOOK_RE.finditer(line):
        target = repo / m.group("path")
        if _inside(repo, target) and target.exists():
            return f"path {m.group('path')}"

    for m in PATH_RE.finditer(line):
        rel = m.group("path")
        target = repo / rel
        if not _inside(repo, target) or not target.exists():
            continue
        symbol, lineno = m.group("symbol"), m.group("line")
        body = _file_text(target)
        if body is None:
            continue
        if symbol:
            if symbol_declared(body, symbol):
                return f"{rel}::{symbol}"
            continue
        if lineno:
            if 1 <= int(lineno) <= len(body.splitlines()):
                return f"{rel}:{lineno}"
            continue
        return f"path {rel}"

    for m in INSTALLER_RE.finditer(line):
        target = repo / "install.py"
        body = _file_text(target)
        if body is None:
            continue
        symbol, lineno = m.group("symbol"), m.group("line")
        if symbol:
            if symbol_declared(body, symbol):
                return f"install.py::{symbol}"
            continue
        if lineno:
            if 1 <= int(lineno) <= len(body.splitlines()):
                return f"install.py:{lineno}"
            continue
        # A bare `install.py` mention is not a fact about the code.

    for m in VAR_RE.finditer(line):
        if m.group(1) in envs:
            return f"env {m.group(1)}"
    return None


def _head_lines(repo: Path, path: str) -> set[str] | None:
    try:
        body = _git(repo, "show", f"HEAD:{path}")
    except RuntimeError:
        return None
    return {ln.strip() for ln in body.splitlines() if ln.strip()}


def _head_cites_code(repo: Path, path: str, envs: set[str], flags: set[str]) -> bool:
    try:
        body = _git(repo, "show", f"HEAD:{path}")
    except RuntimeError:
        return False
    return any(verify_reference(ln, repo, envs, flags) for ln in body.splitlines())


def installer_flags(repo: Path) -> set[str]:
    body = _file_text(repo / "install.py")
    if body is None:
        return set()
    return set(re.findall(r'"(--[a-z][a-z0-9-]*)"', body))


def check(repo: Path, diff_text: str) -> tuple[list[str], list[str], int]:
    files, headers = parse_diff(diff_text)
    if len(files) > MAX_FILES:
        return [f"diff touches {len(files)} markdown files (limit {MAX_FILES}) — refusing to pass"], [], len(files)
    total_added = sum(len(f.added) for f in files)
    if total_added > MAX_ADDED_LINES:
        return [f"diff adds {total_added} markdown lines (limit {MAX_ADDED_LINES}) — refusing to pass"], [], total_added
    if not files:
        return [], [f"no added markdown lines ({headers} file header(s): deletions/renames only)"], 0

    envs = env_names(corpus(repo))
    flags = installer_flags(repo)
    problems: list[str] = []
    notes: list[str] = []

    for change in files:
        if is_exempt(change.path):
            notes.append(f"exempt: {change.path}")
            continue
        verified = None
        for _lineno, text in change.added:
            verified = verify_reference(text, repo, envs, flags)
            if verified:
                break
        if verified:
            notes.append(f"ok: {change.path} -> {verified}")
            continue

        old_lines = _head_lines(repo, change.path) or set()
        new_claims = [
            text for _n, text in change.added
            if CLAIM_RE.search(text) and text.strip() not in old_lines
        ]
        if not new_claims and _head_cites_code(repo, change.path, envs, flags):
            notes.append(f"ok: {change.path} (cosmetic edit, file already cites code)")
            continue
        first = change.added[0][0]
        reason = "new claim without a reference" if new_claims else "file never cited code"
        problems.append(
            f"{change.path}:{first}: no verifiable code reference ({reason}; add "
            f"`src/…py`, `path::symbol`, `install.py --flag` or a setting read by the code)"
        )
    return problems, notes, len(files)


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:  # Windows console code pages crash on non-ASCII output (cp1252, 2026-11-14)
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--base", default=None)
    ap.add_argument("--diff-file", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    try:
        diff_text = load_diff(
            repo, staged=args.staged, base=args.base,
            diff_file=Path(args.diff_file) if args.diff_file else None,
        )
    except (RuntimeError, OSError, UnicodeDecodeError) as e:
        print(f"docs-refs: cannot read the diff: {e}", file=sys.stderr)
        return 3

    problems, notes, files_seen = check(repo, diff_text)
    hard_limit = any("refusing to pass" in p for p in problems)

    if args.json:
        print(json.dumps({"files": files_seen, "problems": problems, "notes": notes},
                         indent=2, ensure_ascii=False))
        return 3 if hard_limit else (0 if not problems else 1)

    for note in notes:
        print(f"  - {note}")
    for problem in problems:
        print(f"  FAIL {problem}")
    if files_seen == 0:
        print("docs-refs: no markdown additions in this diff — nothing to prove")
    else:
        print(f"docs-refs: {files_seen} markdown file(s) changed, {len(problems)} without a code reference")
    if hard_limit:
        return 3
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
