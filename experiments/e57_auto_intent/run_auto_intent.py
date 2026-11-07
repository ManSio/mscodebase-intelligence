"""E57: automatic lexical intent -> docs channel or code quality (no LLM)."""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("MSCODEBASE_DENSE_OFF", "true")
os.environ.setdefault("MSCODEBASE_SQLITE_CHUNKS", "true")
os.environ.setdefault("MSCODEBASE_ONDEMAND_RERANK", "false")
os.environ.setdefault("MSCODEBASE_DEMOTE_NON_CODE", "true")
os.environ.setdefault("MSCODEBASE_P3_ANCHOR", "false")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"D:\Project\MSCodeBase")
FROZEN = ROOT / "experiments" / "e57_auto_intent" / "frozen" / "QUERIES.jsonl"
RESULTS = ROOT / "experiments" / "e57_auto_intent" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)


class FakeIndexer:
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.db_manager = None
        self.table = object()
        self._symbol_index = None


def hit(files, gold, k, basename=False):
    if basename:
        name = Path(gold).name
        return any(Path(f).name == name for f in files[:k])
    return any(f == gold or f.endswith(gold) for f in files[:k])


def score(rows, arm, k, basename=False):
    return sum(hit(r[arm], r["gold"], k, basename) for r in rows) / len(rows)


def main():
    qs = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    from src.core.search.engine import Searcher
    from src.core.search.scoring import auto_detect_intent

    searcher = Searcher(FakeIndexer(ROOT), None)
    searcher._ondemand_rerank = False
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None
    searcher._demote_non_code = True
    searcher._demote_intent_aware = False
    searcher._p3_anchor = False

    rows, lat = [], []
    fp = []
    for q in qs:
        intent = auto_detect_intent(q["query"])
        if intent == "docs" and not q["gold_file"].startswith("docs/"):
            fp.append(q["id"])

        t0 = time.perf_counter()
        code = searcher.search_with_mode(q["query"], mode="quality", limit=5)
        t_code = (time.perf_counter() - t0) * 1000
        code_files = [
            str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
            for r in (code.get("results", []) if isinstance(code, dict) else [])
        ]

        t0 = time.perf_counter()
        docs_files = [
            str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
            for r in searcher.search_docs(q["query"], limit=5)
        ]
        t_docs = (time.perf_counter() - t0) * 1000

        auto_files = docs_files if intent == "docs" else code_files
        oracle_files = docs_files if q["gold_file"].startswith("docs/") else code_files
        rows.append({
            "id": q["id"],
            "gold": q["gold_file"],
            "intent": intent,
            "code_only": code_files,
            "auto": auto_files,
            "oracle": oracle_files,
        })
        lat.append(t_docs if intent == "docs" else t_code)

    out = {"n": len(rows), "false_positive_docs": fp, "p50_ms": statistics.median(lat)}
    for arm in ("code_only", "auto", "oracle"):
        out[arm] = {
            "exact_h1": score(rows, arm, 1),
            "exact_h5": score(rows, arm, 5),
            "base_h1": score(rows, arm, 1, True),
            "base_h5": score(rows, arm, 5, True),
        }
        print(f"{arm:<10} exact {out[arm]['exact_h1']:.3f}/{out[arm]['exact_h5']:.3f} "
              f"base {out[arm]['base_h1']:.3f}/{out[arm]['base_h5']:.3f}")
    print(f"false-positive docs intent: {len(fp)} {fp}")
    print(f"p50={out['p50_ms']:.0f}ms")
    out["rows"] = rows
    (RESULTS / "e57.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
