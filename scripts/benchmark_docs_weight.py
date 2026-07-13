"""
Эксперимент: подбор docs_bucket_weight для fast mode.

Тестирует 6 весов (1.0, 0.5, 0.3, 0.2, 0.1, 0.0) на 15 запросах.
Собирает: позиция первого кода, code/docs ratio, время.
"""

import os, sys, time, json
from pathlib import Path

EXT = Path(r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence")
sys.path.insert(0, str(EXT))
from dotenv import load_dotenv
load_dotenv(Path(r"D:\Project\MSCodeBase\.env"))
os.environ["PROJECT_PATH"] = "D:\\Project\\MSCodeBase"

from src.core.config import get_config
from src.core.di_container import create_service_collection
from src.core.remote_embedder import RemoteEmbedder
from src.core.searcher import Searcher
from src.core.indexer import Indexer
from src.core.file_guard import FileGuard
from src.core.parser import CodeParser
from src.core.symbol_index import SymbolIndex
from src.core.indexer import _generate_unique_db_path
import lancedb

PR = Path(r"D:\Project\MSCodeBase").resolve()

# Создаём embedder + загружаем провайдер
emb = RemoteEmbedder()
emb._init_provider_async()
print(f"Embedder: mode={emb.mode}")

# Подключаем существующий LanceDB
db_path = _generate_unique_db_path(PR)
db = lancedb.connect(str(db_path))
tbl = db.open_table("codebase_chunks")
n = tbl.count_rows()
print(f"Table: {n} rows")

# Создаём Indexer (не индексируем, только даём ему таблицу)
fg = FileGuard(PR)
idx = Indexer(db_path=db_path, embedder=emb, file_guard=fg, project_path=PR,
              parser=CodeParser(), symbol_index=SymbolIndex())
idx.table = tbl

# Создаём Searcher с BM25 из существующих данных
searcher = Searcher(idx, emb)
searcher.reindex()  # сброс BM25, перестроится при первом поиске

WEIGHTS = [1.0, 0.5, 0.3, 0.2, 0.1, 0.0]
QUERIES = [
    "class Searcher hybrid_search",
    "def embed_batch",
    "class RemoteEmbedder",
    "def _process_path_pattern",
    "class MultiProviderReranker",
    "property graph edge traversal",
    "cypher query left join",
    "index guard schema validation",
    "reranker bge m3 llama server",
    "async subprocess git log",
    "LanceDB vector search IVF",
    "bucket weights code docs penalty",
    "embedding dimension ONNX model",
    "tree sitter parser chunk function",
    "watchdog idle timeout unload",
]

CODE_EXTS = {".py", ".rs", ".ts", ".tsx", ".go", ".js", ".java", ".c", ".cpp", ".h", ".rs"}

results_data = []

for w in WEIGHTS:
    get_config().performance.docs_bucket_weight = w
    print(f"\n── WEIGHT={w} ──")
    for q in QUERIES:
        try:
            t0 = time.perf_counter()
            res = searcher.search_with_mode(q, mode="fast", limit=10)
            dt = (time.perf_counter() - t0) * 1000
        except Exception as e:
            print(f"  ERR {q[:35]:35} {e}")
            continue
        results = res.get("results", [])
        parsed = []
        for r in results:
            meta = r.get("metadata", {}) or {}
            fp = meta.get("file", "")
            ext = Path(fp).suffix.lower()
            is_code = ext in CODE_EXTS
            parsed.append({"file": fp, "is_code": is_code, "score": r.get("final_score", 0.0)})
        
        n_code = sum(1 for p in parsed if p["is_code"])
        n_doc = len(parsed) - n_code
        first_code_pos = next((i+1 for i, p in enumerate(parsed) if p["is_code"]), 0)
        top_files = [p["file"].split("/")[-1].split("\\")[-1] for p in parsed[:5]]
        status = "CODE" if first_code_pos == 1 else f"DOC(pos={first_code_pos})"
        print(f"  {status:15} {q[:35]:35}  code={n_code} docs={n_doc} time={dt:.0f}ms  top={top_files}")
        results_data.append({
            "weight": w, "query": q, "time_ms": round(dt),
            "first_code_pos": first_code_pos, "n_code": n_code, "n_doc": n_doc,
            "code_first": first_code_pos == 1,
        })

# Summary
print(f"\n\n{'='*60}")
print(f"  SUMMARY: weight → code_first / total, avg_code_ratio, avg_time")
print(f"{'='*60}")
for w in WEIGHTS:
    r = [d for d in results_data if abs(d["weight"] - w) < 0.01 and d.get("first_code_pos", 0) >= 0]
    if not r:
        continue
    total = len(r)
    code_first = sum(1 for d in r if d.get("code_first"))
    code_any = sum(1 for d in r if d.get("n_code", 0) > 0)
    avg_code_ratio = sum(d.get("n_code", 0) / max(d.get("n_code", 0) + d.get("n_doc", 0), 1) for d in r) / total
    avg_time = sum(d.get("time_ms", 0) for d in r) / total
    print(f"  weight={w:.1f}:  code_first={code_first}/{total} ({code_first/total*100:.0f}%)  "
          f"code_any={code_any}/{total}  avg_code_ratio={avg_code_ratio:.0%}  avg_time={avg_time:.0f}ms")

# Best weight analysis
print(f"\n── BEST WEIGHT ──")
for w in WEIGHTS:
    r = [d for d in results_data if abs(d["weight"] - w) < 0.01 and d.get("first_code_pos", 0) >= 0]
    if not r:
        continue
    code_first = sum(1 for d in r if d.get("code_first"))
    print(f"  weight={w:.1f}: code_first={code_first}/{len(r)} = {code_first/len(r)*100:.0f}%  "
          f"TOP if code_first > {0.7*len(r):.0f}")
