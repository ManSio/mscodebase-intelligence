"""Freeze-before-run manifest: hash inputs before a run, verify a raw file came after.

Why: E-OUTCOME-2 was run before its frozen hashes were recorded. Memory is not a
gate; this script is. It refuses empty input, refuses a raw file older than the
freeze, and has a --selftest that proves it can fail.

Usage:
    python scripts/freeze_manifest.py write --out frozen/MANIFEST.json frozen/A.md frozen/B.jsonl
    python scripts/freeze_manifest.py check --manifest frozen/MANIFEST.json --raw results/raw.jsonl
    python scripts/freeze_manifest.py selftest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_write(args) -> int:
    files = [Path(p) for p in args.files]
    if not files:
        print("T10: no input files", file=sys.stderr)
        return 2
    missing = [str(p) for p in files if not p.is_file()]
    if missing:
        print(f"ERROR: missing input files: {missing}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    manifest = {
        "frozen_at_epoch": now,
        "frozen_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "files": {str(p.as_posix()): sha256(p) for p in files},
    }
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"frozen {len(files)} file(s) -> {out}")
    for path, digest in manifest["files"].items():
        print(f"  {digest}  {path}")
    return 0


def cmd_check(args) -> int:
    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") or {}
    if not files:
        print("T10: manifest lists no files", file=sys.stderr)
        return 2
    failed = False
    for rel, expected in files.items():
        path = Path(rel)
        if not path.is_file():
            print(f"FAIL missing input: {rel}")
            failed = True
            continue
        actual = sha256(path)
        if actual != expected:
            print(f"FAIL changed input: {rel}\n  expected {expected}\n  actual   {actual}")
            failed = True
        else:
            print(f"OK   {rel}")

    if args.raw:
        raw = Path(args.raw)
        if not raw.is_file():
            print(f"FAIL raw file not found: {raw}")
            failed = True
        else:
            frozen_at = float(manifest.get("frozen_at_epoch", 0))
            if raw.stat().st_mtime + 1.0 < frozen_at:
                print(
                    f"FAIL raw predates freeze: {raw} mtime={raw.stat().st_mtime:.0f} "
                    f"< frozen_at={frozen_at:.0f}"
                )
                failed = True
            else:
                print(f"OK   raw is after freeze: {raw}")
    return 1 if failed else 0


def cmd_selftest(_args) -> int:
    """Prove the gate can fail. Any unexpected pass is itself a failure."""
    ok = True
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        a, b = base / "a.txt", base / "b.jsonl"
        a.write_text("alpha", encoding="utf-8")
        b.write_text("beta", encoding="utf-8")
        manifest = base / "MANIFEST.json"

        rc = cmd_write(argparse.Namespace(out=str(manifest), files=[str(a), str(b)]))
        assert rc == 0, f"write failed rc={rc}"

        raw = base / "raw.jsonl"
        time.sleep(0.05)
        raw.write_text("result", encoding="utf-8")
        rc = cmd_check(argparse.Namespace(manifest=str(manifest), raw=str(raw)))
        print(f"[selftest] clean check rc={rc} (expected 0)")
        ok &= rc == 0

        a.write_text("tampered", encoding="utf-8")
        rc = cmd_check(argparse.Namespace(manifest=str(manifest), raw=str(raw)))
        print(f"[selftest] tampered input rc={rc} (expected 1)")
        ok &= rc == 1

        # restore, then make raw older than the freeze
        a.write_text("alpha", encoding="utf-8")
        old = float(json.loads(manifest.read_text(encoding="utf-8"))["frozen_at_epoch"]) - 60
        import os
        os.utime(raw, (old, old))
        rc = cmd_check(argparse.Namespace(manifest=str(manifest), raw=str(raw)))
        print(f"[selftest] raw predates freeze rc={rc} (expected 1)")
        ok &= rc == 1

        rc = cmd_write(argparse.Namespace(out=str(manifest), files=[]))
        print(f"[selftest] empty input rc={rc} (expected 2)")
        ok &= rc == 2

    print(f"FREEZE MANIFEST SELFTEST: {'PASSED' if ok else 'FAILED'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write")
    w.add_argument("--out", required=True)
    w.add_argument("files", nargs="*")
    w.set_defaults(func=cmd_write)
    c = sub.add_parser("check")
    c.add_argument("--manifest", required=True)
    c.add_argument("--raw", default="")
    c.set_defaults(func=cmd_check)
    s = sub.add_parser("selftest")
    s.set_defaults(func=cmd_selftest)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
