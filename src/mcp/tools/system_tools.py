"""Системные инструменты: get_index_status, get_index_progress, get_index_timeline,
watcher_status, get_logs, get_health_report, predict_eta, run_health_check.

Все инструменты получают зависимости через DI и используют error_boundary.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.core.indexer import Indexer
from src.core.searcher import Searcher
from src.core.symbol_index import SymbolIndex
from src.core.remote_embedder import RemoteEmbedder
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.system_tools")


class GetIndexStatusTool(MCPTool):
    """get_index_status — статистика заполнения векторной базы."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_index_status")

    @error_boundary("get_index_status", timeout_ms=3000)
    async def execute(self, kwargs: Optional[Dict[str, Any]] = None) -> str:
        stats = self.resolve_indexer().get_status()
        if "error" in stats:
            return f"❌ Error: {stats['error']}"

        total_symbols = (
            self.resolve_symbol_index().get_symbol_count()
            if hasattr(self.resolve_symbol_index(), "get_symbol_count")
            else "N/A"
        )
        embedder_mode = getattr(self.resolve_embedder(), "mode", "unknown")
        mode_label = {
            "lm_studio": "🌐 LM Studio",
            "ollama": "🦙 Ollama",
            "onnx": "⚙️ ONNX (локальный)",
            "fallback": "⚠️ Заглушка",
        }.get(embedder_mode, embedder_mode)

        chunks = stats.get("total_chunks", 0)
        files = stats.get("unique_files", 0)
        db_status = stats.get("status", "unknown")

        return (
            f"📊 Статус базы данных MSCodebase:\n"
            f"  • Всего фрагментов кода в базе (LanceDB): {chunks}\n"
            f"  • Проиндексировано уникальных файлов: {files}\n"
            f"  • Найдено структурных символов (Tree-sitter): {total_symbols}\n"
            f"  • Состояние движка: {db_status}\n"
            f"  • Режим эмбеддера: {mode_label}"
        )


class GetIndexProgressTool(MCPTool):
    """get_index_progress — прогресс индексации для всех проектов."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_index_progress")

    @error_boundary("get_index_progress", timeout_ms=5000)
    async def execute(self, kwargs: Optional[Dict[str, Any]] = None) -> dict:
        try:
            from src.core.log_manager import get_log_summary
        except ImportError:
            return {"status": "ok", "progress": []}

        # Получаем базовую статистику
        stats = self.resolve_indexer().get_status()
        return {
            "status": "ok",
            "total_chunks": stats.get("total_chunks", 0),
            "unique_files": stats.get("unique_files", 0),
            "status": stats.get("status", "unknown"),
        }


class GetIndexTimelineTool(MCPTool):
    """get_index_timeline — временная шкала индексации."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_index_timeline")

    @error_boundary("get_index_timeline", timeout_ms=15000)
    async def execute(self, kwargs: Optional[Dict[str, Any]] = None) -> dict:
        from collections import defaultdict
        import pandas as pd

        if not self.resolve_indexer().table or len(self.resolve_indexer().table) == 0:
            return {"status": "warning", "message": "Database is empty"}

        df = self.resolve_indexer().table.to_pandas()
        if df.empty:
            return {"status": "warning", "message": "No data"}

        # Группируем по дате
        date_counts: Dict[str, int] = defaultdict(int)
        oldest_dt = None
        newest_dt = None
        chunks_without_ts = 0

        for _, row in df.iterrows():
            indexed_at = str(row.get("indexed_at", ""))
            if not indexed_at:
                chunks_without_ts += 1
                continue
            try:
                dt = datetime.fromisoformat(indexed_at)
                date_counts[dt.strftime("%Y-%m-%d")] += 1
                if oldest_dt is None or dt < oldest_dt:
                    oldest_dt = dt
                if newest_dt is None or dt > newest_dt:
                    newest_dt = dt
            except (ValueError, TypeError):
                chunks_without_ts += 1

        return {
            "status": "ok",
            "total_chunks": len(df),
            "oldest": oldest_dt.isoformat() if oldest_dt else None,
            "newest": newest_dt.isoformat() if newest_dt else None,
            "without_timestamp": chunks_without_ts,
            "daily_distribution": dict(sorted(date_counts.items())),
        }


