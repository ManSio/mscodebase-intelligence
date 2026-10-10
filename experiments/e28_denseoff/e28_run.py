#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E28 dense-off A/B — один и тот же код для обоих плеч.

Различается ТОЛЬКО env MSCODEBASE_DENSE_OFF (плечо задаётся снаружи).
Вход: frozen/queries.jsonl (33 кейса, sha256 — в frozen/MANIFEST.sha256).

USAGE (PowerShell):
  python experiments/e28_denseoff/e28_run.py            # arm=A dense ON
  $env:MSCODEBASE_DENSE_OFF="true"; python experiments/e28_denseoff/e28_run.py  # arm=B
Exit: 0 — оба плеча отработали; 2 — пустой вход (тихий ноль запрещён, §19.6).
"""
import json
import os
import sys
import time
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

FROZEN = ROOT / "experiments/e28_denseoff/frozen/queries.jsonl"


def main() -> int:
    rows = [json.loads(l) for l in FROZEN.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:  # §19.6: метрика на пустой выборке запрещена
        print("EMPTY INPUT — панель пуста, метрика не считается", file=sys.stderr)
        return 2

    searcher = H.build_searcher(ROOT)
    arm = "B(dense_off)" if searcher._dense_off else "A(dense_on)"
    print(f"arm={arm} flag_dense_off={searcher._dense_off} cases={len(rows)}")

    import asyncio

    hits1 = hits5 = errors = 0
    t_all = time.perf_counter()
    per_case = []
    for r in rows:
        t0 = time.perf_counter()
        try:
            res = asyncio.run(searcher.hybrid_search_async(r["query"], limit=10))
            items = res.get("results", []) if isinstance(res, dict) else (res or [])
            files = [str((it.get("metadata") or {}).get("file", "")).replace("\\", "/")
                     for it in items]
        except Exception as e:  # noqa: BLE001 — эксперимент должен считать и падения
            files = []
            errors += 1
            print(f"  ERR {r['id']}: {type(e).__name__}: {e}")
        dt = (time.perf_counter() - t0) * 1000
        gold = r["gold_file"].replace("\\", "/")
        h1 = bool(files[:1] == [gold])
        h5 = gold in files[:5]
        hits1 += h1
        hits5 += h5
        per_case.append({"id": r["id"], "gold": gold, "ms": round(dt, 1),
                         "hit1": h1, "hit5": h5, "top1": files[0] if files else None})
        print(f"  {r['id']:8s} h1={int(h1)} h5={int(h5)} {dt:7.0f}ms {gold} -> {per_case[-1]['top1']}")
    wall = time.perf_counter() - t_all
    n = len(rows)
    summary = {
        "arm": arm, "n": n, "hit1": hits1, "hit5": hits5, "errors": errors,
        "hit1_pct": round(100 * hits1 / n, 1), "hit5_pct": round(100 * hits5 / n, 1),
        "mean_ms": round(sum(c["ms"] for c in per_case) / n, 1),
        "wall_s": round(wall, 1),
    }
    out = ROOT / "experiments/e28_denseoff/results" / f"e28_{arm.split('(')[0]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "cases": per_case}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())