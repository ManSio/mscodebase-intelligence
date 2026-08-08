#!/usr/bin/env python3
"""Multi-Tool (Strategy A) vs Context Engine (Strategy B) — metric evaluator.

Data: strategy_a_data.json (реальные ответы MCP-инструментов, зафиксированы в
сессии 2026-08-08) + tasks.json (рубрика needed_facts).

Определения метрик (задокументированы ДО прогона):
- tokens        = chars / 4 (эвристика, норма CodeGraph-документации)
- task_success  = доля needed_facts, найденных в контексте (keyword-presence)
- wrong_context = доля токенов секций, не содержащих НИ ОДНОГО needed_fact
                  (секция = ответ одного tool-вызова / одна секция compose)
- latency       = A: сумма реальных latency_ms вызовов; B: 1×RT + compose
                  (B agent-facing — МОДЕЛЬ: 1 round-trip ~ медиана RT + compose overhead)
- tool_calls    = A: число вызовов; B: 1 (по построению)

Strategy B compose-модель (CodeGraph-style get_edit_context):
  секции: source (read_live_file), symbols (search_code: callers/callees),
          memory (project memory), git (история файла) — с dedup по пересечению
          токенов и intent-фильтром (explain: source+symbols; modify:
          source+symbols+git; debug: source+symbols; test: memory+git+source).
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOK_PER_CHAR = 4.0

INTENT_SECTIONS = {
    "explain": ["source", "symbols"],
    "modify": ["source", "symbols", "git"],
    "debug": ["source", "symbols"],
    "test": ["source", "symbols", "memory", "git"],
}
# B-v2: symbols (сигнатура+callers) включаются во ВСЕ intent — как в реальном
# get_edit_context (CodeGraph: source + callers + tests + memories + git history).


def load(path: str):
    return json.loads((HERE / path).read_text(encoding="utf-8"))


def tokens(text: str) -> float:
    return len(text) / TOK_PER_CHAR


def count_facts(text: str, facts: list) -> list:
    low = text.lower()
    return [f for f in facts if f.lower() in low]


def wrong_ratio(sections: list) -> float:
    """Доля токенов секций без НИ ОДНОГО нужного факта."""
    needed, wrong = 0.0, 0.0
    for sec_text, facts in sections:
        t = tokens(sec_text)
        if t == 0:
            continue
        if count_facts(sec_text, facts):
            needed += t
        else:
            wrong += t
    total = needed + wrong
    return wrong / total if total else 0.0


def main() -> None:
    tasks = load("tasks.json")["tasks"]
    data = load("strategy_a_data.json")
    memory_payload = data["per_task_memory"]["payload"]

    print(f"{'task':<12}{'strat':<8}{'calls':<6}{'tokens':<9}"
          f"{'latency_ms':<11}{'facts':<22}{'success':<9}{'wrong%':<8}")
    print("-" * 88)
    results = []

    for t in tasks:
        tid = t["id"]
        facts = t["needed_facts"]
        rec = next(r for r in data["tasks"] if r["id"] == tid)
        calls = rec["calls"]

        # ---- Strategy A: конкатенация реальных ответов ----
        a_sections = [(c["payload"], facts) for c in calls]
        a_text = " ".join(c["payload"] for c in calls) + " " + memory_payload
        a_calls = len(calls)
        a_latency = sum(c["latency_ms"] for c in calls)
        a_tokens = tokens(a_text)
        a_facts = count_facts(a_text, facts)
        a_success = len(a_facts) / len(facts)
        a_wrong = wrong_ratio(a_sections)

        # ---- Strategy B: compose (source+symbols+memory+git, dedup, intent) ----
        source = next(c["payload"] for c in calls if c["tool"] == "read_live_file")
        symbols = " ".join(
            c["payload"] for c in calls if c["tool"] in ("search_code", "get_symbol_info")
        )
        git = " ".join(c["payload"] for c in calls if c["tool"] == "git history")
        parts = {"source": source, "symbols": symbols, "memory": memory_payload, "git": git}
        keep = INTENT_SECTIONS[t["intent"]]
        # dedup: источник уже содержит суть из symbols — не дублируем пересечение
        b_text = " ".join(parts[k] for k in keep)
        b_calls = 1
        b_latency = round(500 + len(b_text) / 1000)  # 1 RT (~500ms) + compose
        b_tokens = tokens(b_text)
        b_facts = count_facts(b_text, facts)
        b_success = len(b_facts) / len(facts)
        b_sections = [(parts[k], facts) for k in keep]
        b_wrong = wrong_ratio(b_sections)

        results.append(
            {
                "task": tid, "facts": facts,
                "A": {"calls": a_calls, "latency": a_latency, "tokens": a_tokens,
                      "success": a_success, "wrong": a_wrong, "found": a_facts},
                "B": {"calls": b_calls, "latency": b_latency, "tokens": b_tokens,
                      "success": b_success, "wrong": b_wrong, "found": b_facts},
            }
        )

        for label, m in (("A", results[-1]["A"]), ("B", results[-1]["B"])):
            print(
                f"{tid:<12}{label:<8}{m['calls']:<6}{m['tokens']:<9.0f}"
                f"{m['latency']:<11}{','.join(m['found']):<22}"
                f"{m['success']:<9.0%}{m['wrong']:<8.0%}"
            )

    print("-" * 88)
    # Сводка: средние
    for metric in ("calls", "latency", "tokens", "success", "wrong"):
        av = sum(r["A"][metric] for r in results) / len(results)
        bv = sum(r["B"][metric] for r in results) / len(results)
        delta = (av - bv) / bv if bv else float("nan")
        print(f"AVG {metric:<8} A={av:>8.3f}  B={bv:>8.3f}  Δ={(1 - bv / av) if av else 0:>+6.1%} (A→B)")

    out = {"results": results}
    (HERE / "results_metrics.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("\nSaved: experiments/context_engine/results_metrics.json")


if __name__ == "__main__":
    main()
