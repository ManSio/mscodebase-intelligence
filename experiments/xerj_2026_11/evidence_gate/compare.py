"""Compare the two arms and check the frozen kill criteria.

Metrics are per task, using the majority over repeats (a task counts only if
more than half of its runs hit the gold). Repeats exist because the channel set
is not stable: a slow grep can degrade and change the first row with no code
change (observed on XERJ P09, 2026-11-10).

Every number comes from results_control.json / results_treatment.json.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8")


def load(arm: str) -> list[dict]:
    path = HERE / f"results_{arm}.json"
    if not path.exists():
        raise SystemExit(f"missing {path}; run run_gate.py first")
    return json.loads(path.read_text(encoding="utf-8"))


def group(rows: list[dict], panel: str, kind: str) -> dict[str, list[dict]]:
    tasks: dict[str, list[dict]] = {}
    for row in rows:
        if row["panel"] == panel and row["kind"] == kind and row["valid"]:
            tasks.setdefault(row["id"], []).append(row)
    return tasks


def majority(runs: list[dict], key: str) -> bool:
    return sum(bool(run[key]) for run in runs) * 2 > len(runs)


def rate(tasks: dict[str, list[dict]], key: str) -> float:
    if not tasks:
        return float("nan")
    return round(sum(majority(runs, key) for runs in tasks.values()) / len(tasks), 3)


def flaky(tasks: dict[str, list[dict]]) -> int:
    """Tasks whose top1 or any outcome moved between repeats of one arm."""
    return sum(
        len({(bool(run["top1"]), bool(run["any"])) for run in runs}) > 1
        for runs in tasks.values()
    )


def p95(values: list[float]) -> float:
    values = sorted(values)
    return values[max(0, int(len(values) * 0.95) - 1)]


def main() -> int:
    control = load("control")
    treatment = load("treatment")
    print(f"{'bucket':<22}{'n':>4}{'top1 c':>9}{'top1 t':>9}{'any c':>8}{'any t':>8}"
          f"{'flaky':>7}{'lat c':>8}{'lat t':>8}")
    failures: list[str] = []
    for panel in ("xerj", "mcp_audit"):
        for kind in ("positive", "ambiguity", "negative"):
            c = group(control, panel, kind)
            t = group(treatment, panel, kind)
            if not c or not t:
                continue
            label = f"{panel}/{kind}"
            ct = statistics.mean(
                r["elapsed_s"] for rows in c.values() for r in rows
            )
            tt = statistics.mean(
                r["elapsed_s"] for rows in t.values() for r in rows
            )
            flaky_n = flaky(t) + flaky(c)
            print(f"{label:<22}{len(t):>4}{rate(c, 'top1'):>9}{rate(t, 'top1'):>9}"
                  f"{rate(c, 'any'):>8}{rate(t, 'any'):>8}{flaky_n:>7}"
                  f"{ct:>8.2f}{tt:>8.2f}")
            if rate(t, "any") < rate(c, "any"):
                failures.append(f"H1 {label}: any {rate(c, 'any')} -> {rate(t, 'any')}")
            if kind == "negative" and rate(t, "any") != rate(c, "any"):
                failures.append(f"H2 {label}: negative changed")
            if rate(t, "top1") < rate(c, "top1"):
                failures.append(f"H3 {label}: top1 {rate(c, 'top1')} -> {rate(t, 'top1')}")
            if kind == "ambiguity" and rate(t, "any") < rate(c, "any"):
                failures.append(f"H4 {label}: a gold was lost")

    c_lat = [r["elapsed_s"] for r in control if r["valid"]]
    t_lat = [r["elapsed_s"] for r in treatment if r["valid"]]
    print(f"\nlatency: control mean={statistics.mean(c_lat):.2f}s p95={p95(c_lat):.2f}s "
          f"(n={len(c_lat)})")
    print(f"         treatment mean={statistics.mean(t_lat):.2f}s p95={p95(t_lat):.2f}s "
          f"(n={len(t_lat)})  delta mean={statistics.mean(t_lat) - statistics.mean(c_lat):+.2f}s"
          f" p95={p95(t_lat) - p95(c_lat):+.2f}s")
    if statistics.mean(t_lat) > statistics.mean(c_lat) + 0.25:
        failures.append("H5 latency mean above +0.25s")
    if p95(t_lat) > p95(c_lat) + 0.60:
        failures.append("H5 latency p95 above +0.60s")

    det_path = HERE / "determinism.json"
    if det_path.exists():
        det = json.loads(det_path.read_text(encoding="utf-8"))
        print(f"determinism: {'PASS' if det.get('identical') else 'FAIL'} "
              f"({det.get('tasks')} tasks x {det.get('runs_per_task')} runs"
              + (f", unstable={det.get('unstable')}" if det.get("unstable") else "")
              + ")")
        if not det.get("identical"):
            failures.append("H6 determinism")

    print("\nverdict distribution (treatment, per task majority run 1):")
    for panel in ("xerj", "mcp_audit"):
        for kind in ("positive", "ambiguity", "negative"):
            tasks = group(treatment, panel, kind)
            if not tasks:
                continue
            dist: dict[str, int] = {}
            for runs in tasks.values():
                verdict = runs[0]["verdict"] or "-"
                dist[verdict] = dist.get(verdict, 0) + 1
            print(f"  {panel}/{kind}: {dist}")

    print("\nchanged tasks (majority over repeats):")
    changed = 0
    for panel in ("xerj", "mcp_audit"):
        for kind in ("positive", "ambiguity", "negative"):
            c = group(control, panel, kind)
            t = group(treatment, panel, kind)
            for task_id in sorted(set(c) & set(t)):
                before = (majority(c[task_id], "top1"), majority(c[task_id], "any"))
                after = (majority(t[task_id], "top1"), majority(t[task_id], "any"))
                if before != after:
                    changed += 1
                    print(f"  {panel:<10} {task_id:<5} top1 {before[0]}->{after[0]} "
                          f"any {before[1]}->{after[1]} "
                          f"verdict={t[task_id][0]['verdict'] or '-'} "
                          f"first={t[task_id][0]['files'][:1]}")
    if not changed:
        print("  (none)")

    print("\nkill criteria: " + ("PASS" if not failures else "FAIL"))
    for failure in failures:
        print(f"  - {failure}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
