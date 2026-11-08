"""Dense A/B on OUR corpus: index a detached worktree copy with 768-d vectors.

The host holds the PID lock on the real project, so a dense reindex of the live
index is impossible. A detached worktree of the same commit gives the same 500+
files and its own artifact store (keyed by path), so the comparison is fair.

Stage 1 (index):  MSCODEBASE_DENSE_OFF=false python probe_dense_corpus.py index
Stage 2 (query):  python probe_dense_corpus.py query            (lexical, sqlite)
                  MSCODEBASE_DENSE_OFF=false python probe_dense_corpus.py query
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

COPY = Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\mscodebase_dense_ab")
OUT = ROOT / "experiments" / "xerj_2026_11" / "dense_ab.json"

# no-identifier questions that BM25 answered with 0 recall on the live index
# (REPORT.md §9) plus four controls with an identifier.
TASKS = [
    ("NL", "Где решается, нужно ли переиндексировать файл?", "src/core/indexing/freshness.py"),
    ("NL", "Какая функция возвращает путь прогресса?", "src/core/artifact_paths.py"),
    ("NL", "Какой документ является каноном публичных чисел?", "docs/FACTS.md"),
    ("NL", "Где LSP-инструмент отправляет за ссылками?", "src/mcp/tools/lsp_tools.py"),
    ("ID", "Где определяется `build_call_graph`?", "src/core/indexing/symbol_index.py"),
    ("ID", "Где определяется `IndexStatusReporter`?", "src/core/indexing/index_status.py"),
    ("ID", "Где определяется `FreshnessChecker`?", "src/core/indexing/freshness.py"),
    ("ID", "Где определяется `SymbolIndexAdapter`?", "src/core/search/graph_adapter.py"),
]


def main() -> int:
    stage = sys.argv[1] if len(sys.argv) > 1 else "query"
    from src.core.di_container import (
        IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
    )

    services = create_service_collection(COPY)
    if stage == "index" and os.getenv("MSCODEBASE_DENSE_OFF", "true").lower() in ("false", "0", "no"):
        # The host enables llama.cpp by hand (server_factory.py:666); a side
        # process must do the same, otherwise embed_batch waits for a provider
        # forever (measured: the first run sat idle for 25 minutes).
        from src.providers.embedder.remote_embedder import RemoteEmbedder
        embedder = services.resolve(RemoteEmbedder)
        with embedder._mode_lock:
            embedder.mode = "llama_cpp"
        print(f"embedder dim={embedder.embedding_dim} ready={embedder.is_ready()}")
    registry = services.resolve(ProjectIndexerRegistry)
    indexer = registry.get_indexer(COPY, factory=services.resolve(IndexerFactoryKey))
    try:
        if stage == "index":
            print(f"indexing {COPY} (dense={not os.getenv('MSCODEBASE_DENSE_OFF','true').lower() in ('1','true','yes')})")
            started = time.perf_counter()
            indexer.index_project(str(COPY))
            print(f"done in {time.perf_counter() - started:.1f}s")
            status = indexer.get_status()
            print("status:", {k: status.get(k) for k in ("total_chunks", "unique_files", "store")})
            return 0

        from src.mcp.tools.investigate_tool import InvestigateTool

        tool = InvestigateTool(services)
        rows = []
        for kind, question, gold in TASKS:
            text = asyncio.run(tool.execute(query=question, limit=8,
                                            project_root=str(COPY)))
            files = [p.replace("\\", "/") for p in
                     __import__("re").findall(r"^\d+\. (.+?):\d+", text, re.M)]
            rank = next((i for i, f in enumerate(files, 1) if f.endswith(gold)), 0)
            rows.append({"kind": kind, "q": question, "gold": gold, "rank": rank,
                         "files": files[:3]})
            print(f"[{kind}] rank={rank or 'absent':<7} {question[:50]}")
        hits_nl = sum(1 for r in rows if r["kind"] == "NL" and r["rank"])
        hits_id = sum(1 for r in rows if r["kind"] == "ID" and r["rank"])
        print(f"\nNL top-10: {hits_nl}/4 | ID top-10: {hits_id}/4")
        prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
        prev[os.getenv("AB_MODE", "lexical")] = rows
        OUT.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8", newline="")
        return 0
    finally:
        sd = getattr(services, "shutdown", None)
        if callable(sd):
            try:
                asyncio.run(sd())
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
