"""Системные инструменты: get_index_status, get_index_progress, get_index_timeline,
watcher_status, get_logs, get_health_report, predict_eta, run_health_check.

Все инструменты получают зависимости через DI и используют error_boundary.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool
from src.utils.ui_formatter import format_index_status

logger = logging.getLogger("mscodebase_server.system_tools")


class GetIndexStatusTool(MCPTool):
    """get_index_status — статистика заполнения векторной базы."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_index_status")

    @error_boundary("get_index_status", timeout_ms=3000)
    async def execute(self, kwargs: Optional[Dict[str, Any]] = None) -> str:
        # INC-6BCB-v3: определяем project path ПЕРВЫМ (до resolve_indexer,
        # чтобы увидеть ГДЕ мы ищем, даже если indexer пуст).
        try:
            indexer = self.resolve_indexer()
            project_path = indexer.project_path
            project_label = f"📂 Project: {project_path}"
        except Exception as e:
            return f"❌ Cannot resolve project_root: {e}"

        stats = indexer.get_status()
        if "error" in stats:
            return f"{project_label}\n❌ Error: {stats['error']}"

        chunks = stats.get("total_chunks", 0)
        files = stats.get("unique_files", 0)
        db_status = stats.get("status", "unknown")

        sym_idx = self.resolve_symbol_index()
        total_symbols = (
            sym_idx.get_symbol_count()
            if hasattr(sym_idx, "get_symbol_count")
            else "N/A"
        )
        # INC-001 рецидив: chunks есть, symbols=0 → SymbolIndex не загрузился с диска
        # Пробуем перезагрузить из index_guard (как при старте Indexer'а).
        if total_symbols == 0 and chunks > 0:
            try:
                if hasattr(indexer, "_index_guard"):
                    indexer._index_guard.load_symbol_index(sym_idx)
                    total_symbols = sym_idx.get_symbol_count()
            except Exception as _e:
                logger.warning("exception", exc_info=True)
                pass
            if total_symbols == 0:
                chunks = chunks  # сохраняем для форматтера — он добавит ⚠️
        embedder_mode = getattr(self.resolve_embedder(), "mode", "unknown")
        mode_label = {
            "lm_studio": "🌐 LM Studio",
            "ollama": "🦙 Ollama",
            "onnx": "⚙️ ONNX (локальный)",
            "fallback": "⚠️ Заглушка",
        }.get(embedder_mode, embedder_mode)

        # Проверка: есть ли другие проекты в этом окне (multi-window)
        other_projects = []
        try:
            _db = (
                Path(os.environ.get("LOCALAPPDATA", ""))
                / "Zed"
                / "db"
                / "0-stable"
                / "db.sqlite"
            )
            if _db.exists():
                import json as _json
                import sqlite3

                _conn = sqlite3.connect(str(_db), timeout=1.0)
                _cur = _conn.cursor()
                _cur.execute(
                    "SELECT value FROM scoped_kv_store "
                    "WHERE namespace = 'multi_workspace_state'"
                )
                for _row in _cur.fetchall():
                    _state = _json.loads(_row[0])
                    for _g in _state.get("project_groups", []):
                        _p = _g.get("path_list", {}).get("paths", "")
                        if _p and Path(_p).resolve() != Path(project_path).resolve():
                            other_projects.append(_p)
                _conn.close()
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        # Используем UI-форматтер
        output = f"📂 {project_path}\n"
        output += format_index_status(
            chunks=chunks,
            files=files,
            symbols=total_symbols,
            embedder=mode_label,
            status=db_status,
            other_projects=[Path(p).name for p in other_projects]
            if other_projects
            else None,
        )
        return output


class GetIndexProgressTool(MCPTool):
    """get_index_progress — прогресс индексации для всех проектов."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_index_progress")

    @error_boundary("get_index_progress", timeout_ms=5000)
    async def execute(self, kwargs: Optional[Dict[str, Any]] = None) -> dict:
        # Получаем базовую статистику
        stats = self.resolve_indexer().get_status()
        return {
            "status": "ok",
            "total_chunks": stats.get("total_chunks", 0),
            "unique_files": stats.get("unique_files", 0),
            "indexer_status": stats.get("status", "unknown"),
        }


class GetIndexTimelineTool(MCPTool):
    """get_index_timeline — временная шкала индексации."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="get_index_timeline")

    @error_boundary("get_index_timeline", timeout_ms=15000)
    async def execute(self, kwargs: Optional[Dict[str, Any]] = None) -> dict:
        from collections import defaultdict


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
        # INC-6BCB-v3.1: self.embedder НЕ существует в MCPTool —
        # нужен resolve_embedder(). Также _scanner_thread — атрибут RemoteEmbedder,
        # проверяем через getattr с default=None (безопасно при отсутствии).
        try:
            embedder = self.resolve_embedder()
            embedder_mode = getattr(embedder, "mode", "unknown")
            scanner_thread = getattr(embedder, "_scanner_thread", None)
            scanner_alive = scanner_thread is not None and scanner_thread.is_alive()
        except Exception as e:
            return {
                "status": "error",
                "error": f"embedder unavailable: {e}",
                "embedder_mode": "unknown",
                "lsp_imported": self._check_lsp_import(),
                "ping_scanner_alive": False,
            }

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

        from src.config.settings import get_config

        config = get_config()
        # INC-6BCB-v3.1: self.embedder → self.resolve_embedder()
        embedder = self.resolve_embedder()
        host = getattr(embedder, "host", config.embedding.lm_studio_host)
        port = getattr(embedder, "port", config.embedding.lm_studio_port)

        with httpx.Client(timeout=3.0) as client:
            r = client.get(f"http://{host}:{port}/api/v0/models")
            if r.status_code != 200:
                return {"available": False, "http_status": r.status_code}

            models = r.json().get("data", [])
            loaded = [
                {"id": m.get("id"), "type": m.get("type")}
                for m in models
                if m.get("state") == "loaded"
            ]
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
            return {
                "status": "error",
                "message": f"Path does not exist: {project_root}",
            }

        log_summary = get_log_summary(target_path)
        if isinstance(log_summary, str):
            return {"status": "ok", "summary": log_summary}

        errors = (
            get_recent_errors(target_path)
            if hasattr(get_recent_errors, "__call__")
            else []
        )
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
        from src.core.intelligence.health import HealthReport

        target_path = self.resolve_indexer().project_path
        if project_root:
            target_path = Path(project_root).resolve()
            if not target_path.exists():
                return {
                    "status": "error",
                    "message": f"Path does not exist: {project_root}",
                }

        report = HealthReport(
            project_path=target_path,
            indexer=self.resolve_indexer(),
            symbol_index=self.resolve_symbol_index(),
            embedder=self.resolve_embedder(),
        )
        result = report.run_full_diagnostic()
        return result


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
        except Exception as _e:
            logger.warning("exception", exc_info=True)
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
    "ReadLiveFileTool",
]
