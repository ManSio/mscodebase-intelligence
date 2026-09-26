#!/usr/bin/env python3
"""Blind-mapper runner for experiment 4A (F4/F4b).

Replaces ad-hoc PowerShell + Tee calls, which mangled quotes and output
encoding on Windows. Runs `opencode run` via subprocess with an argument
list (no shell), captures bytes, decodes UTF-8, strips ANSI, and writes each
run to a UTF-8 file.

--variant is REQUIRED: reasoning budget is a known confound (Coin Flip Judge,
kappa=0.51), so an unpinned run must fail loudly instead of silently varying.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
MSG = ("For each numbered item in the attached handout, pick one entry from "
       "its index that best explains it, or NONE. Answer ONLY as a markdown "
       "table with columns: # and entry. Do not use tools.")
TMPL = """{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "mscodebase-intelligence": { "enabled": false },
    "msp-portfolio": { "enabled": false },
    "community-memory": { "enabled": false },
    "arclux": { "enabled": false }
  },
  "permission": { "edit": "deny", "bash": "deny", "webfetch": "deny",
                  "websearch": "deny", "external_directory": "deny" }
}
"""


def _opencode_bin() -> str:
    env = os.environ.get("OPENCODE_BIN")
    if env and Path(env).exists():
        return env
    found = shutil.which("opencode")
    if found:
        return found
    appdata = os.environ.get("APPDATA")
    if appdata:
        cand = Path(appdata) / "npm" / "opencode.cmd"
        if cand.exists():
            return str(cand)
    raise SystemExit("opencode binary not found (set OPENCODE_BIN)")


def run_one(bin_: str, model: str, variant: str, workdir: Path, handout: Path) -> str:
    cmd = [bin_, "run", MSG, "--model", model, "--pure", "--dir", str(workdir),
           f"--file={handout}", "--variant", variant]
    env = dict(os.environ, PYTHONUTF8="1", NO_COLOR="1")
    p = subprocess.run(cmd, capture_output=True, timeout=300, env=env)
    raw = (p.stdout or b"") + b"\n" + (p.stderr or b"")
    return ANSI.sub("", raw.decode("utf-8", errors="replace"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--runs", type=int, required=True)
    ap.add_argument("--handout", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    workdir = Path(args.outdir)
    workdir.mkdir(parents=True, exist_ok=True)
    cfg = workdir / "opencode.json"
    if not cfg.exists():
        cfg.write_text(TMPL, encoding="utf-8")
    handout = Path(args.handout).resolve()
    bin_ = _opencode_bin()
    slug = args.model.split("/")[-1]

    for i in range(1, args.runs + 1):
        out = run_one(bin_, args.model, args.variant, workdir, handout)
        f = workdir / f"run_{slug}_{i}.txt"
        f.write_text(out, encoding="utf-8")
        print(f"{slug} run {i}: {len(out)} chars -> {f.name}")
    (workdir / "manifest.json").write_text(json.dumps({
        "model": args.model, "variant": args.variant, "runs": args.runs,
        "handout": str(handout), "rule": "variant required (reasoning confound)",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - top-level guard reports and exits non-zero
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
