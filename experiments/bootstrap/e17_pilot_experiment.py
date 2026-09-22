# -*- coding: utf-8 -*-
"""E17 Pilot Experiment: Does TESTS evidence help an LLM understand code?

Research question:
Does execution-derived test-to-function evidence help an LLM answer repository
questions better than code-only context or an equally-specific but WRONG test
context?

Design (corrected 2026-09-22):
- 3 modes: A (code only), B (specific runtime TESTS), D (coverage-matched decoy).
  Mode C (static) is DROPPED: it was never implemented and returned [] → C ≡ A.
- Panel selected by TEST SPECIFICITY, not by edge count. The original script did
  `ORDER BY test_count DESC`, which picked the *most transitively covered*
  functions (234 edges) where a 3-test sample is pure noise.
  Specificity proxy: a test's coverage = number of functions it executes
  (count of its outgoing TESTS edges). Function score = min coverage of its tests.
- B = the 3 most specific tests of the function (smallest coverage first).
- D = matched decoy: for each B test (coverage c) pick a test from a DIFFERENT
  function with the closest coverage, not belonging to this function.
- Paired design, 1 question per function, judge: 11 trials + real position swap.
"""
import sys
import ast
import json
import sqlite3
import random
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.core.artifact_paths import get_graph_db_path  # noqa: E402
from e17_extract import read_function_code, read_test_code  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

COVERAGE_SQL = """
SELECT source_id, COUNT(*) AS cov FROM edges WHERE type = 'TESTS' GROUP BY source_id
"""

_BRANCH = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.BoolOp, ast.Match)
MIN_BRANCHES = 10


def complexity(code: str) -> Tuple[int, int]:
    """(branch nodes, non-blank lines) — a rough difficulty proxy."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return 0, 0
    loc = sum(1 for ln in code.splitlines() if ln.strip())
    branches = sum(1 for n in ast.walk(tree) if isinstance(n, _BRANCH))
    return branches, loc


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(str(get_graph_db_path(ROOT)))


def collect_candidates(max_cov: int = 5) -> List[Dict]:
    """Functions with at least one test of coverage <= max_cov, in src/."""
    conn = _connect()
    rows = conn.execute(
        f"""
        SELECT f.name, f.file_path, f.qualified_name, COUNT(*) AS n_tests, MIN(tc.cov) AS min_cov
        FROM nodes f
        JOIN edges e ON e.target_id = f.id AND e.type = 'TESTS'
        JOIN ({COVERAGE_SQL}) tc ON tc.source_id = e.source_id
        WHERE f.label = 'Function' AND f.file_path LIKE '%/src/%'
        GROUP BY f.id
        HAVING min_cov <= ?
        ORDER BY min_cov ASC, n_tests ASC
        """,
        (max_cov,),
    ).fetchall()
    conn.close()
    out = []
    for name, file_path, qname, n_tests, min_cov in rows:
        if name == "_" or name.startswith("test_"):
            continue
        out.append({
            "name": name,
            "file_path": file_path,
            "qualified_name": qname,
            "n_tests": n_tests,
            "min_cov": min_cov,
        })
    return out


def select_panel(candidates: List[Dict], n: int = 30, per_file: int = 3) -> List[Dict]:
    """Diversify: at most ``per_file`` functions from the same file."""
    panel: List[Dict] = []
    per_file_count: Dict[str, int] = {}
    for cand in candidates:
        if per_file_count.get(cand["file_path"], 0) >= per_file:
            continue
        panel.append(cand)
        per_file_count[cand["file_path"]] = per_file_count.get(cand["file_path"], 0) + 1
        if len(panel) >= n:
            break
    return panel


def specific_tests(conn: sqlite3.Connection, function_name: str, limit: int = 3) -> List[Tuple[str, int]]:
    """Return (test_name, coverage) for the function's tests, most specific first."""
    rows = conn.execute(
        f"""
        SELECT t.name, tc.cov
        FROM nodes f
        JOIN edges e ON e.target_id = f.id AND e.type = 'TESTS'
        JOIN nodes t ON t.id = e.source_id
        JOIN ({COVERAGE_SQL}) tc ON tc.source_id = e.source_id
        WHERE f.name = ?
        ORDER BY tc.cov ASC, t.name ASC
        """,
        (function_name,),
    ).fetchall()
    return [(name, cov) for name, cov in rows[:limit]]


