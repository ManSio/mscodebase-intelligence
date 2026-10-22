"""Generate frozen/MANIFEST.json with sha256 for every frozen input."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXPERIMENT = Path(__file__).resolve().parents[1]
FROZEN = EXPERIMENT / "frozen"
OUT = FROZEN / "MANIFEST.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect() -> list[dict]:
    files = []
    for path in sorted(FROZEN.rglob("*")):
        if not path.is_file() or path == OUT:
            continue
        if "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        rel = path.relative_to(FROZEN).as_posix()
        files.append({
            "path": rel,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    return files


def check(files: list[dict]) -> int:
    if not OUT.is_file():
        print(f"VERIFY FAIL: {OUT} is missing")
        return 2
    recorded = json.loads(OUT.read_text(encoding="utf-8"))
    recorded_files = recorded.get("files", [])
    if recorded_files != files:
        print("VERIFY FAIL: frozen inputs differ from MANIFEST.json")
        old = {f["path"]: f for f in recorded_files}
        new = {f["path"]: f for f in files}
        for path in sorted(set(old) - set(new)):
            print(f"  missing now: {path}")
        for path in sorted(set(new) - set(old)):
            print(f"  new file: {path}")
        for path in sorted(set(old) & set(new)):
            if old[path] != new[path]:
                print(f"  changed: {path}")
        return 2
    print(f"VERIFY: PASS ({len(files)} files)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify manifest instead of writing it")
    args = parser.parse_args()

    files = collect()
    if args.check:
        return check(files)

    manifest = {
        "experiment": "microtask_vs_single",
        "date": "2026-10-20",
        "status": "pre_registered_blocked",
        "question": "planner + isolated microtask workers vs one OpenCode session",
        "pilot": {
            "corpus": "frozen/repo (tinycalc)",
            "tasks": ["P1_mean", "P2_money"],
            "arms": ["A", "D-open"],
            "runs_per_cell": 1,
            "claim_limit": "harness validation only; not evidence for H1-H6",
        },
        "models": {
            "planner": "opencode/deepseek-v4.1-flash-free",
            "baseline": "opencode/deepseek-v4.1-flash-free",
            "worker_open_fallback": "opencode-go/deepseek-v4.1-flash",
            "worker_tirtha": "tirtha/auto",
            "worker_tirtha_status": "BLOCKED: gateway exposes only auto; model ignored; OpenCode tool-call issue 2026-10-18",
            "worker_local": "not installed",
        },
        "isolation": {
            "config_root": "empty HOME/XDG for worker process",
            "project_config": "OPENCODE_DISABLE_PROJECT_CONFIG=1",
            "mcp": "mcpServers=[]; no global MCP in worker config",
            "canary": "CANARY_AGENTS",
        },
        "excludes": ["MANIFEST.json"],
        "n_files": len(files),
        "files": files,
    }
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {OUT} ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

