"""Why E1 is negative: decompose each answer by cause, not by score.

Reads the stored raw answers (never the summary) and separates three different
failures that one accuracy number hides:

  cover   - the gold file does not appear anywhere in the merged answer
  rank    - the gold file IS in the answer but outside the top-10
  score   - the gold file is in the top-10, so this row is not a failure

Also counts which channels contributed to the answer and which were degraded.
"""
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).resolve().parent
rows = json.loads((HERE / "baseline.json").read_text(encoding="utf-8"))

ROW_RE = re.compile(r"^(\d+)\. (.+?):(\d+)  \[([^\]]+)\]", re.M)


def files_with_rank(text: str) -> list[tuple[int, str, list[str]]]:
    out = []
    for rank, path, _line, channels in ROW_RE.findall(text):
        clean = path.replace("\\", "/")
        clean = clean.split("MSCodeBase/", 1)[-1] if "MSCodeBase/" in clean else clean
        clean = clean.lstrip("/")
        out.append((int(rank), clean, channels.split("+")))
    return out


cause = Counter()
channel_hits = Counter()
degraded_counter = Counter()
per_task = []
for row in rows:
    if row.get("b_invalid") or '"ok": false' in row["b_text"][:300]:
        cause["invalid"] += 1
        continue
    ranked = files_with_rank(row["b_text"])
    for _rank, _path, chans in ranked:
        for ch in chans:
            channel_hits[ch] += 1
    for item in filter(None, (row["degraded"] or "").split(",")):
        degraded_counter[item.strip()] += 1

    if row["kind"] == "negative":
        if ranked:
            cause["negative_false_positive"] += 1
        else:
            cause["negative_correct"] += 1
        continue

    def present(gold: str) -> int:
        for rank, path, _chans in ranked:
            if gold in path:
                return rank
        return 0

    ranks = [present(g) for g in row["gold"]]
    if row["kind"] == "ambiguity":
        ok = all(r and r <= 10 for r in ranks)
        near = all(ranks) and not ok
        missing = not all(ranks)
    else:
        ok = any(r and r <= 10 for r in ranks)
        near = any(ranks) and not ok
        missing = not any(ranks)

    if ok:
        cause["ok"] += 1
    elif near:
        cause["ranked_below_10"] += 1
    elif missing:
        cause["absent_from_answer"] += 1
    per_task.append((row["id"], row["gold"], ranks, row["degraded"]))

print("=== cause ===")
for name, n in cause.most_common():
    print(f"  {name:<24} {n}")
print("\n=== channels that delivered a hit ===")
for name, n in channel_hits.most_common():
    print(f"  {name:<10} {n}")
print("\n=== degraded (answers affected) ===")
for name, n in degraded_counter.most_common():
    print(f"  {name:<24} {n}")
print("\n=== tasks whose gold is missing or low ===")
for task_id, gold, ranks, degraded in per_task:
    if ranks and all(r and r <= 10 for r in ranks):
        continue
    print(f"  {task_id:<4} gold={gold} ranks={ranks} degraded={degraded or '-'}")
