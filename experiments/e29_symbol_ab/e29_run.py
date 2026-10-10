#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EXP-29 — тот же измеритель, что E28, плюс разрез по subset (symbolic / NL).

Различается только env MSCODEBASE_DENSE_OFF. Вход: frozen/queries_labeled.jsonl
(sha7639ba1b — в frozen/MANIFEST.sha256). Exit 2 на пустом входе (§19.6).
"""
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import e2e_quality_search as H  # noqa: E402

FROZEN = ROOT / "experiments/e29_symbol_ab/frozen/queries_labeled.jsonl"
# Проект с ИНДЕКСОМ может отличаться от дерева с кодом: индекс per-project-path,
# в worktree его нет → все запросы вернули бы 0 результатов (тихий ноль, §19.6).
PROJ = Path(os.getenv("E29_PROJECT_ROOT") or ROOT)


def main() -> int:
    rows = [json.loads(l) for l in FROZEN.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        print("EMPTY INPUT — метрика не считается", file=sys.stderr)
        return 2

    searcher = H.build_searcher(PROJ)
    arm = "B" if searcher._dense_off else "A"
    print(f"arm={arm} dense_off={searcher._dense_off} project={PROJ} rows={len(rows)}")
    import asyncio

    per_sub = defaultdict(lambda: {"n": 0, "hit1": 0, "hit5": 0})
    cases = []
    errors = 0
    for r in rows:
        t0 = time.perf_counter()
        try:
            res = asyncio.run(searcher.hybrid_search_async(r["query"], limit=10))
            items = res if isinstance(res, list) else res.get("results", [])
            files = [str((it.get("metadata") or {}).get("file", "")).replace("\\", "/")
                     for it in items]
        except Exception as e:  # noqa: BLE001
            files = []
            errors += 1
            print(f"  ERR {r['id']}: {type(e).__name__}: {e}")
        gold = r["gold_file"].replace("\\", "/")
        h1 = files[:1] == [gold]
        h5 = gold in files[:5]
        s = per_sub[r["subset"]]
        s["n"] += 1
        s["hit1"] += int(h1)
        s["hit5"] += int(h5)
        cases.append({"id": r["id"], "subset": r["subset"], "gold": gold,
                      "ms": round((time.perf_counter() - t0) * 1000, 1),
                      "hit1": h1, "hit5": h5, "top1": files[0] if files else None})

    n = len(rows)
    empty = sum(1 for c in cases if not c["top1"])
    if empty == len(cases):
        # §19.6: пустой вход/пустой индекс обязан падать громко, а не отдавать «0%».
        print(f"ABORT: все {len(cases)} запросов вернули 0 результатов — "
              f"индекс недоступен (корень проекта: {ROOT}). Метрика не считается.",
              file=sys.stderr)
        return 2
    summary = {"arm": arm, "dense_off": searcher._dense_off, "n": n, "errors": errors,
               "empty_top1": empty,
               "mean_ms": round(sum(c["ms"] for c in cases) / n, 1),
               "subsets": {k: {"n": v["n"], "hit1": v["hit1"], "hit5": v["hit5"],
                               "hit1_pct": round(100 * v["hit1"] / v["n"], 1)}
                           for k, v in sorted(per_sub.items())}}
    out = ROOT / "experiments/e29_symbol_ab/results" / f"e29_{arm}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "cases": cases}, ensure_ascii=False, indent=1),
                   encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())