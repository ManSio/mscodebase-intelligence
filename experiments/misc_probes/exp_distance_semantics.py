# -*- coding: utf-8 -*-
"""Эксперимент: семантика _distance в lancedb 0.34.0 при cosine-метрике.

Гипотеза (Recalled): для cosine _distance = 1 - cos_sim, меньше = ближе,
сортировка ASC. Комментарий engine.py:166 «чем больше, тем ближе» неверен.

Проверка: temp-таблица, IVF_FLAT metric=cosine, query = [1,0,0,0].
Ожидаем (если гипотеза верна): сам вектор _distance≈0, похожий [0.9,0.1,0,0]
_distance мал, далёкие [0,1,0,0] и [0,0,0,1] _distance ≥ 1, порядок ASC.
"""
import sys
import tempfile
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import lancedb  # noqa: E402

print(f"lancedb version: {lancedb.__version__}", flush=True)

tmp = Path(tempfile.mkdtemp(prefix="lancedb_exp_"))
try:
    db = lancedb.connect(str(tmp / "exp.db"))
    rows = [
        {"id": "q_self", "vector": [1.0, 0.0, 0.0, 0.0]},
        {"id": "near", "vector": [0.9, 0.1, 0.0, 0.0]},
        {"id": "orth", "vector": [0.0, 1.0, 0.0, 0.0]},
        {"id": "far", "vector": [0.0, 0.0, 0.0, 1.0]},
    ]
    tbl = db.create_table("t", data=rows)
    # Тот же путь, что в index_project_runner.py:537-542 (legacy-форма)
    tbl.create_index(
        metric="cosine", vector_column_name="vector",
        index_type="IVF_FLAT", replace=True,
    )

    print("\n=== search([1,0,0,0]) c cosine-индексом ===", flush=True)
    df = tbl.search([1.0, 0.0, 0.0, 0.0]).limit(4).to_pandas()
    for _, r in df.iterrows():
        print(f"  id={r['id']:<8} _distance={r['_distance']:.6f}", flush=True)

    print("\n=== search([1,0,0,0]) c default (l2) ===", flush=True)
    df2 = tbl.search([1.0, 0.0, 0.0, 0.0]).distance_type("l2").limit(4).to_pandas()
    for _, r in df2.iterrows():
        print(f"  id={r['id']:<8} _distance={r['_distance']:.6f}", flush=True)
finally:
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)