class WatcherStatusTool(MCPTool):
    """watcher_status — статус компонентов подсистем индексации и эмбеддинга."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="watcher_status")

    @error_boundary("watcher_status", timeout_ms=15000)
    async def execute(self, kwargs: Optional[Dict[str, Any]] = None) -> dict:
        embedder_mode = getattr(self.resolve_embedder(), "mode", "unknown")
        scanner_thread = getattr(self.resolve_embedder(), "_scanner_thread", None)
        scanner_alive = scanner_thread is not None and scanner_thread.is_alive()

        result = {
            "status": "ok",
            "embedder_mode": embedder_mode,
            "lsp_imported": self._check_lsp_import(),
            "ping_scanner_alive": scanner_alive,
        }

        # Проверяем модели LM Studio
        if embedder_mode in ("lm_studio", "ollama"):
            try:
                result["models"] = self._check_lm_studio_models()
            except Exception as e:
                result["models_error"] = str(e)

        return result

    def _check_lsp_import(self) -> bool:
        try:
            from src.lsp_main import server as lsp_server
            return lsp_server is not None
        except Exception:
            return False

    def _check_lm_studio_models(self) -> dict:
        import httpx
        from src.core.config import get_config

        config = get_config()
        host = getattr(self.embedder, "host", config.embedding.lm_studio_host)
        port = getattr(self.embedder, "port", config.embedding.lm_studio_port)

        with httpx.Client(timeout=3.0) as client:
            r = client.get(f"http://{host}:{port}/api/v0/models")
            if r.status_code != 200:
                return {"available": False, "http_status": r.status_code}

            models = r.json().get("data", [])
            loaded = [{"id": m.get("id"), "type": m.get("type")}
                      for m in models if m.get("state") == "loaded"]
            return {
                "available": True,
                "total_models": len(models),
                "loaded_models": loaded,
            }


class GetLogsTool(MCPTool):
    """get_logs — последние ошибки и предупреждения из логов проекта."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_logs")

    @error_boundary("get_logs", timeout_ms=5000)
    async def execute(
        self, project_root: str = "", kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        from src.core.log_manager import get_log_summary, get_recent_errors

        target_path = Path(project_root).resolve() if project_root else Path.cwd()
        if not target_path.exists():
            return {"status": "error", "message": f"Path does not exist: {project_root}"}

        log_summary = get_log_summary(target_path)
        if isinstance(log_summary, str):
            return {"status": "ok", "summary": log_summary}

        errors = get_recent_errors(target_path) if hasattr(get_recent_errors, "__call__") else []
        return {
            "status": "ok",
            "summary": log_summary,
            "recent_errors": errors[:20],
        }


class GetHealthReportTool(MCPTool):
    """get_health_report — полная диагностика системы."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_health_report")

    @error_boundary("get_health_report", timeout_ms=45000)
    async def execute(
        self, project_root: str = "", kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        from src.core.health_report import HealthReport, format_health_report

        target_path = self.resolve_indexer().project_path
        if project_root:
            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return {"status": "error", "message": f"Path does not exist: {project_root}"}

        report = HealthReport(
            project_path=target_path,
            indexer=self.resolve_indexer(),
            symbol_index=self.resolve_symbol_index(),
            embedder=self.resolve_embedder(),
        )
        result = report.run_full_diagnostic()
        return result


class PredictEtaTool(MCPTool):
    """predict_eta — предсказание времени выполнения операции."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="predict_eta")

    @error_boundary("predict_eta", timeout_ms=3000)
    async def execute(
        self, operation: str, items: int = 1, kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        from src.core.eta_predictor import get_predictor

        predictor = get_predictor()
        est = predictor.estimate(operation, items)
        return {
            "status": "ok",
            "operation": operation,
            "items": items,
            "estimated_seconds": est.get("estimated_seconds", 0),
            "tokens_estimate": est.get("tokens_estimate", 0),
            "confidence": est.get("confidence", "low"),
        }


class RunHealthCheckTool(MCPTool):
    """run_health_check — полная проверка здоровья проекта."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="run_health_check")

    @error_boundary("run_health_check", timeout_ms=30000)
    async def execute(self, kwargs: Optional[Dict[str, Any]] = None) -> dict:
        from src.core.autonomous_fix import AutonomousFixLoop

        fix_loop = AutonomousFixLoop(self.resolve_indexer().project_path)
        health = await fix_loop.health_check()

        return {
            "status": "ok",
            "timestamp": health.get("timestamp", ""),
            "tests": health.get("tests", {}),
            "git_status": health.get("git_status", {}),
            "overall": health.get("overall", "unknown"),
        }


class ReadLiveFileTool(MCPTool):
    """read_live_file — чтение файла из памяти LSP (включая несохранённые изменения).

    Пытается получить текст из LSP VFS (память редактора). Если файл не открыт —
    читает с диска. Это позволяет AI-агенту видеть текущее состояние файла,
    включая правки, которые ещё не сохранены на диск.
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="read_live_file")

    @error_boundary("read_live_file", timeout_ms=3000)
    async def execute(self, absolute_path: str = "", file_path: str = "") -> dict:
        """
        Args:
            absolute_path: Абсолютный путь к файлу (Windows формат)
            file_path: Относительный путь от корня проекта
        """
        # Определяем полный путь
        if absolute_path:
            target = Path(absolute_path).resolve()
        elif file_path:
            target = (self.resolve_indexer().project_path / file_path).resolve()
        else:
            return {"status": "error", "message": "Provide absolute_path or file_path"}

        # Пробуем получить из памяти LSP (актуальная версия)
        content = None
        source = "disk"
        try:
            from src.lsp_main import server as lsp_server
            if lsp_server and hasattr(lsp_server, "workspace"):
                uri = f"file:///{str(target).replace(chr(92), '/')}"
                doc = lsp_server.workspace.get_document(uri)
                if doc and hasattr(doc, "source"):
                    content = doc.source
                    source = "lsp_vfs"
                    logger.debug(f"read_live_file: from LSP VFS ({len(content)} chars)")
        except Exception:
            pass

        # Fallback: читаем с диска
        if content is None:
            if not target.exists():
                return {"status": "error", "message": f"File not found: {target}"}
            try:
                content = target.read_text(encoding="utf-8")
            except Exception as e:
                return {"status": "error", "message": f"Cannot read file: {e}"}

        lines = content.split(chr(10))
        return {
            "status": "ok",
            "path": str(target),
            "source": source,
            "total_lines": len(lines),
            "total_chars": len(content),
            "content": content,
        }


__all__ = [
    "GetIndexStatusTool",
    "GetIndexProgressTool",
    "GetIndexTimelineTool",
    "WatcherStatusTool",
    "GetLogsTool",
    "GetHealthReportTool",
    "PredictEtaTool",
    "RunHealthCheckTool",
    "ReadLiveFileTool",
]
