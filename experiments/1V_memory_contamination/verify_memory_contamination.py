#!/usr/bin/env python3
"""
Verify Memory Contamination experiment: (1) truth-table тест логики decide(),
(2) декомпозиция агрегатов из per-fact строк, (3) целостность валидации.

Три независимые оси верификации («как быть уверенными, что тест проведён правильно»):
- Ось A: логика решения соответствует таблице истинности (9 путей) — ловит баги
  типа v1 (CONTRADICT → not truth вместо False).
- Ось B: агрегаты = пересчёт из сырых per-fact строк — ловит ошибки суммирования.
- Ось C: валидация фактов (24/24 valid, 0 invalid, 0 ambiguous).

Запуск: venv/Scripts/python.exe experiments/context_engine/verify_memory_contamination.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import memory_contamination as mc  # noqa: E402

RESULTS_FILES = (
    "memory_contamination_results.json",
    "memory_contamination_results_v2.json",
    "memory_contamination_results_v3_generated.json",
)


def main() -> int:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'}  {name}")

    # ── Ось A: truth-table логики decide() ──
    print("=== A. Truth-table decide() ===")
    fact = {"id": "X", "truth": True, "support_patterns": ["s"], "contra_patterns": ["c"]}
    evidence_by_says = {
        "SUPPORT":   {"s": {"found": True},  "c": {"found": False}},
        "CONTRADICT": {"s": {"found": False}, "c": {"found": True}},
        "SILENT":     {"s": {"found": False}, "c": {"found": False}},
    }
    # (verdict, choice, would_refute)
    expect = {
        "SUPPORT": {
            "B":            (True,  "CODE",   False),
            "A_code_first": (True,  "CODE",   False),
            "A_memory_first": (True, "MEMORY", False),
        },
        "CONTRADICT": {
            "B":            (False, "CODE",   False),
            "A_code_first": (False, "CODE",   True),
            "A_memory_first": (True, "MEMORY", False),
        },
        "SILENT": {
            "B":            (None,  "NONE",   False),
            "A_code_first": (True,  "MEMORY", False),
            "A_memory_first": (True, "MEMORY", False),
        },
    }
    for says, ev in evidence_by_says.items():
        for pol in ("B", "A_code_first", "A_memory_first"):
            policy = "code_first" if pol == "A_code_first" else "memory_first"
            r = mc.decide(fact, ev, has_memory=(pol != "B"), policy=policy)
            exp = expect[says][pol]
            cond = (
                r["verdict"] == exp[0] and r["choice"] == exp[1]
                and r["would_refute"] == exp[2] and r["code_says"] == says
            )
            check(f"{says:<10} {pol:<14} -> v={r['verdict']} ch={r['choice']:<6} ref={r['would_refute']}", cond)

    # ── Оси B+C: декомпозиция агрегатов + валидация ──
    for fname in RESULTS_FILES:
        print(f"=== B+C. {fname} ===")
        res = json.loads((HERE / fname).read_text(encoding="utf-8"))
        per_fact = res["per_fact"]
        agg = res["aggregates"]
        n = len(per_fact)
        n_true = sum(1 for pf in per_fact if pf["truth"])
        n_false = n - n_true

        check("n_valid == len(per_fact)", agg["n_valid"] == n)
        check("validation: 0 invalid", len(res["validation"]["invalid"]) == 0)
        # ambiguous: v1/v2 = 0; v3 = 6 present-trap (FALSE с найденным support — by design,
        # contra перевешивает, вердикт корректен)
        exp_amb = 6 if "v3" in fname else 0
        check(f"validation: ambiguous == {exp_amb}", len(res["validation"]["ambiguous"]) == exp_amb)
        check("n_true == n - n_false", agg["n_true"] == n_true and agg["n_false"] == n_false)

        for pol in ("B", "A_code_first", "A_memory_first"):
            a = agg["arms"][pol]
            correct = sum(1 for pf in per_fact if pf["arms"][pol]["verdict"] == pf["truth"])
            unk = sum(1 for pf in per_fact if pf["arms"][pol]["verdict"] is None)
            adoption = sum(1 for pf in per_fact if not pf["truth"] and pf["arms"][pol]["verdict"] is True)
            contradict = sum(1 for pf in per_fact if not pf["truth"] and pf["arms"][pol]["code_says"] == "CONTRADICT")
            refuted = sum(
                1 for pf in per_fact
                if not pf["truth"] and pf["arms"][pol]["code_says"] == "CONTRADICT"
                and pf["arms"][pol]["would_refute"]
            )
            silent_false = sum(1 for pf in per_fact if not pf["truth"] and pf["arms"][pol]["code_says"] == "SILENT")
            true_false_verdict = sum(1 for pf in per_fact if pf["truth"] and pf["arms"][pol]["verdict"] is False)

            check(f"{pol:<14} correct {correct}/{n} == {a['correct_rate']}",
                  round(correct / n, 3) == a["correct_rate"] if n else a["correct_rate"] is None)
            check(f"{pol:<14} adoption {adoption}/{n_false} == {a['adoption_rate']}",
                  round(adoption / n_false, 3) == a["adoption_rate"] if n_false else a["adoption_rate"] is None)
            check(f"{pol:<14} contra {contradict}/{n_false} == {a['code_contradictability']}",
                  round(contradict / n_false, 3) == a["code_contradictability"] if n_false else a["code_contradictability"] is None)
            check(f"{pol:<14} corr_cap {refuted}/{contradict} == {a['correction_capability']}",
                  (round(refuted / contradict, 3) if contradict else None) == a["correction_capability"])
            check(f"{pol:<14} conf_eff {silent_false} == {a['memory_confidence_effect']}",
                  silent_false == a["memory_confidence_effect"])
            check(f"{pol:<14} unk {unk}/{n} == {a['unknown_rate']}",
                  round(unk / n, 3) == a["unknown_rate"] if n else a["unknown_rate"] is None)
            check(f"{pol:<14} false_conf {true_false_verdict}/{n_true} == {a['false_confirmation_rate']}",
                  round(true_false_verdict / n_true, 3) == a["false_confirmation_rate"] if n_true else a["false_confirmation_rate"] is None)

    print("=" * 60)
    print("ALL PASS" if ok else "SOME FAILED — разобраться")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