def build_test_pool(conn: sqlite3.Connection) -> List[Dict]:
    """All test nodes with coverage and the set of source files they cover."""
    cov = dict(conn.execute(
        f"SELECT source_id, COUNT(*) FROM edges WHERE type = 'TESTS' GROUP BY source_id"
    ).fetchall())
    files: Dict[int, set] = {}
    for sid, fp in conn.execute(
        "SELECT e.source_id, n.file_path FROM edges e JOIN nodes n ON n.id = e.target_id "
        "WHERE e.type = 'TESTS'"
    ):
        files.setdefault(sid, set()).add(fp)
    names = dict(conn.execute("SELECT id, name FROM nodes WHERE label = 'Test'"))
    return [
        {"name": name, "cov": cov[tid], "files": files.get(tid, set())}
        for tid, name in names.items()
        if tid in cov
    ]


def matched_decoys(
    panel: List[Dict],
    b_pairs_list: List[List[Tuple[str, int]]],
    pool: List[Dict],
) -> List[List[str]]:
    """Unique, foreign, coverage-matched decoys.

    For each B test (coverage c) pick a test that:
      - is not used by any other function (global uniqueness),
      - covers no function in the target's source file (foreign module),
      - has coverage closest to c (matched difficulty).
    """
    shuffled = pool[:]
    random.shuffle(shuffled)
    used: set = set()
    decoys: List[List[str]] = []
    for func, b_pairs in zip(panel, b_pairs_list):
        ffile = func["file_path"]
        d: List[str] = []
        for _, bcov in b_pairs:
            cands = [
                t for t in shuffled
                if t["name"] not in used and ffile not in t["files"]
            ]
            if not cands:
                break
            cands.sort(key=lambda t: abs(t["cov"] - bcov))
            pick = cands[0]
            d.append(pick["name"])
            used.add(pick["name"])
        decoys.append(d)
    return decoys


_STR_NAMES = {
    "query", "text", "name", "symbol", "content", "code", "s", "uri", "line", "msg",
    "message", "doc", "snippet", "source", "what", "key", "value", "token", "pattern",
}
_PATH_NAMES = {
    "path", "root", "dir", "directory", "db_path", "file", "fp", "filepath", "filename",
}
_INT_NAMES = {
    "n", "limit", "depth", "count", "size", "index", "max_depth", "max_count", "timeout",
    "pid",
}
_EDGE_TOKENS = [
    ("None", "None"),
    ('""', "an empty string"),
    ("''", "an empty string"),
    ("[]", "an empty list"),
    ("{}", "an empty dict"),
    ("-1", "the value -1"),
    ("0", "the value 0"),
]


