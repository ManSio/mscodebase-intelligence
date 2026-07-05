"""Инструменты анализа кода: structural_search, get_repo_map, get_repo_rank,
scan_changes, generate_chunk_summaries.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import ToolError, error_boundary
from src.core.file_guard import FileGuard
from src.core.indexer import Indexer
from src.core.parser import CodeParser
from src.core.remote_embedder import RemoteEmbedder
from src.core.searcher import Searcher
from src.core.symbol_index import SymbolIndex
from src.mcp.tools.base import MCPTool
from src.utils.ui_formatter import format_repo_rank

logger = logging.getLogger("mscodebase_server.analysis_tools")


class StructuralSearchTool(MCPTool):
    """structural_search — поиск по AST-паттернам (Tree-sitter)."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="structural_search")

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
            return {
                "status": "error",
                "message": f"Path does not exist: {project_root}",
            }

        searcher = StructuralSearcher(self.resolve_parser())
        # CPU-bound: Tree-sitter AST парсинг — выгружаем в ThreadPool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: searcher.search(
                target_path,
                pattern_name=pattern,
                max_results=30,
            ),
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

    @error_boundary("get_repo_map", timeout_ms=15000)
    async def execute(
        self, project_root: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        if not self.resolve_symbol_index():
            return {"status": "error", "message": "Symbol index is not available"}

        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return {
                "status": "error",
                "message": f"Path does not exist: {project_root}",
            }

        if hasattr(self.resolve_symbol_index(), "get_repo_map"):
            raw = self.resolve_symbol_index().get_repo_map(str(target_path))
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

                structure.append(
                    {
                        "type": item_type,
                        "name": item.get("name"),
                        "path": item.get("path"),
                        "symbols": symbols,
                    }
                )

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

    @error_boundary("get_repo_rank", timeout_ms=10000)
    async def execute(
        self,
        project_root: str,
        top_k: int = 10,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        if not self.resolve_symbol_index():
            return {"status": "error", "message": "Symbol index not available"}

        ranks = self.resolve_symbol_index().compute_repo_rank()
        if not ranks:
            return {"status": "warning", "message": "Call graph is empty"}

        sorted_ranks = sorted(ranks.items(), key=lambda x: x[1], reverse=True)[:top_k]
        _start = time.monotonic()

        items = []
        for symbol, score in sorted_ranks:
            defs = self.resolve_symbol_index().find_definitions(symbol)
            kind = defs[0].kind if defs else "unknown"
            file = defs[0].file_path if defs else "unknown"
            items.append(
                {
                    "symbol": symbol,
                    "score": round(score, 4),
                    "kind": kind,
                    "file": file,
                }
            )

        exec_ms = int((time.monotonic() - _start) * 1000)
        raw = {"top_k": len(items), "items": items}
        return {
            "status": "ok",
            "content": format_repo_rank(items, exec_ms, raw),
        }


class ScanChangesTool(MCPTool):
    """scan_changes — архитектурный дифф (фоновый режим).

    Запускает полную переиндексацию + анализ изменений в фоне.
    Возвращает job_id для отслеживания через get_task_status().
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="scan_changes")

    @error_boundary("scan_changes", timeout_ms=5000)
    async def execute(
        self, project_root: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return {
                "status": "error",
                "message": f"Path does not exist: {project_root}",
            }

        # Резолвим зависимости ДО фоновой задачи (ThreadPool не имеет доступа к async DI)
        indexer = self.resolve_indexer()
        symbol_index = self.resolve_symbol_index()
        parser = self.resolve_parser()
        embedder = self.resolve_embedder()

        from src.core.task_queue import get_task_queue

        task_queue = get_task_queue()

        task_id = task_queue.submit_sync(
            "scan_changes",
            self._run_scan_sync,
            target_path,
            indexer,
            symbol_index,
            parser,
            embedder,
        )

        return {
            "status": "ok",
            "task_id": task_id,
            "project": target_path.name,
            "message": f"✅ Сканирование запущено в фоне. Task ID: {task_id}",
            "check_status_via": "get_task_status",
            "poll_interval_seconds": 30,
        }

    @staticmethod
    def _run_scan_sync(
        target_path: Path,
        indexer: Any,
        symbol_index: Any,
        parser: Any,
        embedder: Any,
    ) -> str:
        """Синхронное выполнение сканирования в ThreadPool."""
        import time

        from src.core.file_guard import FileGuard

        _t = time.time()
        logger.info(f"[bg] scan_changes: {target_path.name}...")

        try:
            # Переключаем и индексируем
            indexer.switch_project(target_path)
            indexer.file_guard = FileGuard(target_path)
            indexed_count = indexer.index_project(target_path)

            # SymbolIndex
            if hasattr(symbol_index, "index_project"):
                symbol_index.index_project(target_path, parser)

            # Архитектурный дифф
            diff_lines = []
            if hasattr(symbol_index, "get_architectural_diff") and indexed_count > 0:
                try:
                    import pandas as pd

                    df = indexer.table.to_pandas()
                    changed_files = list(df["file_path"].unique())[:20]
                    diff_result = symbol_index.get_architectural_diff(changed_files)
                    if diff_result:
                        diff_lines.append(diff_result.get("impact_summary", ""))
                        for f in diff_result.get("impact_files", [])[:8]:
                            diff_lines.append(
                                f"  • {f.get('file', '')} ({f.get('impact', '')})"
                            )
                except Exception as diff_err:
                    logger.debug(f"[bg] diff error: {diff_err}")

            elapsed = round(time.time() - _t, 1)
            embedder_mode = getattr(embedder, "mode", "unknown")

            lines = [
                f"✅ Scan complete: {target_path.name}",
                f"  • Files updated: {indexed_count}",
                f"  • Embedder: {embedder_mode}",
                f"  • Elapsed: {elapsed}s",
            ]
            if diff_lines:
                lines.append(f"  • Architectural diff:")
                lines.extend(diff_lines)
            lines.append(f"💡 *Следующее сканирование: не ранее чем через 2 минуты.*")
            return "\n".join(lines)

        except Exception as e:
            logger.error(f"[bg] scan_chages failed: {e}")
            return f"❌ Scan failed: {target_path.name}: {e}"


class GenerateChunkSummariesTool(MCPTool):
    """generate_chunk_summaries — генерация LLM-описаний для чанков."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="generate_chunk_summaries")

    @error_boundary("generate_chunk_summaries", timeout_ms=300000)
    async def execute(
        self, project_root: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        from src.core.chunk_summarizer import ChunkSummarizer

        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return {
                "status": "error",
                "message": f"Path does not exist: {project_root}",
            }

        table = self.resolve_indexer().table
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

        cache_dir = self.resolve_indexer().db_path.parent / "summaries_cache"
        summarizer = ChunkSummarizer(
            embedder=self.resolve_embedder(), cache_dir=cache_dir
        )

        # Генерируем батчами по 50
        batch_size = 50
        updated_count = 0
        error_count = 0
        start_time = time.time()

        for batch_start in range(0, chunks_to_process, batch_size):
            batch_df = chunks_without.iloc[batch_start : batch_start + batch_size]
            records_to_update = []

            for idx, row in batch_df.iterrows():
                try:
                    code = row.get("text", "")
                    symbol_name = row.get("symbol_name", "")
                    context = row.get("file_path", "")
                    summary = summarizer.summarize_chunk(code, symbol_name, context)
                    records_to_update.append(
                        {
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
                        }
                    )
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
            "message": f"✅ {updated_count} чанков обработано. "
            f"💡 *Не запускай повторно следующие 5 минут.*",
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
