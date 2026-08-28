"""E4 — PoC: deterministic per-class router (no LLM) vs single-arm baselines.

Reuses the E3 harness (same real index, same scoring). Router classifies the
prompt with keyword rules into a klass, then picks an arm:
  fast   : find_bug_cause, git_history, prepare_change   (E3: fast wins)
  quality: find_caller_callee, understand_architecture   (E3: quality wins)
  union  : find_test, find_impact, modify_function, verify_change
           (search-only arms all 0.00 in E3 -> try fast+quality union;
            true graph stage needs in-memory SymbolIndex, unavailable cold)

Metrics: klass-prediction accuracy vs GT klass, recall@5, facts coverage,
latency. Compare vs E3 baselines: fast 0.167 / quality 0.133 / cascade 0.233.
"""
import asyncio
import json
import statistics
import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "experiments" / "mech_orch"))

from E3_category_router_eval import (  # noqa: E402
    build_stack, run_one, gt_hit, fact_covered, snippets_of, LIMIT, TOP_K,
    TASKS_FILE, OUT_FILE,
)

OUT_ROUTER = PROJECT_ROOT / "experiments" / "mech_orch" / "results_E4_router.json"

# ─── deterministic klass rules (keyword sets, checked in order) ─────────────
RULES = [
    ("git_history", ["история", " git", "commit", "кто изменял", "когда", "недавно", "кто и когда"]),
    ("find_caller_callee", ["кто вызывает", "вызывае", "caller", "callee", "кого вызывает", "куда ведёт", "вызовы"]),
    ("understand_architecture", ["архитектур", "слои", "как устроен", "объясни", "связ", "структур", "модул", "опиши", "оркестрация"]),
    ("find_test", ["тест", "tests", "тестов"]),
    ("find_impact", ["влия", "impact", "затронут", "слома", "затрагива"]),
    ("verify_change", ["проверь", "верифициру", "безопасн", "пройдут", "подтверд", "риск"]),
    ("modify_function", ["измен", "модифицир", "перепиши", "рефактор", "добавь", "напиши", "реализуй", "исправь", "дополни"]),
    ("prepare_change", ["план", "подготов", "какие файлы", "оцени", "что менять", "приблизительно"]),
    # fallback
    ("find_bug_cause", ["почему", "причин", "баг", "ошибк", "падает", "не работает", "неверн", "пусто", "подозр", "de facto"]),
]

ARM_BY_KLASS = {
    "find_bug_cause": "fast",
    "git_history": "fast",
    "prepare_change": "fast",
    "find_caller_callee": "quality",
    "understand_architecture": "quality",
    "find_test": "union",
    "find_impact": "union",
    "modify_function": "union",
    "verify_change": "union",
}


def classify(prompt: str) -> str:
    p = (prompt or "").lower()
    for klass, kws in RULES:
        for kw in kws:
            if kw in p:
                return klass
    return "find_bug_cause"


def merge_files(res_a, res_b, topk=TOP_K):
    out = []
    for r in (res_a + res_b):
        meta = r.get("metadata") or {}
        f = str(meta.get("file") or r.get("file") or "unknown")
        if f not in out:
            out.append(f)
    return out[:topk]


async def main():
    tasks = json.loads(TASKS_FILE.read_text(encoding="utf-8"))["tasks"]
    print(f"[*] router PoC: tasks={len(tasks)} topk={TOP_K} limit={LIMIT}")
    searcher, db_path = build_stack()

    rows = []
    klass_hits = 0
    for t in tasks:
        prompt = t.get("prompt") or ""
        gt_klass = t.get("klass", "?")
        pred_klass = classify(prompt)
        if pred_klass == gt_klass:
            klass_hits += 1
        arm = ARM_BY_KLASS.get(pred_klass, "fast")

        fast = await run_one(searcher, t, "fast")
        if arm == "quality":
            chosen = await run_one(searcher, t, "quality")
        elif arm == "union":
            quality = await run_one(searcher, t, "quality")
            chosen = {
                "files": merge_files(fast.get("results", []), quality.get("results", [])),
                "latency_ms": fast.get("latency_ms", 0) + quality.get("latency_ms", 0),
                "mode": "union",
                "results": fast.get("results", []) + quality.get("results", []),
            }
        else:
            chosen = fast

        hit = gt_hit(chosen.get("files", []), t.get("file", ""))
        fcov, nf = fact_covered(t.get("required_facts", []), snippets_of(chosen.get("results", [])))
        rows.append({
            "id": t["id"], "gt_klass": gt_klass, "pred_klass": pred_klass,
            "arm": arm, "hit": hit, "latency_ms": chosen.get("latency_ms", 0),
            "facts": fcov, "facts_n": nf, "files": chosen.get("files", [])[:3],
        })
        print(f"{t['id']:4} {gt_klass:18}->{pred_klass:18} {arm:8} {'H' if hit else '-':1} "
              f"{chosen.get('latency_ms', 0):7.0f}ms")

    n = len(rows)
    recall = sum(r["hit"] for r in rows) / n
    fcov_all = [r["facts"] / max(r["facts_n"], 1) for r in rows if r["facts_n"]]
    lat = [r["latency_ms"] for r in rows]
    by_klass = {}
    for r in rows:
        b = by_klass.setdefault(r["gt_klass"], {"n": 0, "hits": 0, "lat": []})
        b["n"] += 1
        b["hits"] += int(r["hit"])
        b["lat"].append(r["latency_ms"])
    for k, b in by_klass.items():
        b["recall"] = round(b["hits"] / b["n"], 3)

    report = {
        "klass_accuracy": round(klass_hits / n, 3),
        "recall_k": round(recall, 3),
        "facts_coverage_mean": round(statistics.mean(fcov_all), 3) if fcov_all else None,
        "latency_median_ms": round(statistics.median(lat), 1),
        "latency_p95_ms": round(sorted(lat)[int(n * 0.95) - 1], 1) if n > 1 else None,
        "by_klass": by_klass,
        "rows": [{k: v for k, v in r.items()} for r in rows],
    }
    OUT_ROUTER.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== ROUTER vs E3 BASELINES ===")
    print(f"router    : recall={report['recall_k']} facts_cov={report['facts_coverage_mean']} "
          f"lat_med={report['latency_median_ms']}ms p95={report['latency_p95_ms']}ms "
          f"klass_acc={report['klass_accuracy']}")
    print("E3 fast   : recall=0.167 facts=0.517 lat_med=148ms p95=167ms")
    print("E3 quality: recall=0.133 facts=0.861 lat_med=2145ms p95=6803ms")
    print("E3 cascade: recall=0.233 facts=0.753 lat_med=564ms p95=6909ms")
    print("\n=== BY KLASS ===")
    for k, b in by_klass.items():
        print(f"{k:18}: n={b['n']:2} recall={b['recall']:.2f}")
    print(f"\n[*] saved: {OUT_ROUTER}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)