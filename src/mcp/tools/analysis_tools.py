"""Инструменты анализа кода: structural_search, get_repo_map, get_repo_rank,
scan_changes, generate_chunk_summaries.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary, ToolError
from src.core.file_guard import FileGuard
from src.core.indexer import Indexer
from src.core.parser import CodeParser
from src.core.remote_embedder import RemoteEmbedder
from src.core.searcher import Searcher
from src.core.symbol_index import SymbolIndex
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.analysis_tools")


class StructuralSearchTool(MCPTool):
    """structural_search — поиск по AST-паттернам (Tree-sitter)."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="structural_search")
        self.parser = services.resolve(CodeParser)

    @error_boundary("structural_search", timeout_ms=15000)
    async def execute(
        self,
        project_root: str,
        pattern: str = "class_inheritance",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        from src.core.structural_search import StructuralSearcher

        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return {"status": "error", "message": f"Path does not exist: {project_root}"}

        searcher = StructuralSearcher(self.parser)
        result = searcher.search(
            target_path,
            pattern_name=pattern,
            max_results=30,
        )
        return {
            "status": "ok",
            "pattern": pattern,
            "results": searcher.format_results(result),
        }


class GetRepoMapTool(MCPTool):
    """get_repo_map — текстовая карта репозитория."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_repo_map")
        self.symbol_index = services.resolve(SymbolIndex)

    @error_boundary("get_repo_map", timeout_ms=15000)
    async def execute(
        self, project_root: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        if not self.symbol_index:
            return {"status": "error", "message": "Symbol index is not available"}

        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return {"status": "error", "message": f"Path does not exist: {project_root}"}

        if hasattr(self.symbol_index, "get_repo_map"):
            raw = self.symbol_index.get_repo_map(str(target_path))
            # Форматируем структуру
            structure = []
            for item in raw.get("structure", []):
                item_type = item.get("type", "file")
                symbol_entry = raw.get("symbols_by_file", {}).get(
                    item.get("path", ""),
                    raw.get("symbols_by_file", {}).get(
                        item.get("path", "").replace("/", "\\"),
                        None,
                    ),
                )
                symbols = []
                if symbol_entry:
                    for sym in symbol_entry[:10]:
                        s_name = (
                            sym.get("name")
                            if isinstance(sym, dict)
                            else getattr(sym, "symbol", "unknown")
                        )
                        s_kind = (
                            sym.get("kind")
                            if isinstance(sym, dict)
                            else getattr(sym, "kind", "unknown")
                        )
                        symbols.append({"name": s_name, "kind": s_kind})

                structure.append({
                    "type": item_type,
                    "name": item.get("name"),
                    "path": item.get("path"),
                    "symbols": symbols,
                })

            return {
                "status": "ok",
                "project": target_path.name,
                "total_files": raw.get("total_files", 0),
                "total_symbols": raw.get("total_symbols", 0),
                "structure": structure,
            }

        return {
            "status": "warning",
            "message": f"Repo map not supported for {target_path.name}",
        }


class GetRepoRankTool(MCPTool):
    """get_repo_rank — рейтинг важности символов (PageRank)."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_repo_rank")
        self.symbol_index = services.resolve(SymbolIndex)

    @error_boundary("get_repo_rank", timeout_ms=10000)
    async def execute(
        self,
        project_root: str,
        top_k: int = 10,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        if not self.symbol_index:
            return {"status": "error", "message": "Symbol index not available"}

        ranks = self.symbol_index.compute_repo_rank()
        if not ranks:
            return {"status": "warning", "message": "Call graph is empty"}

        sorted_ranks = sorted(ranks.items(), key=lambda x: x[1], reverse=True)[:top_k]

        items = []
        for symbol, score in sorted_ranks:
            defs = self.symbol_index.find_definitions(symbol)
            kind = defs[0].kind if defs else "unknown"
            file = defs[0].file_path if defs else "unknown"
            items.append({
                "symbol": symbol,
                "score": round(score, 4),
                "kind": kind,
                "file": file,
            })

        return {
            "status": "ok",
            "top_k": len(items),
            "items": items,
        }


class ScanChangesTool(MCPTool):
    """scan_changes — архитектурный дифф при сканировании изменений."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="scan_changes")
        self.indexer = services.resolve(Indexer)
        self.symbol_index = services.resolve(SymbolIndex)
        self.parser = services.resolve(CodeParser)
        self.embedder = services.resolve(RemoteEmbedder)

    @error_boundary("scan_changes", timeout_ms=120000)
    async def execute(
        self, project_root: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return {"status": "error", "message": f"Path does not exist: {project_root}"}

        # Переключаем индекс на проект
        self.indexer.switch_project(target_path)
        project_file_guard = FileGuard(target_path)
        self.indexer.file_guard = project_file_guard

        logger.info(f"Scanning changes for {target_path.name}...")

        # Полная переиндексация
        indexed_count = await asyncio.to_thread(
            self.indexer.index_project, target_path
        )

        # Обновляем SymbolIndex
        if hasattr(self.symbol_index, "index_project"):
            await asyncio.to_thread(
                self.symbol_index.index_project, target_path, self.parser
            )

        # Архитектурный дифф
        arch_diff = {}
        if hasattr(self.symbol_index, "get_architectural_diff") and indexed_count > 0:
            try:
                import pandas as pd

                df = self.indexer.table.to_pandas()
                changed_files = list(df["file_path"].unique())[:20]
                diff_result = self.symbol_index.get_architectural_diff(changed_files)
                if diff_result:
                    arch_diff = {
                        "impact_summary": diff_result.get("impact_summary", ""),
                        "impact_files": diff_result.get("impact_files", [])[:8],
                    }
            except Exception as diff_err:
                logger.debug(f"Architectural diff error: {diff_err}")

        embedder_mode = getattr(self.embedder, "mode", "unknown")
        return {
            "status": "ok",
            "project": target_path.name,
            "files_updated": indexed_count,
            "embedder_mode": embedder_mode,
            "architectural_diff": arch_diff,
        }


class GenerateChunkSummariesTool(MCPTool):
    """generate_chunk_summaries — генерация LLM-описаний для чанков."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="generate_chunk_summaries")
        self.indexer = services.resolve(Indexer)
        self.embedder = services.resolve(RemoteEmbedder)

    @error_boundary("generate_chunk_summaries", timeout_ms=300000)
    async def execute(
        self, project_root: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        from src.core.chunk_summarizer import ChunkSummarizer

        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return {"status": "error", "message": f"Path does not exist: {project_root}"}

        table = self.indexer.table
        if table is None:
            return {"status": "error", "message": "LanceDB table not initialized"}

        import pandas as pd

        df = table.to_pandas()
        if df.empty:
            return {"status": "error", "message": "Database is empty"}

        # Находим чанки без summary
        has_summary_col = "summary" in df.columns
        if has_summary_col:
            mask_no_summary = (
                df["summary"].isna()
                | (df["summary"] == "")
                | (df["summary"].str.strip() == "")
            )
            chunks_without = df[mask_no_summary]
        else:
            chunks_without = df

        total_chunks = len(df)
        chunks_to_process = len(chunks_without)

        if chunks_to_process == 0:
            return {
                "status": "ok",
                "total_chunks": total_chunks,
                "chunks_processed": 0,
                "message": "All chunks already have summaries",
            }

        cache_dir = self.indexer.db_path.parent / "summaries_cache"
        summarizer = ChunkSummarizer(embedder=self.embedder, cache_dir=cache_dir)

        # Генерируем батчами по 50
        batch_size = 50
        updated_count = 0
        error_count = 0
        start_time = time.time()

        for batch_start in range(0, chunks_to_process, batch_size):
            batch_df = chunks_without.iloc[batch_start: batch_start + batch_size]
            records_to_update = []

            for idx, row in batch_df.iterrows():
                try:
                    code = row.get("text", "")
                    symbol_name = row.get("symbol_name", "")
                    context = row.get("file_path", "")
                    summary = summarizer.summarize_chunk(code, symbol_name, context)
                    records_to_update.append({
                        "id": row["id"],
                        "vector": row["vector"],
                        "text": row["text"],
                        "text_full": row.get("text_full", row["text"]),
                        "file_path": row["file_path"],
                        "file_hash": row.get("file_hash", ""),
                        "chunk_index": row.get("chunk_index", 0),
                        "source": row.get("source", ""),
                        "indexed_at": row.get("indexed_at", ""),
                        "summary": summary,
                    })
                    updated_count += 1
                except Exception as e:
                    logger.debug(f"Summary generation error: {e}")
                    error_count += 1

            if records_to_update:
                try:
                    for rid in [r["id"] for r in records_to_update]:
                        try:
                            table.delete(f"id = '{rid}'")
                        except Exception:
                            pass
                    table.add(records_to_update)
                except Exception as e:
                    logger.warning(f"Batch update error: {e}")
                    error_count += len(records_to_update)
                    updated_count -= len(records_to_update)

        summarizer.save_cache()
        stats = summarizer.get_stats()

        return {
            "status": "ok",
            "total_chunks": total_chunks,
            "chunks_without_summary": chunks_to_process,
            "updated": updated_count,
            "errors": error_count,
            "llm_generations": stats.get("generated", 0),
            "cache_hits": stats.get("cache_hits", 0),
            "elapsed_seconds": round(time.time() - start_time, 1),
        }


# Need asyncio for ScanChangesTool
import asyncio  # noqa: E402

__all__ = [
    "StructuralSearchTool",
    "GetRepoMapTool",
    "GetRepoRankTool",
    "ScanChangesTool",
    "GenerateChunkSummariesTool",
]
