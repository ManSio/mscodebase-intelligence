#!/usr/bin/env python3
"""Duplicate-run-file gate: an inflated denominator is a defect, not a rounding error.

A "run" is one model invocation whose output lands in one file. When two run
files are byte-identical, the second invocation did not produce independent
evidence: it is a copy. Any manifest that counts it as a separate run inflates
its denominator and dilutes every rate derived from it. Precedent (2026-09-26,
F4b): `results/f4b/symptom/longcat-2.0/run_longcat-2.0_2.txt` and `run_..._5.txt`
were the same git blob, while the manifest claimed `runs_per_model.longcat-2.0=5`
and `total_runs=22`. 22 files existed, 21 were distinct.

WHAT COUNTS AS A "RUN FILE" (narrow on purpose):
    - name starts with `run_`            (run_*.txt / run_*.json / run_*.jsonl / any ext)
    - or name starts with `ans_` and ends in `.txt`
`work/` subdirectories ARE INCLUDED, not skipped: `results/f5judged/work/` holds
per-trial `ans_*.txt` files, and a duplicated trial there corrupts the judge
input exactly the same way. Skipping it would hide the defect in the one place
it is most likely. Only `__pycache__` and `.git` are excluded (build/VCS noise,
never run artifacts). Zero-byte files are excluded from duplicate grouping and
reported separately as `empty_files`: two identical *empty* files are not
evidence of a duplicated run, they are evidence of zero runs.

MEASURED FALSE-POSITIVE RISK IN `ans_` FILES (2026-10-06, `results/f5judged/work`):
    640 ans_*.txt files -> 290 distinct digests, mean file size 241 bytes.
These files hold a model's SHORT answer, so two trials by the same model can be
byte-identical because the answer genuinely was the same — that is not a copied
run. Contrast `f4b`: 22 run_*.txt files at ~4KB each -> exactly 1 duplicate
group. So on `ans_*` input this gate is a HIGH-RECALL, LOW-PRECISION screen: a
group there is a REVIEW QUEUE, not a proven defect. Treat `run_*` findings as
BLOCK-worthy and `ans_*` findings as "inspect the pair before concluding". The
gate does not suppress either, because a suppressed `ans_*` class is how a real
duplicated judge input stays invisible; the interpretation burden is the
caller's, and the numbers to make that judgement are printed.

DUPLICATE RULE: sha256 over RAW BYTES (no normalisation — a CRLF/LF difference
is a real difference in what was stored). No newline or encoding normalisation,
deliberately, unlike `negative_controls_runner._digest_files`.

MANIFEST CROSS-CHECK: recursive JSON walk collecting every int under the key
names `runs`, `runs_per_model`, `total_runs`, `n_runs`, plus any dict mapping a
model name to an int. Each declared int is reported with its JSON path.

    SCOPE TOLERANCE — a declared count is MATCH (non-blocking) when it equals the
    count at ANY scope it could plausibly describe:
      1. tree-wide distinct count,
      2. any leaf directory's distinct count,
      3. per-model distinct count (only when the model key matches >=1 filename).
    Otherwise MISMATCH -> BLOCK. Rationale: manifests legitimately declare a
    per-model or per-stream count rather than a sum, so comparing a per-model
    declaration against a tree-wide total would manufacture false BLOCKs — a
    guard that cries wolf gets disabled. When the declared value matches no
    scope it is reported as UNRESOLVED (informational, non-blocking) rather than
    as a fabricated accusation. MISMATCH and duplicates both exit 1.

USAGE:
    python scripts/check_duplicate_runs.py <results-dir-or-experiment-dir>
    python scripts/check_duplicate_runs.py <dir> --json
    python scripts/check_duplicate_runs.py <dir> --manifest <path>
    python scripts/check_duplicate_runs.py --selftest

EXIT CODES (repo convention — obey exactly):
    0 = no duplicates and no count mismatch
    1 = duplicates found and/or a declared/actual mismatch (BLOCK)
    2 = target missing, or the run-file population is EMPTY.
        MUST NOT print "0 duplicates, all clear": a rate on an empty set is not
        a result (§19.6). Prints `ERROR: no run files found under <path>` to
        stderr and exits 2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

# §5.9 ENCODING SAFETY (Windows): cp1251 cannot encode the markers printed here
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — codec switch is best-effort
        pass
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — codec switch is best-effort
        pass

REPO = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {"__pycache__", ".git"}
COUNT_KEYS = {"runs", "runs_per_model", "total_runs", "n_runs"}


def _is_run_file(path: Path) -> bool:
    """Narrow run-artifact rule — see module docstring for the rationale."""
    name = path.name
    return name.startswith("run_") or (name.startswith("ans_") and name.endswith(".txt"))


def _collect_runs(target: Path) -> tuple[list[Path], list[Path]]:
    """(run files, zero-byte run files). Excludes __pycache__/.git only."""
    runs: list[Path] = []
    empty: list[Path] = []
    for p in sorted(target.rglob("*")):
        if any(part in EXCLUDED_DIRS for part in p.relative_to(target).parts[:-1]):
            continue
        if not p.is_file() or not _is_run_file(p):
            continue
        runs.append(p)
        if p.stat().st_size == 0:
            empty.append(p)
    return runs, empty


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _find_duplicates(runs: list[Path], root: Path, empty: set[Path]) -> list[dict[str, Any]]:
    groups: dict[str, list[Path]] = {}
    for p in runs:
        if p in empty:
            continue
        groups.setdefault(_digest(p), []).append(p)
    out: list[dict[str, Any]] = []
    for digest, files in groups.items():
        if len(files) > 1:
            out.append({
                "sha256": digest,
                "files": [str(f.relative_to(root)) for f in files],
                "file_count": len(files),
                "distinct_runs": 1,
            })
    return sorted(out, key=lambda g: g["sha256"])


def _leaf_dir(p: Path, root: Path) -> str:
    return str(p.parent.relative_to(root)) if p.parent != root else "."


def _distinct_by_scope(runs: list[Path], empty: set[Path], root: Path) -> dict[str, Any]:
    """Distinct-digest counts per scope: tree-wide, per leaf dir, per model token."""
    usable = [p for p in runs if p not in empty]
    tree = len({_digest(p) for p in usable})
    leaves: dict[str, set[str]] = {}
    models: dict[str, set[str]] = {}
    for p in usable:
        leaves.setdefault(_leaf_dir(p, root), set()).add(_digest(p))
        name = p.name.lower()
        for part in name.replace(".", "-").split("_"):
            if part and not part.isdigit():
                models.setdefault(part, set()).add(_digest(p))
    return {
        "tree_distinct": tree,
        "leaf_distinct": {k: len(v) for k, v in sorted(leaves.items())},
        "model_distinct": {k: len(v) for k, v in sorted(models.items())},
    }


def _collect_declared(data: Any, path: str = "$") -> list[dict[str, Any]]:
    """Every int under a count key name, plus model->int dicts under those keys."""
    out: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            child = f"{path}.{key}"
            if key in COUNT_KEYS:
                if isinstance(value, bool):
                    pass
                elif isinstance(value, int):
                    out.append({"json_path": child, "value": value, "model": None, "key": key})
                elif isinstance(value, dict):
                    for mkey, mval in value.items():
                        if isinstance(mval, int) and not isinstance(mval, bool):
                            out.append({"json_path": f"{child}.{mkey}", "value": mval,
                                        "model": mkey, "key": key})
            out.extend(_collect_declared(value, child))
    elif isinstance(data, list):
        for i, value in enumerate(data):
            out.extend(_collect_declared(value, f"{path}[{i}]"))
    return out


def _classify(declared: int, scopes: dict[str, Any], model: str | None, key: str) -> str:
    """MATCH / MISMATCH / UNRESOLVED against every scope the value could mean.

    MATCH      — the declared number is the truth at some scope it plausibly
                 describes (tree total, a leaf dir, or the named model's set).
    MISMATCH   — we know which scope the key refers to (a whole-experiment total,
                 or a model whose files we can actually see) and the number is not
                 that scope's distinct count. This is the inflated-denominator case.
    UNRESOLVED — the key's scope is not identifiable from filenames alone, so any
                 mismatch claim would be a guess. Reported, never used to BLOCK.
    """
    candidates = {scopes["tree_distinct"], *scopes["leaf_distinct"].values()}
    if model:
        candidates |= set(scopes["model_distinct"].values())
    if declared in candidates:
        return "MATCH"
    is_total = key in {"total_runs", "n_runs"}
    model_token = str(model).lower().replace(".", "-") if model else None
    model_files_seen = bool(model_token) and model_token in scopes["model_distinct"]
    if is_total or model_files_seen:
        return "MISMATCH"
    return "UNRESOLVED"


def evaluate(target: Path, manifest_path: Path | None) -> tuple[dict[str, Any], int]:
    """Core check. Returns (report, exit_code). Pure w.r.t. the filesystem."""
    report: dict[str, Any] = {"target": str(target), "manifest": None}
    if not target.exists() or not target.is_dir():
        report["error"] = f"ERROR: target not found: {target}"
        return report, 2

    runs, empty = _collect_runs(target)
    if not runs:
        report["error"] = f"ERROR: no run files found under {target}"
        return report, 2

    empty_set = set(empty)
    report["run_files"] = len(runs)
    report["empty_files"] = [str(p.relative_to(target)) for p in empty]
    report["duplicate_groups"] = _find_duplicates(runs, target, empty_set)
    scopes = _distinct_by_scope(runs, empty_set, target)
    report["distinct_runs"] = scopes["tree_distinct"]
    report["leaf_distinct"] = scopes["leaf_distinct"]

    mismatches: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    if manifest_path is not None:
        report["manifest"] = str(manifest_path)
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — unparseable manifest is a real finding
            report["manifest_error"] = f"{type(exc).__name__}: {exc}"
            mismatches.append({"json_path": "$", "declared": None, "status": "MANIFEST_UNREADABLE"})
        else:
            declared = []
            for item in _collect_declared(data):
                entry = {"json_path": item["json_path"], "declared": item["value"],
                         "status": _classify(item["value"], scopes, item["model"], item["key"])}
                declared.append(entry)
                if entry["status"] == "MISMATCH":
                    mismatches.append(entry)
                elif entry["status"] == "UNRESOLVED":
                    unresolved.append(entry)
            report["declared_counts"] = declared
    report["mismatches"] = mismatches
    report["unresolved"] = unresolved

    duplicates = report["duplicate_groups"]
    blocked = bool(duplicates) or bool(mismatches)
    report["verdict"] = "BLOCK" if blocked else "PASS"
    return report, (1 if blocked else 0)


def render(report: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if "error" in report:
        print(report["error"], file=sys.stderr)
        return
    print(f"target:   {report['target']}")
    print(f"manifest: {report['manifest'] or '(none found)'}")
    print(f"run files: {report['run_files']}   distinct runs: {report['distinct_runs']}")
    if report["empty_files"]:
        print(f"  NOTE: {len(report['empty_files'])} zero-byte run file(s) excluded from "
              f"duplicate grouping (evidence of zero runs, not of a duplicate)")
    groups = report["duplicate_groups"]
    if groups:
        print(f"DUPLICATES: {len(groups)} digest(s) shared by more than one run file")
        for g in groups:
            print(f"  sha256 {g['sha256'][:16]}...  files={g['file_count']}  distinct_runs={g['distinct_runs']}")
            for f in g["files"]:
                print(f"      {f}")
    else:
        print("DUPLICATES: none")
    if "declared_counts" in report:
        print("manifest declared counts:")
        for d in report["declared_counts"]:
            print(f"  {d['status']:<10} {d['json_path']} = {d['declared']}")
    if report["mismatches"]:
        print(f"MISMATCH: {len(report['mismatches'])} declared count(s) match no observed scope")
    for u in report["unresolved"]:
        print(f"  UNRESOLVED (informational) {u['json_path']} = {u.get('declared')}")
    print(f"VERDICT: {report['verdict']}")


def selftest() -> int:
    """Negative + positive control: the gate MUST be able to fail (протокол Тома).

    A gate that cannot fail is indistinguishable from a gate that does nothing.
    """
    cases: list[tuple[str, int, callable]] = [
        ("(a) two identical files, manifest declares 2", 1, lambda d: _case_a(d)),
        ("(b) three distinct files, manifest declares 3", 0, lambda d: _case_b(d)),
        ("(c) empty dir -> population empty", 2, lambda d: _case_c(d)),
        ("(d) two identical files, manifest declares 1", 1, lambda d: _case_d(d)),
        ("(e) manifest count correct (2) but files duplicated", 1, lambda d: _case_e(d)),
    ]
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        for i, (name, expected, build) in enumerate(cases):
            case_dir = base / f"case_{i}"
            case_dir.mkdir()
            manifest = build(case_dir)
            _report, actual = evaluate(case_dir, manifest)
            status = "ok" if actual == expected else "DEVIATION"
            if actual != expected:
                failures += 1
            print(f"  [{status}] {name}: expected exit {expected}, got {actual}")
    if failures:
        print(f"SELFTEST FAILED: {failures}/{len(cases)} case(s) deviated")
        return 1
    print(f"SELFTEST OK: {len(cases)}/{len(cases)} cases behaved as declared "
          f"(the gate can fail on duplicates, on empty population, and is green on clean input)")
    return 0


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _manifest(path: Path, body: dict[str, Any]) -> Path:
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _case_a(d: Path) -> Path:
    _write(d / "run_m_1.txt", "same\n")
    _write(d / "run_m_2.txt", "same\n")
    return _manifest(d / "manifest.json", {"runs": 2})


def _case_b(d: Path) -> Path:
    _write(d / "run_m_1.txt", "one\n")
    _write(d / "run_m_2.txt", "two\n")
    _write(d / "run_m_3.txt", "three\n")
    return _manifest(d / "manifest.json", {"runs": 3})


def _case_c(d: Path) -> Path:
    return _manifest(d / "manifest.json", {"runs": 0})


def _case_d(d: Path) -> Path:
    _write(d / "run_m_1.txt", "same\n")
    _write(d / "run_m_2.txt", "same\n")
    return _manifest(d / "manifest.json", {"runs": 1})


def _case_e(d: Path) -> Path:
    _write(d / "run_m_1.txt", "same\n")
    _write(d / "run_m_2.txt", "same\n")
    _write(d / "run_m_3.txt", "different\n")
    return _manifest(d / "manifest.json", {"runs": 2})  # distinct count is honest; files are not


def main() -> int:
    ap = argparse.ArgumentParser(description="Duplicate-run-file / inflated-denominator gate")
    ap.add_argument("target", nargs="?", help="results dir or experiment dir (recursive)")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--manifest", default=None, help="manifest.json path (default: auto-detect in target)")
    ap.add_argument("--selftest", action="store_true", help="prove the gate can fail")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.target:
        ap.error("target is required (or use --selftest)")

    target = Path(args.target)
    if not target.is_absolute():
        target = (REPO / target) if (REPO / target).exists() else target

    manifest: Path | None
    if args.manifest:
        manifest = Path(args.manifest)
        if not manifest.is_absolute():
            manifest = REPO / manifest
        if not manifest.exists():
            report = {"error": f"ERROR: manifest not found: {manifest}"}
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print(report["error"], file=sys.stderr)
            return 2
    else:
        auto = target / "manifest.json"
        manifest = auto if auto.is_file() else None

    report, code = evaluate(target, manifest)
    render(report, args.json)
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 — top-level guard must report and exit non-zero
        import traceback

        traceback.print_exc()
        raise SystemExit(2)
