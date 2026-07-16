"""Инструменты индексации: notify_change, index_project_dir, index_health.

ИСПРАВЛЕНО (v2):
- notify_change использует DebounceBatch вместо searcher.reindex() на каждый файл
- Rate Limiter: максимум 10 notify_change в секунду
- CircuitBreaker для операций индексации
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import ToolError, error_boundary
from src.core.rate_limiter import SlidingWindowRateLimiter
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.indexing_tools")


class NotifyChangeTool(MCPTool):
    """notify_change — обновляет индекс одного файла через LSP VFS или диск.

    ★ ИСПРАВЛЕНО: вместо searcher.reindex() на каждый файл используется
    DebounceBatch. BM25 перестраивается пакетно (раз в 500ms или при 100 файлах).
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="notify_change")
        # Multi-window (INC-6BCB-v2): DebounceBatch больше НЕ singleton в DI.
        # Per-project batch создаётся внутри Indexer-фабрики и доступен
        # как indexer.bm25_batch. Берём per-call через resolve_indexer().
        self.rate_limiter = services.resolve(SlidingWindowRateLimiter)

    @error_boundary("notify_change", timeout_ms=30000)
    async def execute(
        self,
        file_path: str,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        # ★ RATE LIMIT: максимум 10 notify_change в секунду ★
        # acquire() теперь sync (threading.Lock) — см. INC-53EC / REFC-03.
        if not self.rate_limiter.acquire("notify_change", max_per_sec=10.0):
            return (
                "⚠️ Rate limit exceeded: too many notify_change calls. Wait and retry."
            )

        project_root = self._get_project_root()
        rel_path = self._resolve_and_validate_path(file_path, project_root)
        # Multi-window (INC-6BCB): per-project Indexer.
        indexer = self.resolve_indexer(explicit_project_root=str(project_root))

        # Получаем контент из LSP VFS или с диска
        content, source = await self._get_content(rel_path)

        # Индексируем один файл
        success = indexer._index_single_file(
            rel_path,
            str(rel_path.relative_to(project_root)),
            content=content,
            source=source,
        )

        if success:
            rel_path_str = str(rel_path.relative_to(project_root))
            # Multi-window (INC-6BCB-v2): per-project batch.
            batch = getattr(indexer, "bm25_batch", None)
            if batch is not None:
                await batch.add(rel_path_str)
            elif indexer.searcher:
                # Fallback: per-project batch не создан (например, Indexer
                # был создан до фикса) — синхронный reindex.
                indexer.searcher.reindex()
            # INC-6BCB-v3: project header — пользователь видит ГДЕ индексирует.
            return (
                f"✅ Index updated: {rel_path_str} (source: {source})\n"
                f"{self._project_header()}"
            )

        return (
            f"⏭️ No changes: {str(rel_path.relative_to(project_root))}\n"
            f"{self._project_header()}"
        )

    def _get_project_root(self) -> Path:
        """Определяет корень проекта (multi-window: из DI default)."""
        from src.core.di_container import ProjectRootKey

        return self._services.resolve(ProjectRootKey)

    def _resolve_and_validate_path(self, file_path: str, project_root: Path) -> Path:
        """Проверяет и резолвит путь."""
        raw_path = Path(file_path)
        if raw_path.is_absolute():
            path = raw_path.resolve()
        else:
            path = (project_root / raw_path).resolve()

        if not path.exists():
            raise ToolError(
                message=f"File does not exist: {file_path}",
                status="error",
                detail="Check the path and try again",
            )

        try:
            path.relative_to(project_root)
        except ValueError:
            raise ToolError(
                message=f"File outside project: {file_path}",
                status="error",
            )

        return path

    async def _get_content(self, path: Path) -> tuple[Optional[str], str]:
        """Пытается получить текст из LSP VFS, fallback — диск."""
        content = None

        # Пытаемся получить из LSP VFS (актуальная версия из памяти Zed)
        try:
            from src.hybrid_server import server as lsp_server

            if lsp_server and hasattr(lsp_server, "workspace"):
                uri = f"file:///{str(path).replace(chr(92), '/')}"
                doc = lsp_server.workspace.get_document(uri)
                if doc and hasattr(doc, "source"):
                    content = doc.source
                    logger.debug(
                        f"notify_change: got from LSP VFS ({len(content)} chars)"
                    )
        except Exception:
            pass  # LSP VFS недоступен — ок, читаем с диска

        # Если есть shared_indexer (hybrid mode) — используем через него
        if content is not None:
            try:
                from src.hybrid_server import shared_indexer

                if shared_indexer._initialized:
                    await shared_indexer.index_file(path, content)
                    return content, "lsp_vfs_hybrid"
            except (ImportError, Exception):
                pass

            return content, "lsp_vfs"

        return None, "filesystem"


class IndexProjectDirTool(MCPTool):
    """index_project_dir — полная индексация проекта."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="index_project_dir")
        # Multi-window: Indexer per-call.

    @error_boundary("index_project_dir", timeout_ms=300000)
    async def execute(
        self,
        path: str,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        target_path = Path(path).resolve()
        if not target_path.exists():
            return f"❌ Path does not exist: {path}"

        # INC-6BCB-v3: self-indexing guard в resolve_indexer уже заблокировал бы
        # эту операцию, но даём более понятное сообщение ДО создания Indexer.
        # Используем SystemArtifacts (Layer 1) — не нужно импортировать
        # lsp_project_bridge или mcp.server напрямую.
        from src.core.system_artifacts import SystemArtifacts

        if SystemArtifacts.is_system_path(target_path):
            return (
                f"❌ Refusing to index system directory: {target_path}\n"
                f"  Это self-indexing. Открой проект явно."
            )
        try:
            if target_path.resolve() == _ext_root.resolve():
                return (
                    f"❌ Refusing to index extension's own directory: {target_path}\n"
                    f"  Это исходники самого MCP/LSP. Открой проект явно."
                )
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        # Запускаем полную индексацию в фоновом потоке
        logger.info(f"🔄 Starting full indexing for {target_path.name}...")

        # Multi-window: получаем per-project Indexer (lazy создаётся
        # в registry, не singleton).
        indexer = self.resolve_indexer(explicit_project_root=str(target_path))

        try:
            import asyncio

            indexed = await asyncio.to_thread(indexer.index_project, target_path)
            from datetime import datetime, timedelta

            _eta_time = (datetime.now() + timedelta(seconds=120)).strftime("%H:%M:%S")
            return (
                f"✅ Индексация завершена: {target_path.name}\n"
                f"  • Обработано файлов: {indexed}\n"
                f"  • Используйте get_index_status() для проверки состояния\n"
                f"💡 *Следующая индексация: не ранее {_eta_time}. "
                f"Запрашивай статус не чаще раза в 30с.*"
            )
        except Exception as e:
            logger.error(f"Indexing error: {e}")
            return f"❌ Ошибка индексации: {e}\n💡 *Проверь LM Studio и повтори.*"


class IndexHealthTool(MCPTool):
    """index_health — диагностика и самовосстановление индекса."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="index_health")
        # Multi-window: Indexer per-call.

    @error_boundary("index_health", timeout_ms=10000)
    async def execute(
        self,
        project_root: str = "",
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> dict:
        from src.core.indexing.index_guard import quick_health_check

        if project_root:
            target_path = Path(project_root).resolve()
        else:
            # Default: берём из DI project_root (single-window).
            from src.core.di_container import ProjectRootKey

            target_path = self._services.resolve(ProjectRootKey)
        if not target_path.exists():
            return {
                "status": "error",
                "message": f"Path does not exist: {project_root}",
            }

        # Находим путь к БД
        import hashlib

        normalized_path = str(target_path.resolve()).lower().replace("\\", "/")
        project_hash = hashlib.md5(normalized_path.encode()).hexdigest()[:8]
        project_name = target_path.name.lower()
        db_path = (
            target_path
            / ".codebase_indices"
            / "lancedb_v2"
            / f"index_{project_name}_{project_hash}.db"
        )

        if not db_path.exists():
            return {
                "status": "warning",
                "message": f"Database not found: {db_path.name}",
                "recovery_hint": "Run index_project_dir() to create",
                **self._project_metadata(),  # INC-6BCB-v3
            }

        health = quick_health_check(db_path)

        return {
            "status": "ok" if health["healthy"] else "warning",
            "table_exists": health["table_exists"],
            "row_count": health["row_count"],
            "schema_ok": health["schema_ok"],
            "symbol_index_exists": health["symbol_index_exists"],
            "healthy": health["healthy"],
            "error": health.get("error"),
            **self._project_metadata(),  # INC-6BCB-v3
        }


__all__ = [
    "NotifyChangeTool",
    "IndexProjectDirTool",
    "IndexHealthTool",
]
