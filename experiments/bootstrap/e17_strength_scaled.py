# -*- coding: utf-8 -*-
"""E17 verification-strength — scaled run with held-out validation.

Selects its own panel (N functions with a specific test, min coverage <= 5),
generates M mutations per function, runs every graph-linked test (arm B) and
coverage-matched decoy test (arm D) under every mutant, and records which tests
fail. Then splits by FUNCTION (no leakage) and checks whether a cheap AST proxy
computed at index time predicts a test's mutation kill-rate on held-out data.

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

import e17_pilot_experiment as ex  # noqa: E402
from e17_extract import read_function_code, read_test_code  # noqa: E402

N_FUNCS = int(sys.argv[1]) if len(sys.argv) > 1 else 45
MAX_MUT = int(sys.argv[2]) if len(sys.argv) > 2 else 6
STRONG = 0.5

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
                span = lines[left.lineno - 1][left.end_col_offset:comp.col_offset]
                pair = _OPS.get(type(sub.ops[0]))
                if pair and span.strip() == pair[0]:
                    add(left.lineno, left.end_col_offset, comp.col_offset,
                        f" {pair[1]} ", f"flip-cmp@{pair[0]}->{pair[1]}@L{left.lineno}")
        elif isinstance(sub, ast.Constant) and sub.lineno == sub.end_lineno:
            seg = lines[sub.lineno - 1][sub.col_offset:sub.end_col_offset]
            if isinstance(sub.value, bool) and seg in ("True", "False"):
                add(sub.lineno, sub.col_offset, sub.end_col_offset,
                    "False" if sub.value else "True", f"bool-flip@L{sub.lineno}")
            elif isinstance(sub.value, int) and seg == str(sub.value):
                add(sub.lineno, sub.col_offset, sub.end_col_offset,
                    str(sub.value + 1), f"int+1@{sub.value}->{sub.value + 1}@L{sub.lineno}")
    return out[:limit]


def run_verbose(ids):
    if not ids:
        return {}
    try:
        p = _sh([sys.executable, "-m", "pytest", *ids, "-v", "--no-header",
                 "-p", "no:cacheprovider"], timeout=45)
    except subprocess.TimeoutExpired:
        return {nid: "TIMEOUT" for nid in ids}
    return {m.group(1): m.group(2)
            for m in re.finditer(r"(\S+::\S+)\s+(PASSED|FAILED|ERROR)", p.stdout)}


def features(body):
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return {}
    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    loc = len([ln for ln in body.splitlines() if ln.strip()])
    exact = sum(1 for a in asserts if isinstance(a.test, ast.Compare)
                and any(isinstance(o, (ast.Eq, ast.NotEq)) for o in a.test.ops))
    return {"asserts": len(asserts), "loc": loc,
            "density": round(len(asserts) / loc, 3) if loc else 0.0,
            "exact_compare": exact}


def main():
    conn = ex._connect()
    cands = ex.collect_candidates(max_cov=5)
    # Skip providers/mcp: their tests spawn/await servers and can hang under mutation.
    cands = [c for c in cands
             if "/providers/" not in c["file_path"] and "/mcp/" not in c["file_path"]]
    panel = ex.select_panel(cands, N_FUNCS, per_file=3)
    b_pairs = [ex.specific_tests(conn, f["name"], 3) for f in panel]
    pool = ex.build_test_pool(conn)
    d_sets = ex.matched_decoys(panel, b_pairs, pool)
    conn.close()
    print(f"panel: {len(panel)} functions")

    tfiles = graph_test_files()
    kill = defaultdict(lambda: {"killed": 0, "total": 0})
    d_kill = d_total = 0
    profiled = 0

    for fid, (f, b_pairs_i, d_tests) in enumerate(zip(panel, b_pairs, d_sets), 1):
        rel = f["file_path"].replace("D:/Project/MSCodeBase/", "")
        src_path = ROOT / rel
        if not src_path.exists():
            continue
        muts = mutations(src_path.read_text(encoding="utf-8"), f["name"], MAX_MUT)
        b_tests = [t for t, _ in b_pairs_i if t in tfiles]
        d_tests = [t for t in d_tests if t in tfiles]
        if not muts or not b_tests:
            continue

        def _rel(t):
            return Path(tfiles[t]).resolve().relative_to(ROOT).as_posix()

        b_ids = [(t, node_id(_rel(t), t)) for t in b_tests]
        d_ids = [(t, node_id(_rel(t), t)) for t in d_tests]
        profiled += 1
        print(f"[{profiled}] {f['name']}: {len(muts)} muts, {len(b_tests)} B, {len(d_tests)} D",
              flush=True)
        try:
            for idx, (new_src, _desc) in enumerate(muts):
                src_path.write_text(new_src, encoding="utf-8")
                st = run_verbose([nid for _, nid in b_ids])
                for name, nid in b_ids:
                    kill[(fid, name)]["total"] += 1
                    if st.get(nid) in ("FAILED", "ERROR"):
                        kill[(fid, name)]["killed"] += 1
                if idx == 0:
                    dst = run_verbose([nid for _, nid in d_ids])
                    for _name, nid in d_ids:
                        d_total += 1
                        if dst.get(nid) in ("FAILED", "ERROR"):
                            d_kill += 1
        finally:
            _sh(["git", "checkout", "--", rel])

    import random
    rows = []
    for (fid, name), v in kill.items():
        feats = features(read_test_code(name) or "")
        rows.append({"function_id": fid, "test": name,
                     "kill_rate": round(v["killed"] / v["total"], 3) if v["total"] else 0.0,
                     **feats})

    funcs = sorted({r["function_id"] for r in rows})
    random.seed(41)
    random.shuffle(funcs)
    train_f = set(funcs[: len(funcs) // 2])
    train = [r for r in rows if r["function_id"] in train_f]
    test = [r for r in rows if r["function_id"] not in train_f]

    def rho(rs, feat):
        from scipy import stats
        xs = [r[feat] for r in rs if feat in r]
        ys = [r["kill_rate"] for r in rs if feat in r]
        if len(set(xs)) < 2:
            return float("nan"), float("nan")
        return stats.spearmanr(xs, ys)

    print("\n" + "=" * 72)
    print(f"profiled functions: {profiled} | tests: {len(rows)} | decoys killed: {d_kill}/{d_total}")
    for label, rs in (("train", train), ("test (held-out)", test)):
        for feat in ("exact_compare", "asserts", "density", "loc"):
            r, p = rho(rs, feat)
            print(f"  [{label:14}] spearman(kill_rate, {feat:13}) rho={r:+.2f} p={p:.3f}")

    tp = fp = fn = tn = 0
    for r in test:
        pred = r.get("exact_compare", 0) >= 1
        act = r["kill_rate"] >= STRONG
        tp += pred and act
        fp += pred and not act
        fn += (not pred) and act
        tn += (not pred) and not act
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    print(f"\nheld-out rule (exact_compare>=1 -> strong, kill_rate>={STRONG}):")
    print(f"  TP={tp} FP={fp} FN={fn} TN={tn}  precision={prec:.2f} recall={rec:.2f}")

    (BOOT / "e17_strength_scaled.json").write_text(
        json.dumps({"tests": rows, "decoy": {"killed": d_kill, "total": d_total},
                    "train_rho": {f: rho(train, f)[0] for f in ("exact_compare", "asserts")},
                    "test_rho": {f: rho(test, f)[0] for f in ("exact_compare", "asserts")},
                    "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn}},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 72)


if __name__ == "__main__":
    try:
        main()
    finally:
        subprocess.run(["git", "checkout", "--", "src/"], cwd=str(ROOT))