def signature_edge(code: str) -> Optional[Tuple[str, str, Tuple[str, ...]]]:
    """(description, probe tokens) for the most relevant parameter of the function."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    node = next(
        (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))),
        None,
    )
    if node is None:
        return None
    args = [a for a in node.args.args if a.arg not in ("self", "cls")]
    for p in args:
        ann = ast.unparse(p.annotation) if p.annotation else ""
        nm = p.arg.lower()
        if "Optional" in ann or "None" in ann:
            return ("None", ("None",))
        if "Path" in ann or nm in _PATH_NAMES:
            return ("a path that does not exist", ("path", "missing", "nonexistent", "not_exist"))
        if any(k in ann.lower() for k in ("list", "dict", "iterable", "set", "tuple")):
            return ("an empty collection", ("[]", "{}", "empty"))
        if "int" in ann or nm in _INT_NAMES:
            return ("the value -1", ("-1",))
        if "str" in ann or nm in _STR_NAMES:
            return ("an empty string", ('""', "''", "empty"))
        if "bool" in ann:
            return ("None", ("None",))
    return None


def choose_edge(code: str, b_tests: List[str]) -> Optional[str]:
    """Prefer a signature-appropriate edge input that the B tests exercise."""
    text = "\n".join(read_test_code(t) or "" for t in b_tests)
    sig = signature_edge(code)
    if sig is not None:
        desc, probes = sig
        if any(pr in text for pr in probes):
            return desc
    for token, desc in _EDGE_TOKENS:
        if re.search(r"(?<![\w.])" + re.escape(token) + r"(?![\w])", text):
            return desc
    return sig[0] if sig is not None else None


def generate_question(function_name: str, file_path: str, edge_desc: Optional[str]) -> str:
    """Impact/coverage: which tests exercise this function (the signal's own answer)."""
    return (
        f"A developer is about to change the behavior of the function `{function_name}` in "
        f"`{Path(file_path).name}`. Which existing tests in this repository must be run to catch "
        "regressions, i.e. which tests exercise this function? List the test function names "
        "explicitly (one per line). If you cannot determine this from the information given, "
        "say so explicitly."
    )


def prepare_experiment_data(n_functions: int = 30, max_cov: int = 5) -> Dict:
    print(f"Collecting candidates with min test coverage <= {max_cov}...")
    candidates = collect_candidates(max_cov)
    print(f"  candidates: {len(candidates)}")

    for c in candidates:
        code = read_function_code(c["file_path"], c["name"]) or ""
        c["branches"], c["loc"] = complexity(code)
    hard = [c for c in candidates if c["branches"] >= MIN_BRANCHES]
    hard.sort(key=lambda c: (-c["branches"], -c["loc"]))
    print(f"  hard candidates (branches >= {MIN_BRANCHES}): {len(hard)}")

    panel = select_panel(hard, n_functions)
    print(f"  panel: {len(panel)} functions across "
          f"{len({p['file_path'] for p in panel})} files")

    conn = _connect()
    all_tests: List[Tuple[str, int]] = conn.execute(
        f"""
        SELECT t.name, tc.cov
        FROM nodes t
        JOIN ({COVERAGE_SQL}) tc ON tc.source_id = t.id
        WHERE t.label = 'Test'
        """
    ).fetchall()
    print(f"  total test nodes with coverage: {len(all_tests)}")

    b_pairs_list = [specific_tests(conn, func["name"], limit=3) for func in panel]
    b_sets = [[name for name, _ in pairs] for pairs in b_pairs_list]
    pool = build_test_pool(conn)
    d_sets = matched_decoys(panel, b_pairs_list, pool)

    functions = []
    for i, func in enumerate(panel, 1):
        b_tests = b_sets[i - 1]
        d_tests = d_sets[i - 1]
        code = read_function_code(func["file_path"], func["name"]) or ""
        functions.append({
            "id": i,
            "name": func["name"],
            "file_path": func["file_path"],
            "n_tests": func["n_tests"],
            "min_cov": func["min_cov"],
            "question": generate_question(
                func["name"], func["file_path"], choose_edge(code, b_tests)
            ),
            "modes": {
                "A_baseline": {"tests": [], "description": "Code only (no tests)"},
                "B_runtime": {"tests": b_tests, "description": "Most specific runtime TESTS"},
                "D_shuffled": {"tests": d_tests, "description": "Coverage-matched decoy"},
            },
        })
        print(f"[{i}/{len(panel)}] {func['name']} (branches={func.get('branches')}, "
              f"loc={func.get('loc')}, min_cov={func['min_cov']}) B={b_tests} D={d_tests}")

    conn.close()
    return {
        "functions": functions,
        "metadata": {
            "n_functions": len(functions),
            "n_total_tests": len(all_tests),
            "selection": f"min_test_coverage<={max_cov}, max 3 per file",
            "modes": ["A_baseline", "B_runtime", "D_shuffled"],
        },
    }


def main():
    print("=" * 80)
    print("E17 PILOT EXPERIMENT (specificity-selected)")
    print("=" * 80)
    random.seed(17)
    data = prepare_experiment_data(n_functions=30, max_cov=5)

    output_path = Path(__file__).parent / "e17_pilot_data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("=" * 80)
    print(f"Experiment data saved to: {output_path}")
    print(f"Total functions: {data['metadata']['n_functions']}")
    print(f"Total tests in graph: {data['metadata']['n_total_tests']}")
    print("=" * 80)


if __name__ == "__main__":
    main()
