"""Fusion A/B: weights (shipped) vs pure RRF vs normalized weights (E65).

Frozen spec: `frozen/PLAN.md`, with Amendment 1 (latency is not a criterion —
it is measured and printed, but no arm wins or loses on it).

Panels: XERJ 24 + mcp_audit 17 + metamorphic 12 = 53 asks. Arms are rotated per
task so a warm cache cannot favour one of them; 3 repeats; per-task majority,
the same metric `run_gate.py` reports.

Run:
    python experiments/xerj_2026_11/fusion/run_fusion.py --runs 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EXP))
sys.path.insert(0, str(EXP / "evidence_gate"))
sys.path.insert(0, str(EXP / "metamorphic"))
sys.stdout.reconfigure(encoding="utf-8")

from run_baseline import score as canon_score  # noqa: E402
from run_gate import (  # noqa: E402
    VERDICT_RE,
    _files,
    _invalid,
    _norm,
    _panel_tasks,
    _tools_for,
)
from run_probe import parse as parse_metamorphic  # noqa: E402

from src.mcp.tools.investigate_tool import _fusion_mode  # noqa: E402

ARMS = ("weights", "rrf", "norm")
# Frozen panel size (XERJ 24 + mcp_audit 17 + metamorphic 12). A run whose
# panel differs from this is a smoke run, not a measurement.
FROZEN_PANEL = 53
PANELS = ("xerj", "mcp_audit", "metamorphic")
KINDS = ("positive", "ambiguity", "negative")


def _tasks() -> list[dict]:
    tasks = _panel_tasks()
    for row in parse_metamorphic():
        tasks.append({
            "panel": "metamorphic",
            "id": f"{row['base']}-{row['form']}",
            "kind": "positive",
            # `canon_score` expects a list, like the XERJ and mcp_audit panels.
            "gold": [row["gold"]],
            "question": row["question"],
            "root": ROOT,
        })
    return tasks


def _determinism(results: dict[str, list[dict]]) -> dict[str, int]:
    """Per arm: tasks whose returned file list changed between repeats.

    Two repeats can agree on `top1` and still return different rows; that is
    the difference between "the metric is stable" and "the arm is stable".
    """
    counts: dict[str, int] = {}
    for arm, rows in results.items():
        grouped: dict[str, set] = {}
        for row in rows:
            if row["valid"]:
                grouped.setdefault(row["id"], set()).add(
                    tuple(row["files"])
                )
        counts[arm] = sum(1 for seen in grouped.values() if len(seen) > 1)
    return counts


def _run(tool, task: dict, arm: str) -> dict:
    os.environ["MSCODEBASE_FUSION"] = arm
    os.environ["MSCODEBASE_EVIDENCE_GATE"] = "1"
    # Guard: if the switch did not take effect, every arm measures the shipped
    # formula and the A/B is a no-op that looks like a tie.
    if _fusion_mode() != arm:
        raise RuntimeError(f"env did not apply: {arm}")
    started = time.perf_counter()
    text = asyncio.run(
        tool.execute(query=task["question"], limit=8,
                     project_root=str(task["root"]))
    )
    elapsed = time.perf_counter() - started
    files = _norm(_files(text), task["root"])
    valid = not _invalid(text)
    verdict = VERDICT_RE.search(text)
    # Scoring is the panel's own function (`run_baseline.score`), not a copy:
    # gold is a list and an ambiguity task needs ALL golds. A re-implemented
    # suffix match silently scored every XERJ task False (found in audit).
    return {
        "arm": arm,
        "panel": task["panel"],
        "id": task["id"],
        "kind": task["kind"],
        "question": task["question"],
        "gold": task.get("gold"),
        "files": files,
        "top1": None if not valid else canon_score(task, files[:1]),
        "any": None if not valid else canon_score(task, files[:8]),
        "valid": valid,
        "verdict": verdict.group(1) if verdict else "",
        "elapsed_s": round(elapsed, 3),
    }


def run(tasks: list[dict], runs: int) -> dict[str, list[dict]]:
    tools = _tools_for({task["root"] for task in tasks})
    results: dict[str, list[dict]] = {arm: [] for arm in ARMS}
    for position, task in enumerate(tasks):
        for run_index in range(runs):
            shift = (position + run_index) % len(ARMS)
            order = ARMS[shift:] + ARMS[:shift]
            for arm in order:
                row = _run(tools[str(task["root"])], task, arm)
                row["run"] = run_index + 1
                results[arm].append(row)
                print(f"  r{run_index + 1} {arm:<8} {task['id']:<11} "
                      f"{task['panel']:<11} top1={row['top1']} "
                      f"any={row['any']} {row['verdict'] or '-':<9} "
                      f"{row['elapsed_s']:5.2f}s", flush=True)
    return results


def _majority(values: list) -> bool:
    bits = [v for v in values if v is not None]
    if not bits:
        return False
    return sum(bits) * 2 > len(bits)


def per_task(rows: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        if row["valid"]:
            grouped.setdefault(row["id"], []).append(row)
    return {
        task_id: {
            "panel": runs[0]["panel"],
            "kind": runs[0]["kind"],
            "top1": _majority([r["top1"] for r in runs]),
            "any": _majority([r["any"] for r in runs]),
            "flaky": len({r["top1"] for r in runs}) > 1
            or len({r["any"] for r in runs}) > 1,
        }
        for task_id, runs in grouped.items()
    }


def summarise(results: dict[str, list[dict]]) -> dict:
    table: dict[str, dict] = {}
    for arm in ARMS:
        tasks = per_task(results[arm])
        for panel in PANELS:
            for kind in KINDS:
                subset = [t for t in tasks.values()
                          if t["panel"] == panel and t["kind"] == kind]
                if not subset:
                    continue
                table[f"{arm}|{panel}/{kind}"] = {
                    "n": len(subset),
                    "top1": sum(t["top1"] for t in subset),
                    "any": sum(t["any"] for t in subset),
                    "flaky": sum(t["flaky"] for t in subset),
                }
    return table


def _print_table(table: dict) -> None:
    print("\nbucket                    n   top1 weights/rrf/norm   "
          "any weights/rrf/norm   flaky")
    buckets = sorted({k.split("|", 1)[1] for k in table})
    for bucket in buckets:
        cells = [table.get(f"{arm}|{bucket}") for arm in ARMS]
        if not cells[0]:
            continue
        n = cells[0]["n"]
        t = "/".join(f"{c['top1']:>2}" if c else " -" for c in cells)
        a = "/".join(f"{c['any']:>2}" if c else " -" for c in cells)
        f = "/".join(f"{c['flaky']:>2}" if c else " -" for c in cells)
        print(f"{bucket:<24} {n:>3}   {t:<22} {a:<22} {f}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0,
                        help="smoke: only the first N tasks; no criteria, no results")
    args = parser.parse_args()

    tasks = _tasks()
    if args.limit:
        tasks = tasks[:args.limit]
    print(f"tasks={len(tasks)} arms={len(ARMS)} runs={args.runs}", flush=True)
    results = run(tasks, args.runs)
    table = summarise(results)
    per_arm = {arm: per_task(results[arm]) for arm in ARMS}
    ids = sorted(set().union(*[set(v) for v in per_arm.values()]))

    # ── Measurement guards (red team, 2026-11-10) ────────────────────────────
    # A task that fails to run is dropped by `per_task`, which silently shrinks
    # the denominator and inflates every rate. Refuse to report in that case.
    # The panel size is pinned to the frozen 53: comparing coverage against
    # `len(tasks)` of the current run let a shrunken panel pass (round 2).
    invalid = {arm: sum(1 for r in results[arm] if not r["valid"])
               for arm in ARMS}
    coverage = {arm: len(per_arm[arm]) for arm in ARMS}
    drift = _determinism(results)
    same_rows = all(
        {tuple(r["files"]) for r in results[arm] if r["id"] == task_id}
        == {tuple(r["files"]) for r in results["weights"] if r["id"] == task_id}
        for task_id in ids for arm in ("rrf", "norm")
    )
    print("\nguards")
    print(f"  invalid runs: {invalid}")
    print(f"  scored tasks: {coverage} (frozen panel {FROZEN_PANEL})")
    print(f"  non-deterministic rows per arm: {drift}")
    print(f"  arms return different rows somewhere: {not same_rows}")

    if len(tasks) != FROZEN_PANEL:
        print(f"SMOKE: {len(tasks)} of {FROZEN_PANEL} tasks — no criteria, "
              "results.json untouched.")
        _print_table(table)
        return 0
    if any(invalid.values()) or any(v != FROZEN_PANEL for v in coverage.values()):
        print("ABORT: a task did not run; rates over a shrunken panel are not "
              "publishable.")
        return 3
    if same_rows:
        print("ABORT: every arm returned identical rows — the switch did not "
              "take effect.")
        return 4

    _print_table(table)

    print("\nlatency (note only, Amendment 1 — not a criterion)")
    for arm in ARMS:
        values = [r["elapsed_s"] for r in results[arm] if r["valid"]]
        if values:
            print(f"  {arm:<8} mean={statistics.mean(values):.2f}s "
                  f"p95={sorted(values)[int(len(values) * 0.95) - 1]:.2f}s "
                  f"(n={len(values)})")

    print("\nchanged vs weights (per-task majority)")
    for arm in ("rrf", "norm"):
        for task_id in ids:
            left, right = per_arm["weights"][task_id], per_arm[arm][task_id]
            for key in ("top1", "any"):
                if left[key] != right[key]:
                    print(f"  {arm:<6} {task_id:<11} {key}={left[key]}->{right[key]}"
                          f"  {left['panel']}/{left['kind']}")

    def count(arm: str, panel: str, kind: str, key: str) -> int:
        return sum(t[key] for t in per_arm[arm].values()
                   if t["panel"] == panel and t["kind"] == kind)

    def total(arm: str, key: str) -> int:
        return sum(t[key] for t in per_arm[arm].values())

    gain_rrf = total("rrf", "top1") - total("weights", "top1")
    # F1 as frozen: "does not lose any@8 on the XERJ or mcp_audit panel". The
    # metamorphic loss is reported next to it, not folded in.
    lost_any_measured = sum(
        count("weights", p, "positive", "any") - count("rrf", p, "positive", "any")
        for p in ("xerj", "mcp_audit")
    )
    lost_any_all = sum(
        count("weights", p, "positive", "any") - count("rrf", p, "positive", "any")
        for p in PANELS
    )
    negatives = {
        arm: count(arm, "xerj", "negative", "top1")
        for arm in ARMS
    }
    neg_expected = sum(1 for t in per_arm["weights"].values()
                       if t["kind"] == "negative")

    print("\nkill criteria (frozen)")
    print(f"  F1 rrf any not lower on XERJ/mcp_audit: {lost_any_measured:+d} -> "
          f"{'PASS' if lost_any_measured <= 0 else f'FAIL (-{lost_any_measured})'}"
          f"   [all panels incl. metamorphic: {lost_any_all:+d}]")
    print(f"  F2 rrf top1 gain >= 2 tasks: {gain_rrf:+d} -> "
          f"{'PASS' if gain_rrf >= 2 else 'FAIL'}")
    norm_vs_rrf = total("norm", "top1") - total("rrf", "top1")
    print(f"  F3 norm beats rrf by < 2: {norm_vs_rrf:+d} -> "
          f"{'PASS' if norm_vs_rrf < 2 else 'FAIL'}")
    print(f"  F4 negatives still empty: xerj {negatives} (expected {neg_expected}) -> "
          f"{'PASS' if all(v == neg_expected for v in negatives.values()) else 'FAIL'}")

    (HERE / "results.json").write_text(
        json.dumps({
            "measurement": f"E65 fusion A/B, {args.runs} runs, {len(tasks)} tasks",
            "table": table,
            "per_task": per_arm,
        }, ensure_ascii=False, indent=1),
        encoding="utf-8", newline="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
