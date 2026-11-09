"""Mechanical overlap check between queries and the gold file.

Purpose: decide, BEFORE any search is run, which cases are "lexically
unreachable" (query shares no content token with the gold file) and whether a
query leaks a symbol name from the gold file. This is a property of the inputs,
not of the results, so the population cannot be selected post hoc.

Run: python experiments/xerj_2026_11/ru_vs_dense/overlap_check.py
"""

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
FROZEN = HERE / "frozen"

REPOS = {
    "itsdangerous": Path(
        r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11"
        r"\pallets__itsdangerous__HEAD-672971d"
    ),
    "iniconfig": Path(
        r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11"
        r"\pytest-dev__iniconfig__HEAD-a9e0ad1"
    ),
}

STOP = {
    "the", "and", "from", "for", "with", "into", "that", "this", "where",
    "what", "why", "how", "does", "the", "a", "an", "of", "to", "in", "on",
    "is", "are", "all", "without", "lines", "line",
}

WORD = re.compile(r"[a-z0-9]{3,}")


def tokens(text: str) -> set[str]:
    return {word for word in WORD.findall(text.lower()) if word not in STOP}


def symbols(text: str) -> set[str]:
    names = re.findall(r"^\s*(?:async\s+)?def\s+(\w+)", text, re.M)
    names += re.findall(r"^\s*class\s+(\w+)", text, re.M)
    return {name.lower() for name in names}


def main() -> int:
    questions = json.loads((FROZEN / "questions.json").read_text(encoding="utf-8"))
    queries = json.loads((FROZEN / "queries.json").read_text(encoding="utf-8"))["queries"]

    out = {"cases": {}, "summary": {}}
    hard_turn1 = hard_all = leaks = 0
    for case in questions["cases"]:
        case_id = case["id"]
        gold_path = REPOS[case["repo"]] / "src" / case["repo"] / case["gold"]
        text = gold_path.read_text(encoding="utf-8")
        gold_tokens = tokens(text) | tokens(case["gold"])
        gold_symbols = symbols(text)
        ru = queries[case_id]["ru"]
        en = queries[case_id]["en"]
        ru_overlap = [sorted(tokens(q) & gold_tokens) for q in ru]
        en_overlap = [sorted(tokens(q) & gold_tokens) for q in en]
        symbol_hits = sorted({t for q in en + ru for t in tokens(q) if t in gold_symbols})
        if not en_overlap[0]:
            hard_turn1 += 1
        if not any(en_overlap):
            hard_all += 1
        if symbol_hits:
            leaks += 1
        out["cases"][case_id] = {
            "gold": case["gold"],
            "ru_overlap": ru_overlap,
            "en_overlap": en_overlap,
            "symbol_hits": symbol_hits,
            "hard_turn1": not en_overlap[0],
            "hard_all_turns": not any(en_overlap),
        }
        print(
            f"{case_id} gold={case['gold']:<13} "
            f"en_overlap={[len(o) for o in en_overlap]} "
            f"ru_overlap={[len(o) for o in ru_overlap]} "
            f"symbols={symbol_hits or '-'}"
        )

    total = len(questions["cases"])
    out["summary"] = {
        "cases": total,
        "hard_turn1": hard_turn1,
        "hard_all_turns": hard_all,
        "cases_with_symbol_leak": leaks,
    }
    target = FROZEN / "overlap.json"
    rendered = json.dumps(out, ensure_ascii=False, indent=2) + "\n"
    if "--write" in sys.argv:
        target.write_text(rendered, encoding="utf-8", newline="")
    elif target.exists() and target.read_text(encoding="utf-8") != rendered:
        print("FROZEN OVERLAP DIFFERS: rerun with --write and bump the manifest")
        return 2

    print(
        f"\ncases={total} hard_turn1={hard_turn1} hard_all_turns={hard_all} "
        f"symbol_leaks={leaks} -> frozen/overlap.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
