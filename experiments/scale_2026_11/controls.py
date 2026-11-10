"""Red-team controls for the E66 panel.

Three questions, all adversarial:

1. **Triviality** — would `grep "def <name>"` score the same? If yes, the panel
   measures grep, not search, and the number must not be sold as quality.
2. **Correctness of the misses** — for every top-1 miss, is the gold really a
   definition, and what did the tool return instead?
3. **Selection bias** — how many symbols did the generator drop, and why? A
   panel built only from distinctive, unique names is easier than the corpus.

Run: python experiments/scale_2026_11/controls.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

TASKS = HERE / "tasks.jsonl"
RESULTS = HERE / "results.json"


def _tasks() -> list[dict]:
    return [json.loads(x) for x in TASKS.read_text(encoding="utf-8").splitlines() if x.strip()]


def _py_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8")
    return sorted(x for x in out.stdout.splitlines() if x.strip())


def _symbol(question: str) -> str:
    match = re.search(r"`([^`]+)`", question)
    return match.group(1).split(".")[-1] if match else ""


def main() -> int:
    tasks = _tasks()
    files = _py_files()
    cache: dict[str, str] = {}

    def text_of(path: str) -> str:
        if path not in cache:
            try:
                cache[path] = (ROOT / path).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                cache[path] = ""
        return cache[path]

    print("== 1. grep control (definition lines, path order) ==")
    rows = []
    for task in tasks:
        if task["kind"] != "positive":
            continue
        name = _symbol(task["question"])
        pattern = re.compile(
            rf"^\s*(async\s+def|def|class)\s+{re.escape(name)}\b", re.M
        )
        hits = [path for path in files if pattern.search(text_of(path))]
        gold = task["gold"][0]
        top1 = bool(hits) and hits[0].endswith(gold)
        any8 = any(h.endswith(gold) for h in hits[:8])
        rows.append({"bucket": task["bucket"], "top1": top1, "any": any8})

    for bucket in ("name", "qualified"):
        subset = [r for r in rows if r["bucket"] == bucket]
        if subset:
            print(f"  grep {bucket:<10} top1={sum(r['top1'] for r in subset)}/{len(subset)} "
                  f"any={sum(r['any'] for r in subset)}/{len(subset)}")

    result_data = json.loads(RESULTS.read_text(encoding="utf-8"))
    summary = result_data["summary"]
    for bucket in ("name", "qualified"):
        cell = summary.get(bucket)
        if cell:
            print(f"  tool {bucket:<10} top1={cell['top1']}/{cell['n']} "
                  f"any={cell['any']}/{cell['n']}")

    print("\n== 2. the misses, one by one ==")
    # Per-task rows are not stored; re-derive the list from the run log if present.
    log = Path(r"C:\Users\misha\AppData\Local\Temp\opencode\scale_run2.log")
    misses = []
    if log.is_file():
        for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = re.search(r"^\s+\d+/\d+ (name|qualified).*top1=False", line)
            if match:
                misses.append(line.strip())
    print(f"  misses found in the run log: {len(misses)}")
    for line in misses[:10]:
        print("   ", line[:120])

    print("\n== 3. what the generator dropped ==")
    from generate import _definitions, SKIP_FILES, NAME_RE, QUALIFIED_RE  # noqa: E402

    defs = _definitions()
    unique = {s: r for s, r in defs.items() if len(r) == 1}
    code = {s: r for s, r in unique.items()
            if not any(part in r[0][0] for part in SKIP_FILES)}
    names = [s for s in code if NAME_RE.match(s)]
    qualified = [s for s in code if QUALIFIED_RE.match(s)]
    print(f"  graph definitions: {len(defs)} symbols, {len(unique)} with one definition")
    print(f"  after code-only filter: {len(code)}")
    print(f"  matching `name` regex: {len(names)} (panel uses 160)")
    print(f"  matching `qualified` regex: {len(qualified)} (panel uses 40)")
    print(f"  dropped by regex (short/dunder/generic names): "
          f"{len(code) - len(set(names) | set(qualified))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
