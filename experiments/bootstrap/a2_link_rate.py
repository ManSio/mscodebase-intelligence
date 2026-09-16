# -*- coding: utf-8 -*-
"""A2: link-rate замер — сколько из trace_result.json (1727 тестов / 1212 функций)
реально матчатся на узлы PropertyGraph. Read-only (find_nodes + qname-вывод), без записи."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.core.artifact_paths import get_project_dir, get_graph_db_path
from src.core.graph import PropertyGraph

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path.cwd()
PROJECT = ROOT
SRC = PROJECT / "src"

trace = json.load(open(ROOT / "experiments/bootstrap/trace_result.json", encoding="utf-8"))
pg = PropertyGraph(get_graph_db_path(PROJECT))

project_name = None  # определим по первому найденному узлу


def test_qname(nodeid: str) -> str:
    """tests/foo.py::test_bar -> f'{project}.{abs_path}.test_bar' (имя до [)."""
    path_part, _, name_part = nodeid.partition("::")
    name = name_part.split("[")[0]
    abs_path = (ROOT / path_part.replace("\\", "/")).resolve().as_posix()
    return f"unknown.{abs_path}.{name}", abs_path, name


def func_match(entry: str):
    """func@relpath -> (суффикс-имя, abs_path)."""
    fn, _, rel = entry.rpartition("@")
    rel_posix = rel.replace("\\", "/")
    abs_path = (SRC / rel_posix).resolve().as_posix()
    return fn, abs_path


test_hits = 0
test_miss = []
func_hits = 0
func_miss_samples = []

# 1) тестовые узлы: ищем по file_path + точному имени
for nodeid in trace:
    _, abs_path, name = test_qname(nodeid)
    nodes = pg.find_nodes(name_pattern=f"{name}", file_path=abs_path, limit=2)
    # более строго: точное равенство имени (find_nodes LIKE может зацепить префиксы)
    exact = [n for n in nodes if n.name == name]
    if exact:
        test_hits += 1
        if project_name is None:
            project_name = exact[0].qualified_name.split(".")[0]
    else:
        test_miss.append(nodeid)

# 2) src функции: суффикс-матч (Class.method в графе) + file_path равенство
multi = 0
for funcs in trace.values():
    for entry in funcs:
        fn, abs_path = func_match(entry)
        if not abs_path or not fn:
            func_miss_samples.append(entry)
            continue
        nodes = pg.find_nodes(name_pattern=f"%.{fn}", file_path=abs_path, limit=8)
        nodes = [n for n in nodes if n.name == fn or n.name.endswith(f".{fn}")]
        if nodes:
            func_hits += 1
            if len(nodes) > 1:
                multi += 1
        else:
            func_miss_samples.append(entry)

print(f"PROJECT_ROOT: {PROJECT}")
print(f"project_name sample: {project_name!r} (из qname тестового узла)")
print()
print(f"tests in trace: {len(trace)}")
print(f"  found as nodes: {test_hits} ({test_hits/len(trace)*100:.1f}%)")
print(f"  missing: {len(test_miss)}")
for m in test_miss[:5]:
    print(f"    {m}")
print()
all_funcs = sum(len(v) for v in trace.values())
print(f"src func entries in trace: {all_funcs} (unique {len({f for v in trace.values() for f in v})})")
print(f"  found as nodes: {func_hits} ({func_hits/all_funcs*100:.1f}% of entries)")
print(f"  multi-match entries: {multi}")
print(f"  missing: {len(func_miss_samples)}")
for m in func_miss_samples[:8]:
    print(f"    {m}")