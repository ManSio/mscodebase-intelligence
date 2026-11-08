"""Does the Cyrillic-keyword channel reach the gold files the searcher missed?"""
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

CASES = [
    ("P04-ru", "Где решается, нужно ли переиндексировать файл?", "src/core/indexing/freshness.py"),
    ("P04-en", "Where is the decision made whether a file must be reindexed?", "src/core/indexing/freshness.py"),
    ("P06-ru", "Какая функция возвращает путь прогресса?", "src/core/artifact_paths.py"),
    ("P06-en", "Which function returns the progress file path?", "src/core/artifact_paths.py"),
    ("P14-ru", "Какой документ является каноном публичных чисел?", "docs/FACTS.md"),
    ("P14-en", "Which document is the canon of published numbers?", "docs/FACTS.md"),
    ("P15-ru", "Где LSP-инструмент отправляет за ссылками?", "src/mcp/tools/lsp_tools.py"),
    ("P15-en", "Where does the LSP tool send the user for references?", "src/mcp/tools/lsp_tools.py"),
]

services = create_service_collection(ROOT)
try:
    registry = services.resolve(ProjectIndexerRegistry)
    registry.get_indexer(ROOT, factory=services.resolve(IndexerFactoryKey))
    tool = InvestigateTool(services)
    hits = 0
    for task_id, question, gold in CASES:
        text = asyncio.run(tool.execute(query=question, limit=8))
        rows = re.findall(r"^\d+\. (.+?):\d+", text, re.M)
        rank = next((i for i, f in enumerate(rows, 1)
                     if f.replace("\\", "/").endswith(gold)), 0)
        hits += bool(rank)
        channels = re.findall(r"\[([^\]]+)\]", text)[:3]
        print(f"{task_id:<7} rank={rank or 'absent':<7} rows={len(rows)} "
              f"channels={channels}")
    print(f"\ntop-10 hits: {hits}/{len(CASES)}")
finally:
    sd = getattr(services, "shutdown", None)
    if callable(sd):
        try:
            asyncio.run(sd())
        except Exception:
            pass
