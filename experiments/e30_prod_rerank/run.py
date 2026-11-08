"""E30: production-like on-demand rerank benchmark on real project queries.

Measures end-to-end `Searcher.hybrid_search_async` (SQLite FTS5 + BM25 +
graph + on-demand rerank) over 48 real queries from MSCodeBase:
33 frozen E28 queries + 15 fresh docstring-derived queries.

Model servers (started outside this script):
  :8080  embeddinggemma-2 Q8_0 (768d)
  :8084  multilingual-e5-small Q8_0 (384d)
  :8085  embeddinggemma-2 UD-Q4_K_XL (768d)

No vectors are stored: each run embeds query + top-N candidates live.
"""

from __future__ import annotations

import asyncio
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("MSCODEBASE_DENSE_OFF", "true")
os.environ.setdefault("MSCODEBASE_SQLITE_CHUNKS", "true")
os.environ.setdefault("MSCODEBASE_ONDEMAND_RERANK", "true")

import httpx  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
FROZEN = Path(__file__).resolve().parent / "frozen" / "QUERIES.jsonl"
RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)


class FakeIndexer:
    def __init__(self, project_path: Path, symbol_index=None):
        self.project_path = project_path
        self.db_manager = None
        self.table = object()  # force full pipeline, no SQLite short-circuit
        self._symbol_index = symbol_index


class HttpEmbedder:
    """llama.cpp embedding client with token-trim (same idea as RemoteEmbedder)."""

    def __init__(self, url: str, dim: int):
        self.url = url.rstrip("/")
        self.dim = dim
        self._client = httpx.Client(base_url=self.url, timeout=180.0)

    def _prep(self, text: str, target: int = 400) -> str:
        if len(text) <= 256:
            return text
        try:
            r = self._client.post(
                "/tokenize", json={"content": text, "add_special": False}
            )
            n = len(r.json()["tokens"])
        except Exception:
            return text[:1600]
        t = text
        for _ in range(6):
            if n <= target:
                return t
            t = t[: max(1, int(len(t) * (target / max(n, 1)) * 0.95))]
            try:
                n = len(
                    self._client.post(
                        "/tokenize", json={"content": t, "add_special": False}
                    ).json()["tokens"]
                )
            except Exception:
                return t[:1600]
        return t

    def embed_batch(self, texts, is_query: bool = False):
        prepped = [self._prep(str(t)) for t in texts]
        r = self._client.post("/v1/embeddings", json={"input": prepped})
        r.raise_for_status()
        vecs = [d["embedding"] for d in r.json()["data"]]
        if self.dim and self.dim < len(vecs[0]):
            out = []
            for v in vecs:
                v = v[: self.dim]
                n = sum(x * x for x in v) ** 0.5 or 1.0
                out.append([x / n for x in v])
            return out
        return vecs

    async def embed_batch_async(self, texts, is_query: bool = False):
        return self.embed_batch(texts, is_query)


CONFIGS = [
    # name, url, dim, top_n, max_chars, rerank
    ("e5_384_top10", "http://127.0.0.1:8084", 384, 10, 0, True),
    ("q8_768_top10", "http://127.0.0.1:8080", 768, 10, 0, True),
    ("q8_768_top20", "http://127.0.0.1:8080", 768, 20, 0, True),
    ("q8_256_top10", "http://127.0.0.1:8080", 256, 10, 0, True),
    ("q8_768_top10_cap800", "http://127.0.0.1:8080", 768, 10, 800, True),
    ("q4_768_top10", "http://127.0.0.1:8085", 768, 10, 0, True),
    ("q4_768_top20", "http://127.0.0.1:8085", 768, 20, 0, True),
    ("q4_256_top10", "http://127.0.0.1:8085", 256, 10, 0, True),
    ("no_rerank", None, 0, 0, 0, False),
]


def hit_at(files, gold, k):
    for f in files[:k]:
        if f == gold or f.endswith(gold):
            return 1
    return 0


