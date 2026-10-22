"""E24 driver: E5-панель БЕЗ health-gate (для плеча 'вектор мёртв').

Переиспользует весь измерительный код scripts/e2e_quality_search.py
(CASES/hit_at/build_searcher/run_mode/report), пропускает только gate
'embedder недоступен — тест бессмысленен' — сам gate и есть объект removal.
Выход: JSON results + тот же stdout-отчёт.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import json
sys.path.insert(0, r"D:\Project\MSCodeBase")
sys.path.insert(0, r"D:\Project\MSCodeBase\scripts")
from pathlib import Path
import e2e_quality_search as H

out = Path(sys.argv[1])
searcher = H.build_searcher(Path(r"D:\Project\MSCodeBase"))
all_rows = {}
for mode in ("fast", "quality"):
    rows = H.run_mode(searcher, mode)
    all_rows[mode] = [
        {"q": q, "exp": exp, "ms": ms, "h1": h1, "h5": h5, "top": top}
        for (q, exp, ms, h1, h5, top) in rows
    ]
    H.report(f"mode={mode} [E24 arm={sys.argv[2]}]", rows)
if not all_rows["fast"] or not all_rows["quality"]:
    print("POPULATION EMPTY — refusing 0%")
    sys.exit(2)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(all_rows, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"OK -> {out}")
