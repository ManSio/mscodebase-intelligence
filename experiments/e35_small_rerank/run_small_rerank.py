"""E35: small ONNX cross-encoder rerank (ms-marco-MiniLM-L-6-v2 int8)."""

from __future__ import annotations

import asyncio
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

import numpy as np  # noqa: E402
import onnxruntime as ort  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
FROZEN = Path(__file__).resolve().parent / "frozen" / "QUERIES.jsonl"
RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)
MODEL_DIR = Path(
    r"C:\Users\misha\AppData\Local\Temp\opencode\models\ms-marco-minilm-l6-v2"
)


class FakeIndexer:
    def __init__(self, project_path: Path, symbol_index=None):
        self.project_path = project_path
        self.db_manager = None
        self.table = object()
        self._symbol_index = symbol_index


class MiniLMReranker:
    def __init__(self, model_dir: Path):
        self.sess = ort.InferenceSession(
            str(model_dir / "onnx_model_quantized.onnx"),
            providers=["CPUExecutionProvider"],
        )
        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tok.enable_truncation(max_length=512)
        self.tok.enable_padding(pad_id=0, pad_token="[PAD]")

    def score(self, query: str, texts):
        encs = self.tok.encode_batch([(query, str(t)[:2000]) for t in texts])
        ids = np.asarray([e.ids for e in encs], dtype=np.int64)
        mask = np.asarray([e.attention_mask for e in encs], dtype=np.int64)
        types = np.asarray([e.type_ids for e in encs], dtype=np.int64)
        out = self.sess.run(
            None,
            {"input_ids": ids, "attention_mask": mask, "token_type_ids": types},
        )[0]
        return [float(x) for x in out.reshape(-1)]


def hit_at(files, gold, k):
    return int(any(f == gold or f.endswith(gold) for f in files[:k]))


def mrr_at(files, gold):
    for i, f in enumerate(files, 1):
        if f == gold or f.endswith(gold):
            return 1.0 / i
    return 0.0


async def run_arm(name, pool_size, reranker, queries, symbol_index):
    from src.core.search.engine import Searcher

    searcher = Searcher(FakeIndexer(ROOT, symbol_index=symbol_index), None)
    searcher._ondemand_rerank = False
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None
    searcher._demote_non_code = True

    async def one(q):
        t0 = time.perf_counter()
        res = await searcher.hybrid_search_async(q["query"], limit=pool_size)
        if reranker is not None and res:
            texts = [r.get("text_full") or r.get("text") or "" for r in res]
            try:
                scores = reranker.score(q["query"], texts)
                order = sorted(range(len(res)), key=lambda i: scores[i], reverse=True)
                res = [res[i] for i in order]
            except Exception as e:
                return {
                    "id": q["id"],
                    "query": q["query"],
                    "gold": q["gold_file"],
                    "files": [],
                    "ms": (time.perf_counter() - t0) * 1000,
                    "h1": 0,
                    "h5": 0,
                    "rr": 0.0,
                    "error": f"rerank: {e}"[:240],
                }
        res = res[:5]
        files = [(r.get("metadata") or {}).get("file", "") for r in res]
        return {
            "id": q["id"],
            "query": q["query"],
            "gold": q["gold_file"],
            "files": files,
            "ms": (time.perf_counter() - t0) * 1000,
            "h1": hit_at(files, q["gold_file"], 1),
            "h5": hit_at(files, q["gold_file"], 5),
            "rr": mrr_at(files, q["gold_file"]),
            "error": None,
        }

    await one(queries[0])
    rows = [await one(q) for q in queries]
    await searcher.close()

    lat = sorted(r["ms"] for r in rows)
    summary = {
        "arm": name,
        "pool": pool_size,
        "n": len(rows),
        "hit1": sum(r["h1"] for r in rows) / len(rows),
        "hit5": sum(r["h5"] for r in rows) / len(rows),
        "mrr": sum(r["rr"] for r in rows) / len(rows),
        "p50_ms": statistics.median(lat),
        "p95_ms": lat[int(len(lat) * 0.95) - 1],
        "mean_ms": sum(lat) / len(lat),
        "errors": sum(1 for r in rows if r.get("error")),
        "rows": rows,
    }
    (RESULTS / f"{name}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"{name:<14} h1={summary['hit1']:.3f} h5={summary['hit5']:.3f} "
        f"mrr={summary['mrr']:.3f} p50={summary['p50_ms']:.0f}ms "
        f"p95={summary['p95_ms']:.0f}ms err={summary['errors']}"
    )
    return summary


async def main():
    queries = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not queries:
        print("FATAL: empty query set", file=sys.stderr)
        return 2

    symbol_index = None
    try:
        from src.core.artifact_paths import get_graph_db_path
        from src.core.graph import PropertyGraph
        from src.core.search.graph_adapter import SymbolIndexAdapter

        pg = PropertyGraph(get_graph_db_path(ROOT))
        symbol_index = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
    except Exception as e:
        print(f"[warn] graph unavailable: {e}")

    reranker = MiniLMReranker(MODEL_DIR)
    await run_arm("demote", 5, None, queries, symbol_index)
    await run_arm("minilm_top10", 10, reranker, queries, symbol_index)
    await run_arm("minilm_top20", 20, reranker, queries, symbol_index)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
