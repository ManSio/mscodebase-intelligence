# -*- coding: utf-8 -*-
"""E17 verification-strength profiling.

For each panel function: generate several behaviour mutations (negate-if,
flip-compare, bool-flip, int+1, str-append), run the graph-linked tests (arm B)
and the decoy tests (arm D) under each mutation, and record which tests fail.
Then relate each test's kill-rate to cheap AST features (assert count, density,
comparison specificity) to see what actually predicts detection.

No LLM. Files restored via `git checkout --` in a finally block.
"""
import ast
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
BOOT = ROOT / "experiments/bootstrap"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BOOT))
K_FUNCS = int(sys.argv[1]) if len(sys.argv) > 1 else 10
MAX_MUT = int(sys.argv[2]) if len(sys.argv) > 2 else 4

_OPS = {ast.Eq: ("==", "!="), ast.NotEq: ("!=", "=="), ast.Lt: ("<", ">"),
        ast.Gt: (">", "<"), ast.LtE: ("<=", ">="), ast.GtE: (">=", "<=")}


def _sh(cmd, timeout=300):
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def graph_test_files():
    import sqlite3
    from src.core.artifact_paths import get_graph_db_path
    conn = sqlite3.connect(str(get_graph_db_path(ROOT)))
    rows = conn.execute("SELECT name, file_path FROM nodes WHERE label='Test'").fetchall()
    conn.close()
    out = {}
    for name, fp in rows:
        out.setdefault(name, fp)
    return out


def node_id(rel_file, test_name):
    cls, _, meth = test_name.partition("::")
    return f"{rel_file}::{cls}::{meth}" if meth else f"{rel_file}::{test_name}"


def find_func(tree, qualname):
    parts = qualname.split(".")
    if len(parts) == 1:
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == parts[0]:
                return n
        return None
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == parts[-2]:
            for item in n.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == parts[-1]:
                    return item
    return None


