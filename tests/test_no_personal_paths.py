"""Guard: no personal absolute paths or usernames in human-facing docs.

Regression guard for F0 (2026-09-26). The public repo must not leak a local
machine layout (`X:\\Project`) or the owner's local username in files a reader
sees. Scope is deliberately human-facing: root docs + docs/**/*.md (excluding
archive/generated) + the opencode plugin. Historical scratch (`experiments/**`,
`scripts/**`, tests, data JSON) is out of scope here — those are handled by a
separate reviewed pass, because edits there are paired with assertions.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

ROOT_DOCS = [
    "README.md", "AGENTS.md", "AI_INSTALLATION_PROMPT.md",
    "AGENT_DIARY.md", "EXPERIMENTS_LOG.md", "KNOWN_ISSUES.md", "WISDOM.md",
    "CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
]
EXCLUDED_DOC_PARTS = ("docs/archive/", "docs/generated/")

# Owner's local username (split so this test file does not flag itself) and a
# drive-rooted personal project path. `C:\Users\...` (generic) is allowed.
USERNAME = "mis" + "ha"
PATTERNS = [
    re.compile(rf"(?<![A-Za-z]){USERNAME}(?![A-Za-z])"),
    re.compile(r"[A-Za-z]:[\\/]Project"),
]


def _tracked_files() -> list[str]:
    """Only git-tracked files can leak publicly; a gitignored file cannot."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
            text=True, encoding="utf-8",
        )
    except OSError:
        return []
    if out.returncode != 0:
        return []
    return [x for x in out.stdout.split("\0") if x]


def _in_scope(rel: str) -> bool:
    if rel in ROOT_DOCS:
        return True
    if rel.startswith("docs/") and rel.endswith(".md"):
        return not any(rel.startswith(x) for x in EXCLUDED_DOC_PARTS)
    if rel.startswith(".opencode/plugin/") and rel.endswith(".ts"):
        return True
    return False


def _doc_files() -> list[Path]:
    files = [REPO / r for r in _tracked_files() if _in_scope(r)]
    if not files:
        pytest.skip("git not available / no tracked docs (clean CI without git)")
    return files


def test_no_personal_paths_in_docs() -> None:
    violations: list[str] = []
    for p in _doc_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pat in PATTERNS:
                if pat.search(line):
                    rel = p.relative_to(REPO).as_posix()
                    violations.append(f"{rel}:{lineno}: {line.strip()[:120]}")
    assert not violations, "personal path/username leak in docs:\n" + "\n".join(violations)
