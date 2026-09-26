"""Closure-walk measurement for the personal-path guard (2026-09-27).

Hypothesis: `tests/test_no_personal_paths.py` reports clean because its scope
is human-facing docs only, while drive-rooted project paths and the owner's
username can still live in tracked files outside that scope (experiments,
scripts, tests, data JSON). A guard that certifies the wrong set is a true
statement about the wrong population.

Protocol (frozen-before-look):
  1. Load the frozen manifest (tracked files + sha256) and verify integrity.
  2. Run the same regexes as the guard against every tracked file.
  3. Partition hits into guard-scope vs outside-scope.
  4. Controls:
     POSITIVE  — a planted leak must be detected.
     NONE      — repo-relative paths (src/core/...) must not be flagged.

The test-suite files live outside the experiment tree by design. Deliberately
excluded from the positive control: nothing here edits the production guard;
this is a measurement script, not a fix.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "experiments" / "closure_walk" / "frozen" / "files_manifest_final.json"
RESULTS = REPO / "experiments" / "closure_walk" / "results" / "closure_walk.json"

ROOT_DOCS = [
    "README.md", "AGENTS.md", "AI_INSTALLATION_PROMPT.md",
    "AGENT_DIARY.md", "EXPERIMENTS_LOG.md", "KNOWN_ISSUES.md", "WISDOM.md",
    "CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
]
EXCLUDED_DOC_PARTS = ("docs/archive/", "docs/generated/")
USERNAME = "mis" + "ha"
PATTERNS = {
    "username": re.compile(rf"(?<![A-Za-z]){USERNAME}(?![A-Za-z])"),
    "drive_path": re.compile(r"[A-Za-z]:[\\/]Project"),
}


def _in_scope(rel: str) -> bool:
    if rel in ROOT_DOCS:
        return True
    if rel.startswith("docs/") and rel.endswith(".md"):
        return not any(rel.startswith(x) for x in EXCLUDED_DOC_PARTS)
    if rel.startswith(".opencode/plugin/") and rel.endswith(".ts"):
        return True
    return False


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _scan(text: str) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, pat in PATTERNS.items():
            m = pat.search(line)
            if m:
                hits.append({"line": lineno, "pattern": name, "match": m.group(0)})
    return hits


def _load_manifest() -> tuple[dict[str, Any], list[str]]:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = {e["path"]: e["sha256"] for e in raw["files"]}
    failures = []
    for rel, expected in entries.items():
        if rel == Path(__file__).relative_to(REPO).as_posix():
            continue  # сам скрипт изменяется после заморозки манифеста
        p = REPO / rel
        if not p.is_file():
            failures.append(f"missing:{rel}")
            continue
        actual = _sha256(p)
        if actual != expected:
            failures.append(f"modified:{rel}")
    return raw, failures


def _run_controls() -> dict[str, Any]:
    out: dict[str, Any] = {"positive": {}, "none": {}}
    with tempfile.TemporaryDirectory() as td:
        pos = Path(td) / "README.md"
        pos.write_text("Run on D:\\Project\\MSCodeBase as user misha.\n", encoding="utf-8")
        out["positive"]["file"] = "README.md (synthetic)"
        out["positive"]["hits"] = _scan(pos.read_text(encoding="utf-8"))

        none = Path(td) / "sample_repo_relative.md"
        none.write_text(
            "Guard check on src/core/indexing/parser.py — repo-relative only.\n",
            encoding="utf-8",
        )
        out["none"]["file"] = "sample_repo_relative.md (synthetic)"
        out["none"]["hits"] = _scan(none.read_text(encoding="utf-8"))
    return out


def main() -> int:
    raw, failures = _load_manifest()
    entries = raw["files"]
    violations: list[dict[str, Any]] = []
    in_scope_files = out_scope_files = 0
    per_top_dir: dict[str, int] = {}

    for e in entries:
        rel = e["path"]
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        hits = _scan(text)
        if not hits:
            continue
        scope = "in_scope" if _in_scope(rel) else "out_scope"
        if scope == "in_scope":
            in_scope_files += 1
        else:
            out_scope_files += 1
        top = rel.split("/", 1)[0]
        per_top_dir[top] = per_top_dir.get(top, 0) + 1
        for h in hits:
            violations.append({"file": rel, "scope": scope, **h})

    controls = _run_controls()
    ok = not failures and controls["positive"]["hits"] and not controls["none"]["hits"]
    payload = {
        "protocol": {
            "frozen_at": raw["generated"],
            "frozen_count": raw["count"],
            "patterns": list(PATTERNS),
            "controls": {
                "positive_must_hit": True,
                "none_must_miss": True,
            },
        },
        "integrity": {
            "failures": failures,
            "clean": not failures,
        },
        "scope_summary": {
            "in_scope_files_with_hits": in_scope_files,
            "out_scope_files_with_hits": out_scope_files,
            "total_files_with_hits": in_scope_files + out_scope_files,
            "out_scope_violations": sum(1 for v in violations if v["scope"] == "out_scope"),
        },
        "out_scope_violations": violations,
        "controls": controls,
        "verdict": {
            "passes_integrity": not failures,
            "positive_control_hit": bool(controls["positive"]["hits"]),
            "none_control_clean": not controls["none"]["hits"],
        },
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"integrity_clean={not failures} failures={len(failures)}")
    print(f"in_scope_files={in_scope_files} out_scope_files={out_scope_files}")
    print(f"out_scope_violations={payload['scope_summary']['out_scope_violations']}")
    print(f"positive_hit={bool(controls['positive']['hits'])} "
          f"none_clean={not controls['none']['hits']}")
    print(f"results={RESULTS.relative_to(REPO).as_posix()}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
