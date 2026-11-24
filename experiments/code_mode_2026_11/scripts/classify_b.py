"""Classify why arm B did not return the gold: refusal vs extraction miss."""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
raw = json.load(gzip.open(ROOT.parent / "results" / "raw_texts" / "arm_texts.json.gz",
                          "rt", encoding="utf-8"))
rows = json.loads((ROOT.parent / "results" / "arms.json").read_text(encoding="utf-8"))

lost = [r["id"] for r in rows if r["A"]["hit"] and not r["B"]["hit"]]
n_a = sum(1 for r in rows if r["A"]["hit"])
print(f"B lost gold where A had it: {len(lost)}/{n_a}")
buckets = {"refusal": [], "extraction": []}
for qid in lost:
    text = raw[qid]["B"]
    verdict = re.search(r'"verdict"\s*:\s*"([a-z_]+)"', text) or re.search(r"verdict[^a-z]{0,4}([a-z_]+)", text)
    is_refusal = bool(
        re.search(r'"(ask_rewrite|abstain|insufficient_evidence|clarify)"', text)
        or "нет идентификатора кода" in text
        or "no verified candidate" in text
    )
    buckets["refusal" if is_refusal else "extraction"].append(
        (qid, verdict.group(1) if verdict else "-", len(text))
    )
for k, v in buckets.items():
    print(f"\n{k}: {len(v)}")
    for item in v:
        print("  ", item)
print("\nrate total:", round(len(lost) / n_a, 3),
      "| extraction only:", round(len(buckets["extraction"]) / n_a, 3))
