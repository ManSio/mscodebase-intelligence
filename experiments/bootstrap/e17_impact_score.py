# -*- coding: utf-8 -*-
"""E17 impact scoring: recall/precision of the regression-test set per mode.

Ground truth = the function's covering tests surfaced by the signal (B tests).
Predicted = test names the answer mentions (regex). No LLM judge — objective.
"""
import sys
import re
import json
import math
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
MODES = ("A_baseline", "B_runtime", "D_shuffled")
TEST_RE = re.compile(r"\btest_[A-Za-z0-9_]+")


def short(t: str) -> str:
    return t.split("::")[-1]


def paired(diffs):
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


def main() -> None:
    data = json.loads(
        (ROOT / "experiments/bootstrap/e17_pilot_data.json").read_text(encoding="utf-8")
    )
    answers = json.loads(
        (ROOT / "experiments/bootstrap/e17_pilot_answers.json").read_text(encoding="utf-8")
    )
    by_id = {a["id"]: a for a in answers["answers"]}

    per_mode_recall = defaultdict(list)
    per_mode_prec = defaultdict(list)
    per_mode_any = defaultdict(list)
    guessed = defaultdict(int)

    for f in data["functions"]:
        gt = {short(t) for t in f["modes"]["B_runtime"]["tests"]}
        for mode in MODES:
            pred = set(TEST_RE.findall(by_id[f["id"]]["modes"][mode]["answer"]))
            hit = pred & gt
            per_mode_recall[mode].append(len(hit) / len(gt) if gt else 0.0)
            per_mode_prec[mode].append(len(hit) / len(pred) if pred else 0.0)
            per_mode_any[mode].append(1.0 if hit else 0.0)
            if mode == "A_baseline" and hit:
                guessed[f["id"]] += 1

    print("per-mode means (n=30):")
    for label, store in (("recall", per_mode_recall), ("precision", per_mode_prec),
                         ("any-hit", per_mode_any)):
        a = sum(store["A_baseline"]) / 30
        b = sum(store["B_runtime"]) / 30
        d = sum(store["D_shuffled"]) / 30
        print(f"  {label:10} A={a:.3f}  B={b:.3f}  D={d:.3f}")

    for metric, store in (("recall", per_mode_recall), ("precision", per_mode_prec)):
        for hi, lo in (("B_runtime", "A_baseline"), ("B_runtime", "D_shuffled")):
            diffs = [store[hi][i] - store[lo][i] for i in range(len(store[hi]))]
            mean, d, p, t = paired(diffs)
            wins = sum(1 for x in diffs if x > 0)
            losses = sum(1 for x in diffs if x < 0)
            print(f"\n{metric}: {hi} - {lo}")
            print(f"  mean_diff={mean:+.3f}  d={d:+.3f}  t={t:+.3f}  p={p:.4f}  "
                  f"W/L/T={wins}/{losses}/{len(diffs) - wins - losses}")

    print(f"\nname-convention leak: A guessed a real covering test for "
          f"{len(guessed)}/30 functions")


if __name__ == "__main__":
    main()
