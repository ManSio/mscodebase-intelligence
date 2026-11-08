#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mechanical recheck of the facts this package rests on.

Why: a number or a file:line that cannot be reproduced today is dead for
everyone who reads it (AGENTS.md В§19.11). This script turns that rule into a
command. It fails loudly on drift, and it refuses to print "all good" when it
verified nothing (T10).

Modes
  (default)   local anchors + GitHub issue state
  --offline   local anchors only (no network, no gh)
  --freeze    write frozen/MANIFEST.sha256 from the frozen inputs
  --frozen    verify frozen/MANIFEST.sha256, fail on any change
  --selftest  prove the checker can fail (injected drift + empty population)

Exit codes: 0 all pass, 1 drift, 2 cannot verify (missing gh/network/inputs).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
FROZEN = Path(__file__).resolve().parent / "frozen"

# anchor: kind "local" -> path + regex must match (file may be a dir-relative path)
#         kind "github" -> repo + issue + expected state + expected created date
ANCHORS = [
    # our code: the capability the whole comparison rests on
    {"id": "ours.callgraph", "kind": "local", "path": "src/core/indexing/symbol_index.py",
     "regex": r"def build_call_graph"},
    {"id": "ours.impact", "kind": "local", "path": "src/core/indexing/symbol_index.py",
     "regex": r"def get_impact_analysis"},
    {"id": "ours.freshness_hash", "kind": "local", "path": "src/core/indexing/freshness.py",
     "regex": r"hash-confirm"},
    {"id": "ours.artifacts_outside", "kind": "local", "path": "src/core/artifact_paths.py",
     "regex": r"projects"},
    {"id": "ours.degraded", "kind": "local", "path": "src/mcp/tools/investigate_tool.py",
     "regex": r"degraded: List\[str\]"},
    # 2026-11-08: the two behaviours this package measured and changed
    {"id": "ours.investigate_exact", "kind": "local", "path": "src/mcp/tools/investigate_tool.py",
     "regex": r'exact\["per"\]\[ident\]'},
    {"id": "ours.grep_prefilter", "kind": "local", "path": "src/mcp/tools/grep_tool.py",
     "regex": r"Prefilter \(2026-11-08\)"},
    {"id": "ours.t10_guard", "kind": "local", "path": "tools/verification/heldout_g5.py",
     "regex": r"sys\.exit\(2\)"},
    {"id": "ours.test_callgraph", "kind": "local", "path": "tests/test_symbol_index_call_graph.py",
     "regex": r"def test_build_call_graph_callers"},
    # the frozen inputs this package freezes
    {"id": "frozen.tasks", "kind": "local", "path": "experiments/xerj_2026_11/frozen/benchmark_tasks.md",
     "regex": r"## Negative"},
    {"id": "frozen.hypotheses", "kind": "local", "path": "experiments/xerj_2026_11/frozen/HYPOTHESES.md",
     "regex": r"H4"},
    # the package's own decisions and findings (added 2026-11-08): if one of these
    # disappears, the package is no longer the thing its README describes.
    {"id": "pkg.decision", "kind": "local", "path": "experiments/xerj_2026_11/DECISION.md",
     "regex": r"да, с условиями"},
    {"id": "pkg.research", "kind": "local", "path": "experiments/xerj_2026_11/RESEARCH.md",
     "regex": r"## R5\."},
    {"id": "pkg.baseline", "kind": "local", "path": "experiments/xerj_2026_11/baseline_raw.txt",
     "regex": r"### run1 P01"},
    {"id": "pkg.tests", "kind": "local", "path": "tests/test_no_silent_success.py",
     "regex": r"test_agreement_between_non_exact_channels_is_not_confirmation"},
    # XERJ: the claims we quote about them
    {"id": "xerj.1791", "kind": "github", "repo": "xerj-org/xerj", "issue": 1791,
     "state": "open", "created": "2026-10-19"},
    {"id": "xerj.1793", "kind": "github", "repo": "xerj-org/xerj", "issue": 1793,
     "state": "closed", "created": "2026-10-19"},
    {"id": "xerj.3015", "kind": "github", "repo": "xerj-org/xerj", "issue": 3015,
     "state": "open", "created": "2026-11-06"},
    {"id": "xerj.3021", "kind": "github", "repo": "xerj-org/xerj", "issue": 3021,
     "state": "open", "created": "2026-11-06"},
    {"id": "xerj.3036", "kind": "github", "repo": "xerj-org/xerj", "issue": 3036,
     "state": "open", "created": "2026-11-07"},
]


def check_local(anchor: dict) -> tuple[str, str]:
    path = ROOT / anchor["path"]
    if not path.is_file():
        return "DRIFT", f"missing file {anchor['path']}"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "DRIFT", f"cannot read {anchor['path']}: {exc}"
    match = re.search(anchor["regex"], text)
    if not match:
        return "DRIFT", f"{anchor['path']}: /{anchor['regex']}/ not found"
    line = text.count("\n", 0, match.start()) + 1
    return "PASS", f"{anchor['path']}:{line}"


