# -*- coding: utf-8 -*-
"""B1: верификатор детектора сущностей против живого графа.

Прогон: `python experiments/bootstrap/b1_entities_smoke.py`.
Ожидание: расхождение детектор-vs-граф == ровно bootstrap-классы
(EntityShape/EntitiesBootstrapStats/TestsBootstrapStats), потерь 0.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path("D:/Project/MSCodeBase").resolve()

con = sqlite3.connect(
    Path.home() / "AppData/Local/mscodebase/projects/bfe9644b/graph.db"
)
rows = con.execute(
    """SELECT DISTINCT t.name FROM edges e
       JOIN nodes s ON e.source_id=s.id
       JOIN nodes t ON e.target_id=t.id
       WHERE s.qualified_name LIKE '%.__decorator__.dataclass'
         AND t.qualified_name LIKE '%MSCodeBase/src/%'"""
).fetchall()
graph_entities = set(name for (name,) in rows)

from src.core.bootstrap_entities import detect_entities  # noqa: E402

stats = detect_entities(PROJECT_ROOT)
det_entities = {e.name for e in stats.entities if e.kind == "dataclass"}

print(f"graph dataclass: {len(graph_entities)}")
print(f"detector dataclass: {stats.dataclass_count}")
print(f"open_table calls (non-entities): {stats.open_table_calls}")
print(f"in detector, not in graph: {sorted(det_entities - graph_entities)}")
print(f"in graph, not in detector: {sorted(graph_entities - det_entities)}")

missing = graph_entities - det_entities
print("PASS" if not missing else f"FAIL: losses={sorted(missing)}")