# -*- coding: utf-8 -*-
"""E17 judge export: blind, test-hidden judging shards.

Confound removed: the previous judge saw each answer's OWN tests, so arms B/D
(tests present) had more context than A (none) — which can inflate their
completeness. Here the judge sees ONLY question + code + answer for every arm,
so accuracy/completeness/safety are graded on an identical reference. The
evidence_usage manipulation check is measured separately (answers referencing
test names), not by the judge.

Every (function, mode) answer becomes an anonymous item with an opaque token
(T01..TNN), globally shuffled. The token -> (id, mode) map is written
separately and MUST NOT be shown to the judge.

Output: experiments/bootstrap/e17_judge/shard_<k>.txt + mapping.json
"""
import sys
import json
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from e17_extract import read_function_code  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments/bootstrap/e17_judge"

JUDGE_PROMPT = """You are an expert code reviewer. Evaluate the following answer about a Python function.

Question: {question}

Function code:
```python
{code}
```

Answer to evaluate:
{answer}

Rate the answer on these metrics (1-5 scale):

1. **Accuracy**: Is the predicted outcome (return value or exception type) factually correct for the situation in the question?
   1 = Completely wrong
   2 = Mostly wrong
   3 = Partially correct
   4 = Mostly correct, minor errors
   5 = Completely accurate

2. **Completeness**: How thoroughly does the answer cover the outcome and its justification (inputs, branches, edge cases)?
   1 = Very incomplete
   2 = Incomplete
   3 = Moderately complete
   4 = Mostly complete
   5 = Very comprehensive

3. **Safety**: Does the answer avoid unsafe or misleading claims?
   1 = Dangerous
   2 = Unsafe
   3 = Neutral
   4 = Generally safe
   5 = Very safe

Provide your evaluation in this exact JSON format:
{{"accuracy": <1-5>, "completeness": <1-5>, "safety": <1-5>}}
"""


def main() -> None:
    random.seed(23)
    data = json.loads(
        (ROOT / "experiments/bootstrap/e17_pilot_data.json").read_text(encoding="utf-8")
    )
    answers = json.loads(
        (ROOT / "experiments/bootstrap/e17_pilot_answers.json").read_text(encoding="utf-8")
    )
    by_id = {a["id"]: a for a in answers["answers"]}

    items = []
    for f in data["functions"]:
        code = read_function_code(f["file_path"], f["name"])
        if not code:
            raise SystemExit(f"no source for {f['name']}")
        ans = by_id[f["id"]]
        for mode in f["modes"]:
            items.append({
                "id": f["id"],
                "mode": mode,
                "name": f["name"],
                "question": f["question"],
                "code": code,
                "answer": ans["modes"][mode]["answer"],
            })

    random.shuffle(items)
    mapping = {}
    blocks = []
    for i, it in enumerate(items, 1):
        token = f"T{i:02d}"
        mapping[token] = {"id": it["id"], "mode": it["mode"], "name": it["name"]}
        prompt = JUDGE_PROMPT.format(
            question=it["question"], code=it["code"], answer=it["answer"]
        )
        blocks.append(f"=== BEGIN token={token} ===\n{prompt}\n=== END token={token} ===\n")

    OUT.mkdir(exist_ok=True)
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 1500

    def n_lines(item: str) -> int:
        return item.count("\n") + 1

    shards: list = []
    current: list = []
    for block in blocks:
        if current and sum(n_lines(b) for b in current) + n_lines(block) > budget:
            shards.append(current)
            current = []
        current.append(block)
    if current:
        shards.append(current)

    for k, shard in enumerate(shards, 1):
        (OUT / f"shard_{k}.txt").write_text("\n".join(shard), encoding="utf-8")
        print(f"shard {k}: {len(shard)} items, {sum(n_lines(b) for b in shard)} lines")
    (OUT / "mapping.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"total items: {len(items)} across {len(shards)} shards; mapping.json written")


if __name__ == "__main__":
    main()
