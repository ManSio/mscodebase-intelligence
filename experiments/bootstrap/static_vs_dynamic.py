# -*- coding: utf-8 -*-
"""Exp 9 (v2): Static Score Engine против ground truth trace_result.json.

v2: исправление методики L1 — извлечение вызовов ТОЛЬКО из тела текущей
функции теста (per-test granularity), а не из всего файла (v1 завышала hit
вызовами соседних тестов того же файла).

Владельческая 3-уровневая схема (Шаг B, статический компаньон):
  L1 AST Direct Call Mining  — прямые вызовы из тела тестовой функции
  L2 Lexical & Semantic Token Alignment — токены имени теста vs co_name
  L3 Module & Import Proximity — func-кандидаты из импортированных src-модулей

Ground truth: experiments/bootstrap/trace_result.json (1727 тестов).
Метрики на тест: hit (S∩G≠∅), recall |S∩G|/|G|, precision |S∩G|/|S|.
Имя-матч (Exp 7, 0%) мерял ДРУГОЙ сигнал (имя теста=имя функции);
здесь L1 — имена ПРЯМЫХ ВЫЗОВОВ в теле теста → co_name src-функции.
"""
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "experiments" / "bootstrap" / "trace_result.json"
SRC = ROOT / "src"

trace = json.loads(TRACE.read_text(encoding="utf-8"))
tests = [(k, set(v)) for k, v in trace.items()]

src_funcs: dict[str, set[str]] = defaultdict(set)
module_funcs: dict[str, set[str]] = defaultdict(set)
for funcs in trace.values():
    for f in funcs:
        name, _, mod = f.rpartition("@")
        mod = mod.replace("\\", "/").removeprefix("src/")
        src_funcs[name].add(f)
        module_funcs[mod].add(f)

IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|\s*import\s+([\w.]+))", re.M)


def imports_of(test_file: Path) -> list[str]:
    try:
        text = test_file.read_text(encoding="utf-8")
    except Exception:
        return []
    mods = set()
    for m in IMPORT_RE.finditer(text):
        mod = m.group(1) or m.group(2)
        if mod.startswith("src"):
            mods.add(mod[4:].replace(".", "/") + ".py")
        elif mod.startswith("core"):
            mods.add(mod.replace(".", "/") + ".py")
    return sorted(mods)


def calls_in_function(node: ast.FunctionDef) -> set[str]:
    """Имена прямых вызовов (Name.id / Attribute.attr) внутри одной функции."""
    names = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            fn = n.func
            if isinstance(fn, ast.Name):
                names.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                names.add(fn.attr)
    return names


def func_call_names(test_file: Path, test_name: str) -> set[str]:
    """Вызовы из тела именно этой тестовой функции (per-test)."""
    try:
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
    except Exception:
        return set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == test_name:
            return calls_in_function(node)
    return set()


def tokens_of(nodeid: str) -> set[str]:
    name = nodeid.rsplit("::", 1)[-1]
    return set(re.split(r"[_\W]+", name)) - {"", "test"}


def main() -> None:
    stats = {}
    for k in ("L1", "L2", "L3", "union"):
        stats[k] = defaultdict(float)
    n_empty_g = 0
    empty_g_static = 0

    for nodeid, ground in tests:
        test_file = ROOT / nodeid.split("::")[0]
        test_name = nodeid.rsplit("::", 1)[-1]
        if not ground:
            n_empty_g += 1

        cands: dict[str, set[str]] = {}
        calls = func_call_names(test_file, test_name)
        cands["L1"] = {f for c in calls for f in src_funcs.get(c, ())}
        toks = tokens_of(nodeid)
        cands["L2"] = {f for t in toks for f in src_funcs.get(t, ())}
        cands["L3"] = {f for m in imports_of(test_file) for f in module_funcs.get(m, ())}
        cands["union"] = cands["L1"] | cands["L2"] | cands["L3"]

        for k, S in cands.items():
            if not S:
                stats[k]["none"] += 1
                continue
            inter = len(S & ground)
            if inter:
                stats[k]["hit"] += 1
                stats[k]["recall"] += inter / max(1, len(ground))
                stats[k]["precision"] += inter / len(S)
            else:
                stats[k]["miss"] += 1
            stats[k]["S"] += len(S)

        if not ground and cands["union"]:
            empty_g_static += 1

    print("=" * 78)
    print(f"Exp 9 v2 | Static Score Engine (per-test) vs trace | tests={len(tests)} | empty-G={n_empty_g}")
    print("=" * 78)
    print(f"{'level':<8}{'hit%':>7}{'recall%':>9}{'precision%':>11}{'miss':>6}{'noneS':>7}{'avg|S|':>9}")
    for k in ("L1", "L2", "L3", "union"):
        s = stats[k]
        ev = s["hit"] + s["miss"]
        hit = 100.0 * s["hit"] / max(1, ev)
        rec = 100.0 * s["recall"] / max(1, ev)
        prec = 100.0 * s["precision"] / max(1, ev)
        avg_s = s["S"] / max(1, ev)
        print(f"{k:<8}{hit:>6.1f}%{rec:>8.1f}%{prec:>10.1f}%{s['miss']:>6}{s['none']:>7}{avg_s:>8.1f}")

    print(f"\nstatic кандидаты для динамически-пустых тестов: {empty_g_static}/{n_empty_g}")
    g_sizes = [len(g) for _, g in tests if g]
    print(f"|G| per linked test: min={min(g_sizes)} avg={sum(g_sizes)/len(g_sizes):.1f} max={max(g_sizes)}")
    print(f"unique src funcs in trace: {len({f for _, g in tests for f in g})}")


if __name__ == "__main__":
    main()