"""
Reranker load test: starts the in-process ONNX reranker server (bge-reranker-v2-m3)
and fires many rerank queries at it, measuring latency + score sanity.

The reranker model (bge-reranker-v2-m3/model.onnx) already exists on disk.
The server runs on port 1235 by default.
"""
import subprocess
import sys
import time
import httpx
from pathlib import Path

EXT = Path(r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence")
PORT = 1235
HOST = "127.0.0.1"

# Start the ONNX server (reranker enabled)
proc = subprocess.Popen(
    [str(EXT / "venv" / "Scripts" / "python.exe"), str(EXT / "src" / "core" / "onnx_server.py"),
     "--port", str(PORT), "--host", HOST,
     "--model-dir", str(EXT / ".codebase_models" / "onnx" / "e5-base-v2"),
     "--reranker-dir", str(EXT / ".codebase_models" / "onnx" / "reranker-bge-reranker-v2-m3")],
    cwd=str(EXT),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
print(f"[server] started pid {proc.pid}, waiting for /health ...")
client = httpx.Client(timeout=30, base_url=f"http://{HOST}:{PORT}")
# wait for ready
for i in range(30):
    try:
        r = client.get("/v1/models")
        if r.status_code == 200:
            print(f"[server] ready after {i}s: {r.json()}")
            break
    except Exception:
        time.sleep(1)
else:
    print("[server] FAILED to start"); proc.terminate(); sys.exit(1)

# Rerank query/passage pairs
pairs = [
    ("def hybrid_search_async", [
        "async def hybrid_search_async(self, query, limit=5): ...",
        "def something_unrelated(x): return x + 1",
        "class Searcher: def hybrid_search(self, query, limit): ...",
        "The weather today is sunny and warm.",
    ]),
    ("reranker bge-m3 llama-server", [
        "self._reranker = MultiProviderReranker(lm_studio_url=...)",
        "BGE-M3 reranker served via llama.cpp on port 8081.",
        "def index_project(self, project_path): ...",
        "I like to eat pizza with my friends.",
    ]),
    ("Cypher OPTIONAL MATCH LEFT JOIN", [
        "LEFT JOIN generated for OPTIONAL MATCH in cypher_engine.translate()",
        "SELECT * FROM nodes WHERE id = 1",
        "def _process_path_pattern(self, join_type, left_labels_in_on): ...",
        "The cat sat on the mat.",
    ]),
    ("index_guard schema validation vector dim", [
        "IndexGuard._validate_schema checks vec_type.list_size == expected_dim",
        "def _validate_schema(self): errors = []",
        "print('hello world')",
        "Water boils at 100 degrees celsius.",
    ]),
    ("file_guard should_skip_file relative path", [
        "self.project_path = Path(project_path).resolve()  # fix relative/absolute",
        "def should_skip_file(self, file_path): ...",
        "x = 42",
        "Birds can fly in the sky.",
    ]),
    ("PropertyGraph ASSIGNED_FROM edge", [
        "MATCH (s)-[e:ASSIGNED_FROM]->(t) WHERE t.name = 'x'",
        "class PropertyGraph: def add_edge(self, ...): ...",
        "import os",
        "Music is a universal language.",
    ]),
    ("LanceDB IVF index build", [
        "table.create_index('vector', metric='cosine')  # IVF",
        "def search_async(self, vector, limit): ...",
        "y = 'test'",
        "The book was on the shelf.",
    ]),
    ("intel_auto_collect_adrs git log async", [
        "proc = await asyncio.create_subprocess_exec('git', 'log', ...)",
        "async def intel_auto_collect_adrs(self, max_commits=50): ...",
        "z = [1,2,3]",
        "Cars drive on the road.",
    ]),
]

print(f"\n=== RERANKER LOAD TEST ({len(pairs)} queries x 4 passages) ===")
all_ok = True
for q, passages in pairs:
    try:
        t0 = time.perf_counter()
        r = client.post("/v1/rerank", json={"query": q, "passages": passages})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            print(f"  ERR {r.status_code}: {q} -> {r.text[:120]}")
            all_ok = False
            continue
        scores = r.json().get("scores", [])
        # sanity: relevant passage (index 0) should score higher than irrelevant (last)
        ok = scores and scores[0] > scores[-1]
        all_ok = all_ok and ok
        print(f"  [{dt:6.1f}ms] q={q[:40]:40} scores={[round(s,3) for s in scores]} rel>irr={ok}")
    except Exception as e:
        print(f"  EXC {q}: {e}")
        all_ok = False

# Throughput: 20 rapid reranks
N = 20
t0 = time.perf_counter()
for _ in range(N):
    client.post("/v1/rerank", json={"query": "test query", "passages": ["a", "b", "c"]})
dt = (time.perf_counter() - t0) / N * 1000
print(f"\n[throughput] {N} reranks avg={dt:.1f}ms (~{1000/dt:.1f} reranks/s)")

print(f"\nRESULT: {'ALL OK' if all_ok else 'SOME FAILED'}")
proc.terminate()
