r"""Quality panel for the ONNX dynamic-padding change (frozen 48-query panel).

Control: dense index built with fixed-512 padding (`g4data_onnx`).
Treatment: dense index built with per-batch padding (`g4data_dyn`).
Same frozen queries, same hybrid `quality` path, same text index; only the
vector table and the query embedding mode differ.

Usage (from the repository root):
    $env:MSCODEBASE_DATA_DIR='...\g4data_onnx'
    $env:MSCODEBASE_DENSE_OFF='false'
    $env:MSCODEBASE_EMBEDDER_PROVIDER='onnx'
    python experiments/onnx_dense_2026_11/quality_panel.py --arm control
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FROZEN = ROOT / "experiments" / "e57_auto_intent" / "frozen" / "QUERIES.jsonl"
OUT = Path(__file__).resolve().parent


class FakeIndexer:
    """Minimal indexer surface Searcher needs for the hybrid path."""

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.db_manager = None
        self.table = object()
        self._symbol_index = None

    async def search_async(self, query_vector, limit: int = 5, filter_expr: str = ""):
        """Vector search against the data root in MSCODEBASE_DATA_DIR."""
        import lancedb

        from src.core.artifact_paths import get_db_path

        db = lancedb.connect(str(get_db_path(self.project_path)))
        table = db.open_table("codebase_chunks")
        builder = table.search(query_vector, vector_column_name="vector")
        df = builder.limit(limit).to_pandas()
        out = []
        for _, row in df.iterrows():
            out.append(
                {
                    "text": row["text"],
                    "text_full": row.get("text_full", row["text"]),
                    "metadata": {
                        "file": row["file_path"],
                        "chunk_index": row["chunk_index"],
                        "indexed_at": row.get("indexed_at", ""),
                        "layer": row.get("layer", ""),
                        "hierarchy_level": row.get("hierarchy_level", ""),
                        "parent_id": row.get("parent_id", ""),
                        "start_line": row.get("start_line", 0),
                        "end_line": row.get("end_line", 0),
                        "symbol_type": row.get("symbol_type", ""),
                        "module_name": row.get("module_name", ""),
                    },
                }
            )
        return out


def _files(rows):
    return [
        str((r.get("metadata") or {}).get("file") or "").replace("\\", "/")
        for r in rows
    ]


def _hit(files, gold: str, k: int) -> bool:
    return any(f == gold or f.endswith(gold) for f in files[:k])


def _mrr(files, gold: str) -> float:
    for rank, f in enumerate(files, 1):
        if f == gold or f.endswith(gold):
            return 1.0 / rank
    return 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", required=True, help="control | treatment label")
    args = parser.parse_args()

    if os.getenv("MSCODEBASE_DENSE_OFF", "true").lower() == "true":
        print("REFUSING: MSCODEBASE_DENSE_OFF=true — no vector table would be used")
        return 2
    if os.getenv("MSCODEBASE_EMBEDDER_PROVIDER", "").lower() != "onnx":
        print("REFUSING: pin MSCODEBASE_EMBEDDER_PROVIDER=onnx")
        return 2

    queries = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    from src.core.search.engine import Searcher
    from src.core.search.scoring import auto_detect_intent
    from src.providers.embedder.remote_embedder import RemoteEmbedder

    embedder = RemoteEmbedder()
    deadline = time.time() + 120
    while time.time() < deadline and not embedder.is_ready():
        time.sleep(2)
    if not embedder.is_ready():
        print(f"REFUSING: embedder not ready (mode={getattr(embedder, 'mode', '?')})")
        return 2
    print(f"embedder: {embedder.provider_name} dim={embedder.embedding_dim}")

    searcher = Searcher(FakeIndexer(ROOT), embedder)
    searcher._ondemand_rerank = False
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None
    searcher._demote_non_code = True
    searcher._demote_intent_aware = False
    searcher._p3_anchor = False

    rows, base_h1, base_h5, mrr, lat = [], [], [], [], []
    for q in queries:
        intent = auto_detect_intent(q["query"])
        t0 = time.perf_counter()
        code = searcher.search_with_mode(q["query"], mode="quality", limit=5)
        t_code = (time.perf_counter() - t0) * 1000
        code_files = _files(code.get("results", []) if isinstance(code, dict) else [])

        t0 = time.perf_counter()
        docs_files = _files(searcher.search_docs(q["query"], limit=5))
        t_docs = (time.perf_counter() - t0) * 1000

        auto_files = docs_files if intent == "docs" else code_files
        gold = q["gold_file"]
        base_h1.append(_hit(auto_files, gold, 1))
        base_h5.append(_hit(auto_files, gold, 5))
        mrr.append(_mrr(auto_files, gold))
        lat.append(t_docs if intent == "docs" else t_code)
        rows.append(
            {
                "id": q["id"],
                "gold": gold,
                "intent": intent,
                "auto": auto_files,
                "h1": base_h1[-1],
                "h5": base_h5[-1],
                "mrr": mrr[-1],
            }
        )

    n = len(queries)
    result = {
        "arm": args.arm,
        "n": n,
        "data_dir": os.getenv("MSCODEBASE_DATA_DIR", ""),
        "hit@1": sum(base_h1) / n,
        "hit@5": sum(base_h5) / n,
        "mrr": sum(mrr) / n,
        "p50_ms": statistics.median(lat),
        "rows": rows,
    }
    print(
        f"{args.arm:<10} n={n} hit@1={result['hit@1']:.3f} "
        f"hit@5={result['hit@5']:.3f} MRR={result['mrr']:.3f} "
        f"p50={result['p50_ms']:.0f}ms"
    )
    (OUT / f"results_{args.arm}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
