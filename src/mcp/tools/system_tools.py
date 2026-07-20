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
        # lsp_main удалён — LSP-мост больше не используется
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
    """read_live_file — чтение файла с диска с поддержкой диапазона строк.

    LSP-мост удалён из проекта — читаем только с диска.
    Поддерживает:
    - Частичное чтение (start_line / end_line)
    - Preview без диапазона (первые 50 строк, truncated=true)
    - Детект бинарных файлов (null-байты в первых 512 байтах)
    - Path traversal guard (§5.12 AGENTS.md)
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="read_live_file")

    @error_boundary("read_live_file", timeout_ms=3000)
    async def execute(
        self,
        absolute_path: str = "",
        file_path: str = "",
        start_line: int = 0,
        end_line: int = 0,
    ) -> dict:
        """
        Args:
            absolute_path: Абсолютный путь к файлу (Windows формат).
            file_path: Относительный путь от корня проекта.
            start_line: Первая строка (1-indexed, 0 = сначала).
            end_line: Последняя строка (включительно, 0 = до конца).
        """
        # ─── 1. Определяем полный путь с Path traversal guard (§5.12) ───
        if absolute_path:
            target = Path(absolute_path).resolve()
        elif file_path:
            project_root = self.resolve_indexer().project_path
            resolved = (project_root / file_path).resolve()
            if not resolved.is_relative_to(project_root.resolve()):
                return {
                    "status": "error",
                    "message": "Path traversal detected",
                }
            target = resolved
        else:
            return {"status": "error", "message": "Provide absolute_path or file_path"}

        if not target.exists():
            return {"status": "error", "message": f"File not found: {target}"}

        # ─── 2. Детект бинарных файлов ───
        try:
            with open(target, "rb") as f:
                header = f.read(512)
            if b"\x00" in header:
                mime = _guess_mime(target)
                return {
                    "status": "error",
                    "binary": True,
                    "message": f"Binary file ({mime}): {target.name}",
                    "path": str(target),
                    "size": target.stat().st_size,
                }
        except Exception as e:
            return {"status": "error", "message": f"Cannot read file header: {e}"}

        # ─── 3. Читаем файл ───
        encoding = "utf-8"
        try:
            content = target.read_text(encoding=encoding)
        except UnicodeDecodeError:
            # Fallback: пробуем chardet, иначе latin-1
            try:
                import chardet
                raw = target.read_bytes()
                detected = chardet.detect(raw)
                encoding = detected.get("encoding", "latin-1") or "latin-1"
                content = raw.decode(encoding, errors="replace")
            except ImportError:
                encoding = "latin-1"
                content = target.read_text(encoding=encoding, errors="replace")
        except Exception as e:
            return {"status": "error", "message": f"Cannot read file: {e}"}

        # ─── 4. Обрезаем по диапазону ───
        lines = content.split("\n")
        total_lines = len(lines)

        has_range = bool(start_line) or bool(end_line)
        if not has_range:
            # Без диапазона — preview 50 строк
            display_lines = lines[:50]
            truncated = total_lines > 50
        else:
            # start_line: 0 = сначала, иначе 1-indexed
            start_idx = 0 if start_line == 0 else max(0, start_line - 1)
            # end_line: 0 = до конца, иначе включительно
            end_idx = total_lines if end_line == 0 else min(total_lines, end_line)
            if start_idx >= total_lines:
                return {
                    "status": "ok",
                    "path": str(target),
                    "source": "disk",
                    "encoding": encoding,
                    "total_lines": total_lines,
                    "total_chars": len(content),
                    "content": "",
                    "warning": f"start_line={start_line} exceeds file length ({total_lines} lines)",
                    "range": {"start": start_line, "end": end_line},
                }
            if start_idx >= end_idx:
                return {
                    "status": "ok",
                    "path": str(target),
                    "source": "disk",
                    "encoding": encoding,
                    "total_lines": total_lines,
                    "total_chars": len(content),
                    "content": "",
                    "warning": f"start_line={start_line} > end_line={end_line}",
                    "range": {"start": start_line, "end": end_line},
                }
            display_lines = lines[start_idx:end_idx]
            truncated = end_idx < total_lines

        result_content = "\n".join(display_lines)
        return {
            "status": "ok",
            "path": str(target),
            "source": "disk",
            "encoding": encoding,
            "total_lines": total_lines,
            "total_chars": len(content),
            "content": result_content,
            "truncated": truncated,
        }


def _guess_mime(path: Path) -> str:
    """Простое определение MIME-типа по расширению."""
    ext = path.suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".pdf": "application/pdf",
        ".zip": "application/zip", ".gz": "application/gzip", ".tar": "application/x-tar",
        ".exe": "application/x-msdownload", ".dll": "application/x-msdownload",
        ".o": "application/x-object", ".so": "application/x-sharedlib",
        ".pyc": "application/x-python-bytecode",
        ".whl": "application/x-wheel+zip",
        ".gguf": "application/x-gguf",
        ".bin": "application/octet-stream",
        ".db": "application/octet-stream", ".sqlite": "application/x-sqlite3",
    }
    return mime_map.get(ext, "application/octet-stream")


__all__ = [
    "GetIndexStatusTool",
    "GetIndexProgressTool",
    "GetIndexTimelineTool",
    "WatcherStatusTool",
    "GetLogsTool",
    "GetHealthReportTool",
    "ReadLiveFileTool",
]
