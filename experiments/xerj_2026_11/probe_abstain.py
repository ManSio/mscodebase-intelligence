"""Abstention check: negatives must not produce file:line, positives must."""
import asyncio
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import (  # noqa: E402
    IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
)
from src.mcp.tools.investigate_tool import InvestigateTool  # noqa: E402

TASKS = [
    ("N01", "negative", "Где реализовано «согласие партнёрской модели» (`partner_agreement`)?"),
    ("N02", "negative", "Где читается `XERJ_FACTS_MODEL_DIR` (`facts_model_dir`)?"),
    ("N03", "negative", "Где ключ подписи Corpus Hub (`corpus_hub_signing_key`)?"),
    ("N04", "negative", "Где `consensus_partner_agreement`?"),
    ("P01", "positive", "Где определяется `build_call_graph` и что оно возвращает?"),
    ("P04", "positive", "Где решается, нужно ли переиндексировать файл?"),
    ("P16", "positive", "Где описан контракт «артефакты вне проекта»?"),
]

services = create_service_collection(ROOT)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    registry.get_indexer(ROOT, factory=services.resolve(IndexerFactoryKey))
    tool = InvestigateTool(services)
    for task_id, kind, question in TASKS:
        for flag in (False, True):
            text = asyncio.run(tool.execute(
                query=question, limit=8, include_neighbours=flag))
            rows = len(re.findall(r"^\d+\. .+?:\d+", text, re.M))
            withheld = re.search(r"Neighbours withheld: (\d+)", text)
            print(f"{task_id} {kind:<8} neighbours={str(flag):<5} rows={rows} "
                  f"withheld={withheld.group(1) if withheld else 0}")
finally:
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
