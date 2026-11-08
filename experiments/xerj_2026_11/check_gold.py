"""Gold self-check: an identifier the codebase does not contain makes a task invalid.

Found 2026-11-08: E1's P03 asks about `ModificationGuard`, which does not exist in
`src/` (the module has functions, not that class). The task was frozen from an
expectation, not from a read — the §19.17 class. The frozen set is not edited
(§17); this script names the invalid rows and recomputes the scores without them,
so both numbers can be published.

Run: python experiments/xerj_2026_11/check_gold.py
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from run_baseline import parse_tasks, TOKEN_RE  # noqa: E402  (same parser as the run)


def _occurrences(token: str, roots: list[Path]) -> int:
    pattern = re.compile(rf"\b{re.escape(token)}\b")
    total = 0
    for base in roots:
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in (".py", ".md", ".toml", ".sh"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            total += len(pattern.findall(text))
            if total:
                return total
    return total


def main() -> int:
    tasks = parse_tasks()
    roots_all = [ROOT / d for d in ("src", "docs", "tests", "scripts", "tools")
                 if (ROOT / d).is_dir()]
    # A symbol "exists" only in code. Writing its name into a document does not
    # create it - but it DOES create a hit for the tool, which is why negatives
    # are checked against every indexed root and positives only against code.
    roots_code = [ROOT / "src"] if (ROOT / "src").is_dir() else roots_all

    invalid = []
    print(f"{'id':<4} {'kind':<10} {'subject':<28} occurrences")
    for task in tasks:
        # Only backticked identifiers can be checked mechanically. A Russian
        # phrase from a question is not a symbol, and flagging it as "absent"
        # says nothing about the task (P06/P07/P15 were false flags until this
        # rule was added).
        gold_col = " ".join(task["gold"])
        names = TOKEN_RE.findall(task["question"]) or TOKEN_RE.findall(gold_col)
        # A NEGATIVE task is only valid while its token occurs NOWHERE. Writing
        # the token into documentation or a probe invalidates the control - it
        # happened twice on 2026-11-08 (`partner_agreement`, then
        # `corpus_hub_signing_key` in the GRACEFUL_DEGRADATION examples), and
        # the tool then "found" the experiment's own text.
        if task["kind"] == "negative":
            tokens = TOKEN_RE.findall(task["question"]) + list(task.get("tokens") or [])
            tokens = list(dict.fromkeys(tokens))
            dirty = {tok: _occurrences(tok, roots_all) for tok in tokens}
            dirty = {k: v for k, v in dirty.items() if v}
            if dirty:
                invalid.append(task["id"])
                print(f"{task['id']:<4} {'negative':<10} {'<token leaked>':<28} {dirty} INVALID")
            else:
                print(f"{task['id']:<4} {'negative':<10} {', '.join(tokens):<28} 0 ok")
            continue
        if not names:
            print(f"{task['id']:<4} {task['kind']:<10} {'<no identifier>':<28} -  skipped")
            continue
        subject = names[0]
        hits = _occurrences(subject, roots_code)
        flag = "INVALID" if (task["kind"] != "negative" and hits == 0) else ""
        if flag:
            invalid.append(task["id"])
        print(f"{task['id']:<4} {task['kind']:<10} {subject:<28} {hits} {flag}")

    print(f"\ninvalid gold rows: {invalid or 'none'}")

    baseline = HERE / "baseline.json"
    if baseline.exists() and invalid:
        rows = json.loads(baseline.read_text(encoding="utf-8"))
        kept = [r for r in rows if r["id"] not in invalid]
        a = sum(r["a_ok"] for r in kept) / len(kept)
        b = sum(bool(r["b_ok"]) for r in kept) / len(kept)
        print(f"recomputed without invalid rows: n={len(kept)} A={a:.3f} B={b:.3f}")
        for kind in ("positive", "ambiguity", "negative"):
            group = [r for r in kept if r["kind"] == kind]
            if not group:
                continue
            av = sum(r["a_ok"] for r in group) / len(group)
            bv = sum(bool(r["b_ok"]) for r in group) / len(group)
            print(f"  {kind:<10} n={len(group):<3} A={av:.3f} B={bv:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