def mutations(src, qualname, limit):
    """Yield up to `limit` distinct (mutated_src, description)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    node = find_func(tree, qualname)
    if node is None:
        return []
    lines = src.split("\n")
    out = []

    def add(ln_no, col, end_col, text, desc):
        nl = list(lines)
        nl[ln_no - 1] = lines[ln_no - 1][:col] + text + lines[ln_no - 1][end_col:]
        joined = "\n".join(nl)
        try:
            ast.parse(joined)
        except SyntaxError:
            return
        out.append((joined, desc))

    for sub in ast.walk(node):
        if len(out) >= limit:
            break
        if isinstance(sub, ast.If) and sub.test.lineno == sub.test.end_lineno:
            ln = lines[sub.test.lineno - 1]
            seg = ln[sub.test.col_offset:sub.test.end_col_offset]
            if seg.strip():
                add(sub.test.lineno, sub.test.col_offset, sub.test.end_col_offset,
                    f"not ({seg})", f"negate-if@L{sub.test.lineno}")
        elif isinstance(sub, ast.Compare) and len(sub.ops) == 1:
            left, comp = sub.left, sub.comparators[0]
            if left.lineno == left.end_lineno == comp.lineno:
                ln = lines[left.lineno - 1]
                span = ln[left.end_col_offset:comp.col_offset]
                pair = _OPS.get(type(sub.ops[0]))
                if pair and span.strip() == pair[0]:
                    add(left.lineno, left.end_col_offset, comp.col_offset,
                        f" {pair[1]} ", f"flip-cmp@{pair[0]}->{pair[1]}@L{left.lineno}")
        elif isinstance(sub, ast.Constant) and sub.lineno == sub.end_lineno:
            ln = lines[sub.lineno - 1]
            seg = ln[sub.col_offset:sub.end_col_offset]
            if isinstance(sub.value, bool) and seg in ("True", "False"):
                add(sub.lineno, sub.col_offset, sub.end_col_offset,
                    "False" if sub.value else "True", f"bool-flip@L{sub.lineno}")
            elif isinstance(sub.value, int) and seg == str(sub.value):
                add(sub.lineno, sub.col_offset, sub.end_col_offset,
                    str(sub.value + 1), f"int+1@{sub.value}->{sub.value + 1}@L{sub.lineno}")
            elif isinstance(sub.value, str) and len(sub.value) > 1 and seg[:1] in ("'", '"'):
                add(sub.lineno, sub.col_offset, sub.end_col_offset,
                    f'"{sub.value}X"', f"str-append@L{sub.lineno}")
    return out[:limit]


def run_verbose(ids):
    """Return {nodeid: status} for a pytest -v run."""
    if not ids:
        return {}
    p = _sh([sys.executable, "-m", "pytest", *ids, "-v", "--no-header",
             "-p", "no:cacheprovider"])
    status = {}
    for m in re.finditer(r"(\S+::\S+)\s+(PASSED|FAILED|ERROR)", p.stdout):
        status[m.group(1)] = m.group(2)
    return status


def test_features(body):
    """Cheap AST features of a test function body."""
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return None
    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    lines = len([ln for ln in body.splitlines() if ln.strip()])
    exact = 0
    for a in asserts:
        t = a.test
        if isinstance(t, ast.Compare) and any(isinstance(o, (ast.Eq, ast.NotEq)) for o in t.ops):
            exact += 1
    return {
        "asserts": len(asserts),
        "loc": lines,
        "density": round(len(asserts) / lines, 3) if lines else 0.0,
        "exact_compare": exact,
    }


def main():
    import importlib
    sys.path.insert(0, str(BOOT))
    ext = importlib.import_module("e17_extract")

    data = json.loads((BOOT / "e17_pilot_data.json").read_text(encoding="utf-8"))
    tfiles = graph_test_files()

    # (function_id, test_name) -> {killed, total}
    kill = defaultdict(lambda: {"killed": 0, "total": 0})
    d_kill = 0
    d_total = 0
    tested_funcs = 0

    for f in data["functions"]:
        if tested_funcs >= K_FUNCS:
            break
        rel = f["file_path"].replace("D:/Project/MSCodeBase/", "")
        src_path = ROOT / rel
        if not src_path.exists():
            continue
        muts = mutations(src_path.read_text(encoding="utf-8"), f["name"], MAX_MUT)
        if not muts:
            continue

        def _rel(t):
            return Path(tfiles[t]).resolve().relative_to(ROOT).as_posix()

        b_tests = [t for t in f["modes"]["B_runtime"]["tests"] if t in tfiles]
        d_tests = [t for t in f["modes"]["D_shuffled"]["tests"] if t in tfiles]
        b_ids = [(t, node_id(_rel(t), t)) for t in b_tests]
        d_ids = [(t, node_id(_rel(t), t)) for t in d_tests]
        tested_funcs += 1
        print(f"\n[{f['name']}] {len(muts)} mutations")
        try:
            for new_src, desc in muts:
                src_path.write_text(new_src, encoding="utf-8")
                st = run_verbose([nid for _, nid in b_ids])
                for name, nid in b_ids:
                    kill[(f["id"], name)]["total"] += 1
                    if st.get(nid) in ("FAILED", "ERROR"):
                        kill[(f["id"], name)]["killed"] += 1
                dst = run_verbose([nid for _, nid in d_ids])
                for name, nid in d_ids:
                    d_total += 1
                    if dst.get(nid) in ("FAILED", "ERROR"):
                        d_kill += 1
                print(f"  {desc}: {sum(1 for _, nid in b_ids if st.get(nid) in ('FAILED','ERROR'))} B-tests killed")
        finally:
            _sh(["git", "checkout", "--", rel])

    rows = []
    for (fid, name), v in kill.items():
        body = ext.read_test_code(name) or ""
        feats = test_features(body) or {}
        rows.append({"function_id": fid, "test": name,
                     "kill_rate": round(v["killed"] / v["total"], 3) if v["total"] else 0.0,
                     **feats})
    (BOOT / "e17_strength_profile.json").write_text(
        json.dumps({"tests": rows, "decoy": {"killed": d_kill, "total": d_total}},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    n = len(rows)
    full = sum(1 for r in rows if r["kill_rate"] >= 1.0)
    zero = sum(1 for r in rows if r["kill_rate"] == 0.0)
    print(f"tests profiled: {n} across {tested_funcs} functions")
    print(f"kill_rate = 1.0: {full}   kill_rate = 0.0: {zero}")
    print(f"decoy tests killed: {d_kill}/{d_total}")
    try:
        from scipy import stats
        for feat in ("asserts", "density", "exact_compare", "loc"):
            xs = [r[feat] for r in rows if feat in r]
            ys = [r["kill_rate"] for r in rows if feat in r]
            if len(set(xs)) > 1:
                rho, p = stats.spearmanr(xs, ys)
                print(f"  spearman(kill_rate, {feat:13}) rho={rho:+.2f} p={p:.3f}")
    except Exception as e:
        print("  (scipy unavailable:", e, ")")
    print("=" * 72)
    for r in rows:
        print(f"  kill={r['kill_rate']:.2f} asserts={r.get('asserts')} dens={r.get('density')} "
              f"exact={r.get('exact_compare')} {r['test']}")


if __name__ == "__main__":
    main()
