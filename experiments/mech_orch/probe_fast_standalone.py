"""Diagnostic probe: why does mode=fast return empty in standalone (E3 artifact)."""
import asyncio, json, os, sys, time
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXT = Path(os.getenv("EXT_ROOT", r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence"))
if str(EXT) not in sys.path:
    sys.path.insert(0, str(EXT))
try:
    from dotenv import load_dotenv
    env = PROJECT_ROOT / ".env"
    if env.exists():
        load_dotenv(env)
except ImportError:
    pass
os.environ.setdefault("PYTHONPATH", str(EXT))
os.environ["PROJECT_PATH"] = str(PROJECT_ROOT)
os.environ["LLAMA_CPP_ENABLED"] = "true"
import logging
logging.basicConfig(level=logging.DEBUG, stream=sys.stderr, format="%(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

from src.config.settings import get_config
from src.core.artifact_paths import get_db_path
from src.providers.embedder.remote_embedder import RemoteEmbedder
from src.core.indexing.file_guard import FileGuard
from src.core.indexing.indexer import Indexer
from src.core.search.engine import Searcher
from src.core.di_container import create_service_collection
from src.core.indexing.parser import CodeParser
from src.core.indexing.symbol_index import SymbolIndex

async def main():
    services = create_service_collection(PROJECT_ROOT)
    embedder = services.resolve(RemoteEmbedder)
    db_path = get_db_path(PROJECT_ROOT)
    indexer = Indexer(db_path=db_path, embedder=embedder, file_guard=FileGuard(PROJECT_ROOT),
                      project_path=PROJECT_ROOT, parser=CodeParser(), symbol_index=SymbolIndex())
    searcher = Searcher(indexer, embedder)
    indexer.set_searcher(searcher)
    n = indexer.table.count_rows() if indexer.table is not None else -1
    print("rows:", n, "dbm_is_reindexing:", indexer.db_manager.is_reindexing() if hasattr(indexer, 'db_manager') else "n/a")
    for mode in ("fast", "quality"):
        t0 = time.perf_counter()
        out = searcher.search_with_mode("def hybrid_search", mode=mode, limit=5)
        dt = (time.perf_counter() - t0) * 1000
        print(f"[{mode}] wall={dt:.0f}ms timing={json.dumps(out.get('timing_ms', {}))} n={len(out.get('results', []))}")
        tr = out.get("trace")
        if tr:
            s = json.dumps(tr, default=str)[:600]
            print(f"[{mode}] trace={s}")
        cache_hit = out.get("cache_hit")
        print(f"[{mode}] cache_hit={cache_hit} model={out.get('model_info')}")

asyncio.run(main())