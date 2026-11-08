import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
)
from src.mcp.tools.investigate_tool import InvestigateTool  # noqa: E402

services = create_service_collection(ROOT)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    indexer = registry.get_indexer(ROOT, factory=services.resolve(IndexerFactoryKey))
    sym = indexer._symbol_index
    print("has_symbol(corpus_hub_signing_key) =", sym.has_symbol("corpus_hub_signing_key"))
    print("has_symbol(partner_agreement)      =", sym.has_symbol("partner_agreement"))
    tool = InvestigateTool(services)
    out = asyncio.run(tool.execute(
        query="Где ключ подписи Corpus Hub (`corpus_hub_signing_key`)?", limit=8))
    print(out[:900])
finally:
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
