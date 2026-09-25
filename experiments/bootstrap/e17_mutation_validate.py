# -*- coding: utf-8 -*-
"""E17 mutation validation: does the TESTS signal identify *verifying* tests?

Hypothesis: for a function F with a strong behaviour mutation, the tests the
graph links to F (arm B) FAIL (kill the mutant), while coverage-matched decoy
tests (arm D) PASS. If so, the TESTS edges can drive verification, not just
description.

Method: mutate the first single-line `if` condition inside F (negate it), run
the exact pytest node ids for arm B and arm D, then restore the file with
`git checkout --` in a finally block. No LLM.
"""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
BOOT = ROOT / "experiments/bootstrap"
K = int(sys.argv[1]) if len(sys.argv) > 1 else 10


def _sh(cmd, timeout=300):
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def graph_test_files():
    """test name -> absolute file path from the PropertyGraph."""
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


def mutate(src, qualname):
    """Strong mutation: negate the first single-line `if` condition. Else None."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None, None
    node = find_func(tree, qualname)
    if node is None:
        return None, None
    lines = src.split("\n")
    for sub in ast.walk(node):
        if isinstance(sub, ast.If) and sub.test.lineno == sub.test.end_lineno:
            ln = lines[sub.test.lineno - 1]
            seg = ln[sub.test.col_offset:sub.test.end_col_offset]
            if seg.strip():
                lines[sub.test.lineno - 1] = (
                    ln[:sub.test.col_offset] + f"not ({seg})" + ln[sub.test.end_col_offset:]
                )
                return "\n".join(lines), f"negate-if @L{sub.test.lineno}"
    return None, None


def run_tests(ids):
    if not ids:
        return None
    p = _sh([sys.executable, "-m", "pytest", *ids, "-q", "--no-header",
             "-p", "no:cacheprovider"])
    m = re.search(r"(\d+) failed", p.stdout)
    return {"failed": int(m.group(1)) if m else 0, "rc": p.returncode}


def main():
    data = json.loads((BOOT / "e17_pilot_data.json").read_text(encoding="utf-8"))
    tfiles = graph_test_files()
    results = []
    for f in data["functions"]:
        if len(results) >= K:
            break
        rel = f["file_path"].replace("D:/Project/MSCodeBase/", "")
        src_path = ROOT / rel
        if not src_path.exists():
            continue
        mutated, desc = mutate(src_path.read_text(encoding="utf-8"), f["name"])
        if not mutated:
            continue

        def _rel(t):
            return Path(tfiles[t]).resolve().relative_to(ROOT).as_posix()

        b_ids = [node_id(_rel(t), t) for t in f["modes"]["B_runtime"]["tests"] if t in tfiles]
        d_ids = [node_id(_rel(t), t) for t in f["modes"]["D_shuffled"]["tests"] if t in tfiles]
        if not b_ids or not d_ids:
            continue
        print(f"\n[{f['name']}] mutation {desc}")
        try:
            src_path.write_text(mutated, encoding="utf-8")
            b, d = run_tests(b_ids), run_tests(d_ids)
        finally:
            _sh(["git", "checkout", "--", rel])
        results.append({"name": f["name"], "mutation": desc, "B": b, "D": d})
        print(f"  B: failed={b['failed']} rc={b['rc']}")
        print(f"  D: failed={d['failed']} rc={d['rc']}")

    (BOOT / "e17_mutation_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(results)
    b_kill = sum(1 for r in results if r["B"] and r["B"]["rc"] != 0)
    d_kill = sum(1 for r in results if r["D"] and r["D"]["rc"] != 0)
    print("\n" + "=" * 60)
    print(f"functions tested: {n}")
    print(f"B (graph tests) killed the mutant: {b_kill}/{n}")
    print(f"D (decoy tests) killed the mutant: {d_kill}/{n}")
    print("=" * 60)


if __name__ == "__main__":
    main()
