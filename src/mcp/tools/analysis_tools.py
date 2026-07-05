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
from src.utils.i18n import _
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
        from src.core.error_handler import record_tool_result
        from src.core.structural_search import StructuralSearcher

        target_path = Path(project_root).resolve()
        if not target_path.exists():
            record_tool_result(
                "structural_search", route="ast", confidence=0.0, results_count=0
            )
            return {
                "status": "error",
                "message": _("Path does not exist: {path}", path=project_root),
            }

        searcher = StructuralSearcher(self.resolve_parser())
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: searcher.search(target_path, pattern_name=pattern, max_results=30),
        )

        formatted = searcher.format_results(result)
        count = len(result.get("results", [])) if isinstance(result, dict) else 0
        record_tool_result(
            "structural_search",
            route="ast",
            confidence=0.95 if count > 0 else 0.3,
            results_count=count,
            detail=f"pattern={pattern}, {count} matches",
        )

        return {"status": "ok", "pattern": pattern, "results": formatted}


class GetRepoMapTool(MCPTool):
    """get_repo_map — текстовая карта репозитория."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_repo_map")

    @error_boundary("get_repo_map", timeout_ms=15000)
    async def execute(
        self, project_root: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        if not self.resolve_symbol_index():
            return {
                "status": "error",
                "message": _("Symbol index is not available"),
            }

        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return {
                "status": "error",
                "message": _("Path does not exist: {path}", path=project_root),
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
            "message": _(
                "Repo map not supported for {name}",
                name=target_path.name,
            ),
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
            return {
                "status": "error",
                "message": _("Symbol index not available"),
            }

        ranks = self.resolve_symbol_index().compute_repo_rank()
        if not ranks:
            return {
                "status": "warning",
                "message": _("Call graph is empty"),
            }

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
                "message": _("Path does not exist: {path}", path=project_root),
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
            "message": _(
                "✅ Background scan started. Task ID: {task_id}",
                task_id=task_id,
            ),
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
                _("✅ Scan complete: {name}", name=target_path.name),
                _("  • Files updated: {count}", count=indexed_count),
                _("  • Embedder: {mode}", mode=embedder_mode),
                _("  • Elapsed: {time}s", time=elapsed),
            ]
            if diff_lines:
                lines.append(_("  • Architectural diff:"))
                lines.extend(diff_lines)
            lines.append(_("💡 *Next scan: no earlier than 2 minutes.*"))
            return "\n".join(lines)

        except Exception as e:
            logger.error(f"[bg] scan_chages failed: {e}")
            return _(
                "❌ Scan failed: {name}: {error}",
                name=target_path.name,
                error=e,
            )


class GenerateChunkSummariesTool(MCPTool):
    """generate_chunk_summaries — генерация LLM-описаний для чанков (фоновый режим)."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="generate_chunk_summaries")

    @error_boundary("generate_chunk_summaries", timeout_ms=5000)
    async def execute(
        self, project_root: str, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        target_path = Path(project_root).resolve()
        if not target_path.exists():
            return {
                "status": "error",
                "message": _("Path does not exist: {path}", path=project_root),
            }

        table = self.resolve_indexer().table
        if table is None:
            return {
                "status": "error",
                "message": _("LanceDB table not initialized"),
            }

        import pandas as pd

        df = table.to_pandas()
        if df.empty:
            return {
                "status": "error",
                "message": _("Database is empty"),
            }

        # Определяем объём работы ДО отправки в фон
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
                "message": _("All chunks already have summaries"),
            }

        # Резолвим зависимости ДО фона
        embedder = self.resolve_embedder()
        cache_dir = self.resolve_indexer().db_path.parent / "summaries_cache"

        from src.core.chunk_summarizer import ChunkSummarizer

        summarizer = ChunkSummarizer(embedder=embedder, cache_dir=cache_dir)

        from src.core.task_queue import get_task_queue

        task_queue = get_task_queue()
        task_id = task_queue.submit_sync(
            "generate_chunk_summaries",
            self._run_summarize_sync,
            chunks_without.to_dict(orient="records"),
            summarizer,
            cache_dir,
            table,
            total_chunks,
            chunks_to_process,
        )

        return {
            "status": "ok",
            "task_id": task_id,
            "total_chunks": total_chunks,
            "chunks_to_process": chunks_to_process,
            "message": _(
                "✅ Background generation started. Task ID: {task_id}",
                task_id=task_id,
            ),
            "check_status_via": "get_task_status",
            "poll_interval_seconds": 30,
        }

    @staticmethod
    def _run_summarize_sync(
        records: list,
        summarizer: Any,
        cache_dir: Path,
        table: Any,
        total_chunks: int,
        chunks_to_process: int,
    ) -> str:
        """Синхронная генерация summary в ThreadPool."""
        import time

        _t = time.time()
        logger.info(f"[bg] generate_chunk_summaries: {chunks_to_process} chunks...")

        batch_size = 50
        updated_count = 0
        error_count = 0

        for batch_start in range(0, chunks_to_process, batch_size):
            batch = records[batch_start : batch_start + batch_size]
            to_update = []

            for row in batch:
                try:
                    summary = summarizer.summarize_chunk(
                        row.get("text", ""),
                        row.get("symbol_name", ""),
                        row.get("file_path", ""),
                    )
                    to_update.append(
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
                    logger.debug(f"[bg] summary error: {e}")
                    error_count += 1

            if to_update:
                try:
                    for r in to_update:
                        try:
                            table.delete(f"id = '{r['id']}'")
                        except Exception:
                            pass
                    table.add(to_update)
                except Exception as e:
                    logger.warning(f"[bg] batch update error: {e}")
                    error_count += len(to_update)
                    updated_count -= len(to_update)

        summarizer.save_cache()
        stats = summarizer.get_stats()
        elapsed = round(time.time() - _t, 1)

        lines = [
            _("✅ Summaries generated: {count} chunks", count=updated_count),
            _(
                "  • Total: {total} | Processed: {processed}",
                total=total_chunks,
                processed=chunks_to_process,
            ),
            _(
                "  • Updated: {updated} | Errors: {errors}",
                updated=updated_count,
                errors=error_count,
            ),
            _("  • LLM calls: {calls}", calls=stats.get("generated", 0)),
            _("  • Cache hits: {hits}", hits=stats.get("cache_hits", 0)),
            _("  • Elapsed: {time}s", time=elapsed),
            _("💡 *Do not rerun for the next 5 minutes.*"),
        ]
        return "\n".join(lines)