def mrr_at(files, gold):
    for i, f in enumerate(files, 1):
        if f == gold or f.endswith(gold):
            return 1.0 / i
    return 0.0


async def run_config(name, url, dim, top_n, max_chars, rerank, queries, symbol_index, suffix=""):
    from src.core.search.engine import Searcher

    indexer = FakeIndexer(ROOT, symbol_index=symbol_index)
    embedder = HttpEmbedder(url, dim) if url else None
    searcher = Searcher(indexer, embedder)
    searcher._ondemand_rerank = bool(rerank)
    searcher._ondemand_rerank_top_n = int(top_n or 10)
    searcher._ondemand_rerank_max_chars = int(max_chars or 0)
    if not rerank:
        # Clean retrieval-only control: do not fall into BGE multi-reranker.
        searcher._multi_reranker_initialized = True
        searcher._multi_reranker = None

    # Warm-up (loads the model, fills caches; not counted).
    try:
        await searcher.hybrid_search_async(queries[0]["query"], limit=5)
    except Exception as e:
        print(f"[warn] warmup {name}: {e}")

    rows = []
    for q in queries:
        t0 = time.perf_counter()
        try:
            res = await searcher.hybrid_search_async(q["query"], limit=5)
            ms = (time.perf_counter() - t0) * 1000
            files = [(r.get("metadata") or {}).get("file", "") for r in res]
            rows.append(
                {
                    "id": q["id"],
                    "query": q["query"],
                    "gold": q["gold_file"],
                    "files": files,
                    "ms": ms,
                    "h1": hit_at(files, q["gold_file"], 1),
                    "h5": hit_at(files, q["gold_file"], 5),
                    "rr": mrr_at(files, q["gold_file"]),
                    "error": None,
                }
            )
        except Exception as e:
            rows.append(
                {
                    "id": q["id"],
                    "query": q["query"],
                    "gold": q["gold_file"],
                    "files": [],
                    "ms": (time.perf_counter() - t0) * 1000,
                    "h1": 0,
                    "h5": 0,
                    "rr": 0.0,
                    "error": str(e)[:240],
                }
            )

    await searcher.close()
    lat = sorted(r["ms"] for r in rows)
    summary = {
        "config": name,
        "n": len(rows),
        "hit1": sum(r["h1"] for r in rows) / len(rows),
        "hit5": sum(r["h5"] for r in rows) / len(rows),
        "mrr": sum(r["rr"] for r in rows) / len(rows),
        "p50_ms": statistics.median(lat),
        "p95_ms": lat[int(len(lat) * 0.95) - 1],
        "mean_ms": sum(lat) / len(lat),
        "errors": sum(1 for r in rows if r["error"]),
        "rows": rows,
    }
    (RESULTS / f"{name}{suffix}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"{name:<22} h1={summary['hit1']:.3f} h5={summary['hit5']:.3f} "
        f"mrr={summary['mrr']:.3f} p50={summary['p50_ms']:.0f}ms "
        f"p95={summary['p95_ms']:.0f}ms err={summary['errors']}"
    )
    return summary


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="comma-separated config names")
    parser.add_argument("--suffix", default="", help="suffix for result files")
    args = parser.parse_args()

    queries = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not queries:
        print("FATAL: empty query set", file=sys.stderr)
        return 2

    # Real PropertyGraph for the graph stage (production-like).
    symbol_index = None
    try:
        from src.core.artifact_paths import get_graph_db_path
        from src.core.graph import PropertyGraph
        from src.core.search.graph_adapter import SymbolIndexAdapter

        pg = PropertyGraph(get_graph_db_path(ROOT))
        symbol_index = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    except Exception as e:
        print(f"[warn] graph unavailable: {e}")

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    for cfg in CONFIGS:
        if only and cfg[0] not in only:
            continue
        await run_config(
            *cfg,
            queries=queries,
            symbol_index=symbol_index,
            suffix=args.suffix,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

