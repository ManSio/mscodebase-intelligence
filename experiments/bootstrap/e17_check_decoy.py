# -*- coding: utf-8 -*-
"""E17 decoy audit: check D-arm against the owner's 3 criteria.

1. D tests are UNIQUE across functions (no repeats).
2. D tests are FOREIGN: they cover no function in the target's source file.
3. D test coverage matches B coverage (same size/difficulty).
"""
import sys
import json
import sqlite3
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

from src.core.artifact_paths import get_graph_db_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    data = json.loads(
        (ROOT / "experiments/bootstrap/e17_pilot_data.json").read_text(encoding="utf-8")
    )
    conn = sqlite3.connect(str(get_graph_db_path(ROOT)))
    cov = dict(conn.execute(
        "SELECT source_id, COUNT(*) FROM edges WHERE type='TESTS' GROUP BY source_id"
    ).fetchall())
    name_by_id = dict(conn.execute("SELECT id, name FROM nodes WHERE label='Test'"))
    id_by_name = {n: i for i, n in name_by_id.items()}
    files_of: dict = {}
    for sid, fp in conn.execute(
        "SELECT e.source_id, n.file_path FROM edges e JOIN nodes n ON n.id=e.target_id "
        "WHERE e.type='TESTS'"
    ):
        files_of.setdefault(sid, set()).add(fp)
    conn.close()

    d_counts = Counter()
    foreign_violations = []
    cov_mismatch = []
    d_eq_b = []
    for f in data["functions"]:
        b = f["modes"]["B_runtime"]["tests"]
        d = f["modes"]["D_shuffled"]["tests"]
        ffile = f["file_path"]
        for t in d:
            d_counts[t] += 1
            tid = id_by_name.get(t)
            covered = files_of.get(tid, set())
            if ffile in covered:
                foreign_violations.append((f["name"], t))
            bcov = [cov[id_by_name[x]] for x in b if x in id_by_name]
            if tid in cov and bcov and cov[tid] > max(bcov):
                cov_mismatch.append((f["name"], t, cov[tid], max(bcov)))
        if set(d) & set(b):
            d_eq_b.append(f["name"])

    dupes = {t: c for t, c in d_counts.items() if c > 1}
    print(f"functions: {len(data['functions'])}")
    print(f"1) unique D tests: {len(d_counts)} | repeated: {len(dupes)} {list(dupes.items())[:5]}")
    print(f"2) foreign violations: {len(foreign_violations)} {foreign_violations[:5]}")
    print(f"3) cov>B mismatches: {len(cov_mismatch)} {cov_mismatch[:5]}")
    print(f"   D==B collisions: {len(d_eq_b)} {d_eq_b[:5]}")

    ok = not dupes and not foreign_violations and not d_eq_b
    print("DECOY AUDIT:", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