def check_github(anchor: dict) -> tuple[str, str]:
    cmd = ["gh", "api", f"repos/{anchor['repo']}/issues/{anchor['issue']}"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", timeout=45)
    except FileNotFoundError:
        return "UNKNOWN", "gh not installed"
    except subprocess.TimeoutExpired:
        return "UNKNOWN", "gh timed out"
    if proc.returncode != 0:
        return "UNKNOWN", f"gh failed: {(proc.stderr or '')[:120]}"
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return "UNKNOWN", "gh returned non-JSON"
    state = data.get("state", "?")
    created = (data.get("created_at") or "")[:10]
    problems = []
    if state != anchor["state"]:
        problems.append(f"state {state!r} != {anchor['state']!r}")
    if created != anchor["created"]:
        problems.append(f"created {created!r} != {anchor['created']!r}")
    if problems:
        return "DRIFT", "; ".join(problems)
    return "PASS", f"state={state} created={created}"


def run(anchors: list[dict], offline: bool, quiet: bool = False) -> tuple[int, list[tuple[str, str, str]]]:
    if not anchors:
        message = "REFUSING: empty anchor population (T10). Nothing was verified."
        print(message, file=sys.stdout if quiet else sys.stderr)
        return 2, []
    rows, drift, unknown = [], 0, 0
    for anchor in anchors:
        if anchor["kind"] == "local":
            status, detail = check_local(anchor)
        else:
            if offline:
                status, detail = "SKIP", "offline"
            else:
                status, detail = check_github(anchor)
        if status == "DRIFT":
            drift += 1
        if status == "UNKNOWN":
            unknown += 1
        rows.append((anchor["id"], status, detail))
    width = max(len(r[0]) for r in rows)
    for name, status, detail in rows:
        print(f"{name:<{width}}  {status:<6}  {detail}")
    print(f"\n{len(rows)} anchors: {sum(1 for r in rows if r[1]=='PASS')} PASS, "
          f"{drift} DRIFT, {unknown} UNKNOWN, "
          f"{sum(1 for r in rows if r[1]=='SKIP')} SKIP")
    if drift:
        return 1, rows
    if unknown:
        return 2, rows
    return 0, rows


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def do_freeze() -> int:
    files = sorted(p for p in FROZEN.glob("*") if p.is_file() and p.name != "MANIFEST.sha256")
    if not files:
        print("REFUSING: no frozen inputs (T10).", file=sys.stderr)
        return 2
    lines = [f"{sha256(p)}  {p.name}" for p in files]
    (FROZEN / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {FROZEN / 'MANIFEST.sha256'} ({len(files)} entries)")
    return 0


def do_verify_frozen() -> int:
    manifest = FROZEN / "MANIFEST.sha256"
    if not manifest.is_file():
        print("REFUSING: MANIFEST.sha256 missing; run --freeze first.", file=sys.stderr)
        return 2
    expected = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        expected[name] = digest
    if not expected:
        print("REFUSING: empty manifest (T10).", file=sys.stderr)
        return 2
    drift = 0
    for name, digest in sorted(expected.items()):
        path = FROZEN / name
        if not path.is_file():
            print(f"{name}  DRIFT   missing")
            drift += 1
        elif sha256(path) != digest:
            print(f"{name}  DRIFT   sha256 changed")
            drift += 1
        else:
            print(f"{name}  PASS")
    return 1 if drift else 0


def do_selftest() -> int:
    ok = True

    # 1) an injected impossible anchor must be reported as DRIFT (exit 1)
    fake = {"id": "selftest.missing", "kind": "local",
            "path": "experiments/xerj_2026_11/__does_not_exist__.py", "regex": "x"}
    code, _ = run([fake], offline=True, quiet=True)
    print(f"[selftest] injected drift -> exit {code} (want 1)")
    ok &= code == 1

    # 2) an empty population must refuse, not print success (exit 2, T10)
    code, _ = run([], offline=True, quiet=True)
    print(f"[selftest] empty population -> exit {code} (want 2)")
    ok &= code == 2

    # 3) the real anchors must pass locally (no network)
    code, _ = run([a for a in ANCHORS if a["kind"] == "local"], offline=True, quiet=True)
    print(f"[selftest] real local anchors -> exit {code} (want 0)")
    ok &= code == 0

    print("\nSELFTEST PASS" if ok else "\nSELFTEST FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="local anchors only")
    parser.add_argument("--freeze", action="store_true", help="write frozen/MANIFEST.sha256")
    parser.add_argument("--frozen", action="store_true", help="verify frozen/MANIFEST.sha256")
    parser.add_argument("--selftest", action="store_true", help="prove the checker can fail")
    args = parser.parse_args()

    if args.selftest:
        return do_selftest()
    if args.freeze:
        return do_freeze()
    if args.frozen:
        return do_verify_frozen()
    code, _ = run(ANCHORS, offline=args.offline)
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:  # never swallow: print and fail
        import traceback
        traceback.print_exc()
        print(f"FATAL: {exc}", file=sys.stderr)
        raise SystemExit(2)
