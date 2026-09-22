# -*- coding: utf-8 -*-
"""E17 stats: paired analysis of judge scores (A vs B vs D).

Joins token scores with mapping.json, aggregates per (function, mode), and
reports means, paired t-test, Cohen's d and bootstrap CI for B-A and B-D.
Also computes a manipulation check: share of answers that mention one of
their provided test names (B/D) — replaces the judge's evidence_usage metric.
"""
import sys
import json
import math
import random
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
JUDGE = ROOT / "experiments/bootstrap/e17_judge"
MODES = ("A_baseline", "B_runtime", "D_shuffled")


def load_scores():
    mapping = json.loads((JUDGE / "mapping.json").read_text(encoding="utf-8"))
    scores = {}
    for path in sorted(JUDGE.glob("shard_*.scores.json")):
        for it in json.loads(path.read_text(encoding="utf-8")):
            scores[it["token"]] = it
    return mapping, scores


def paired_stats(diffs):
    n = len(diffs)
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    if sd == 0:
        return mean, 0.0, float("nan"), float("inf")
    t = mean / (sd / math.sqrt(n))
    try:
        from scipy import stats  # type: ignore
        p = 2 * stats.t.sf(abs(t), df=n - 1)
    except Exception:
        p = float("nan")
    return mean, mean / sd, p, t


def bootstrap_ci(diffs, n_boot=10000, seed=7):
    random.seed(seed)
    n = len(diffs)
    means = sorted(sum(random.choice(diffs) for _ in range(n)) / n for _ in range(n_boot))
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot)]


def manipulation_check():
    data = json.loads(
        (ROOT / "experiments/bootstrap/e17_pilot_data.json").read_text(encoding="utf-8")
    )
    answers = json.loads(
        (ROOT / "experiments/bootstrap/e17_pilot_answers.json").read_text(encoding="utf-8")
    )
    by_id = {a["id"]: a for a in answers["answers"]}
    print("\nmanipulation check — share of answers mentioning a provided test name:")
    for mode in MODES:
        hit = tot = 0
        for f in data["functions"]:
            names = f["modes"][mode]["tests"]
            if not names:
                continue
            tot += 1
            answer = by_id[f["id"]]["modes"][mode]["answer"]
            short = [n.split("::")[-1] for n in names]
            if any(s in answer for s in short):
                hit += 1
        print(f"  {mode:12} {hit}/{tot} = {hit / tot:.0%}" if tot else f"  {mode:12} n/a")


def main() -> None:
    mapping, scores = load_scores()
    missing = [t for t in mapping if t not in scores]
    if missing:
        print("MISSING tokens:", missing)
        return

    by_func = defaultdict(dict)
    for token, meta in mapping.items():
        by_func[meta["id"]][meta["mode"]] = scores[token]

    metrics = [m for m in ("accuracy", "completeness", "safety") if m in next(iter(scores.values()))]
    print(f"functions: {len(by_func)} | tokens: {len(scores)} | metrics: {metrics}")

    print("\nper-mode means:")
    for metric in metrics:
        row = {}
        for mode in MODES:
            vals = [by_func[f][mode][metric] for f in by_func if mode in by_func[f]]
            row[mode] = sum(vals) / len(vals)
        print(f"  {metric:16} A={row['A_baseline']:.2f}  B={row['B_runtime']:.2f}  D={row['D_shuffled']:.2f}")

    for metric in metrics:
        for hi, lo in (("B_runtime", "A_baseline"), ("B_runtime", "D_shuffled")):
            diffs = [
                by_func[f][hi][metric] - by_func[f][lo][metric]
                for f in by_func
                if hi in by_func[f] and lo in by_func[f]
            ]
            mean, d, p, t = paired_stats(diffs)
            lo_ci, hi_ci = bootstrap_ci(diffs)
            wins = sum(1 for x in diffs if x > 0)
            losses = sum(1 for x in diffs if x < 0)
            print(f"\n{metric}: {hi} - {lo}")
            print(f"  mean_diff={mean:+.3f}  d={d:+.3f}  t={t:+.3f}  p={p:.4f}")
            print(f"  bootstrap95%=[{lo_ci:+.3f}, {hi_ci:+.3f}]  wins/losses/ties="
                  f"{wins}/{losses}/{len(diffs) - wins - losses}")

    manipulation_check()


if __name__ == "__main__":
    main()
