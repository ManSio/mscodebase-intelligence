"""Базовый класс для MCP-инструментов с DI и ErrorBoundary.

Все инструменты наследуют MCPTool и получают зависимости через конструктор.

Multi-window (INC-6BCB):
  - Каждый инструмент вызывает resolve_indexer_for_request() вместо
    services.resolve(Indexer) напрямую.
  - Это обеспечивает per-project indexer из ProjectIndexerRegistry.
  - project_root определяется по приоритету:
    1) явный project_root в kwargs
    2) resolve_project_root() из MCP server
    3) fallback: project_root из DI (default)

Self-Indexing Protection (INC-6BCB-v3):
  - resolve_indexer_for_request() валидирует target path: если это
    Zed install dir или сам ext_root — бросает ToolError с понятным
    сообщением (вместо тихого индексирования мусора).
  - Каждый инструмент может вызвать _project_header() чтобы добавить
    в output строку вида "📂 Project: <path>" — пользователь сразу
    видит, ГДЕ идёт индексация.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from src.core.di_container import (
    ServiceCollection,
    IndexerFactoryKey,
)
from src.core.error_handler import ToolError, IndexNotReadyError
from src.core.project_indexer_registry import (
    ProjectIndexerRegistry,
    get_global_registry,
)


def resolve_indexer_for_intel(
    services: ServiceCollection,
    explicit_project_root: Optional[str] = None,
) -> Any:
    """Резолвит Indexer для read-only Intel tools с FALLBACK на любой валидный workspace.

    Отличие от resolve_indexer_for_request():
    - Если resolved project_path = self-indexing (_ext_root / Zed install / None),
      и в ProjectIndexerRegistry есть другие активные indexer-ы —
      выбираем первый non-self-indexing.
    - Это позволяет intel_* tools (intel_get_runtime_status, intel_get_project_memory,
      и т.п.) показывать состояние **другого** активного workspace, даже если
      default = self-indexing fallback.

    Для write-tools (search_code, index_project_dir, notify_change) — НЕ
    используется, чтобы не было silent redirect на чужой проект.

    Returns:
        Indexer (singleton per project_path). Если ВСЕ workspaces = self-indexing
        (крайне редкий случай) — возвращает default и self-indexing guard
        сработает с понятным сообщением.
    """
    from src.core.lsp_project_bridge import is_zed_install_dir
    from src.mcp.server import resolve_project_root as _rpr, _ext_root
    from src.core.di_container import ProjectRootKey, IndexerFactoryKey, ProjectIndexerRegistry
    from src.core.project_indexer_registry import ProjectIndexerRegistry as PIReg

    # 1. explicit project_root (highest priority) — bypass fallback, guard всё ещё
    #    активен на уровне resolve_indexer_for_request ниже.
    if explicit_project_root and explicit_project_root.strip():
        target = Path(explicit_project_root).resolve()
    else:
        try:
            target = _rpr()
        except Exception:
            target = services.resolve(ProjectRootKey)

    # 2. Если target — self-indexing, ищем первый non-self-indexing в registry.
    if _is_self_index_path(target):
        try:
            registry: PIReg = services.resolve(ProjectIndexerRegistry)
            with registry._meta_lock:
                # Ищем ПЕРВЫЙ non-self-indexing (по порядку создания).
                for p in registry._indexers.keys():
                    if not _is_self_index_path(p):
                        target = p
                        break
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
    # 3. Резолвим через ту же логику, но без self-indexing guard
    #    (мы уже отфильтровали self-index paths выше).
    registry: ProjectIndexerRegistry = services.resolve(ProjectIndexerRegistry)
    factory = services.resolve(IndexerFactoryKey)
    return registry.get_indexer(target, factory=factory)


def _is_self_index_path(path: Optional[Path]) -> bool:
    """Возвращает True если path — это self-indexing target (ЗАПРЕЩЕНО).

    Защита от повторения бага v2.3.0/2.3.1: когда Zed открыл свою
    директорию как worktree, MCP индексировал .exe/.dll Zed-а.

    Self-indexing targets:
    1. _ext_root (директория самого расширения — содержит src/ самого MCP/LSP)
    2. Любой Zed install dir (см. is_zed_install_dir)
    3. None (неопределённый project_path)

    Override: env var MSCODEBASE_ALLOW_SELF_INDEX=1 разрешает индексировать
    даже ext_root/Zed install (для разработки самого расширения: `python -m
    src.main` в Zed, открытом на исходниках расширения).
    """
    import os as _os
    if _os.environ.get("MSCODEBASE_ALLOW_SELF_INDEX", "").strip() in ("1", "true", "yes"):
        return False
    if path is None:
        return True
    try:
        from src.core.lsp_project_bridge import is_zed_install_dir
        if is_zed_install_dir(path):
            return True
    except ImportError:
        pass
    # Проверяем _ext_root через ту же логику, что и в server.py.
    try:
        from src.mcp.server import _ext_root
        if path.resolve() == _ext_root.resolve():
            return True
    except (ImportError, Exception):
        pass
    return False


def resolve_indexer_for_request(
    services: ServiceCollection,
    explicit_project_root: Optional[str] = None,
) -> Any:
    """Резолвит Indexer для текущего MCP-запроса с учётом multi-window.

    Приоритет project_path:
    1) explicit_project_root (из kwargs инструмента)
    2) resolve_project_root() (PROJECT_PATH env → bridge → CWD → ext_root)
    3) fallback: default project_path из DI

    Self-Indexing Protection (INC-6BCB-v3): если target path попадает
    в self-indexing targets (Zed install, ext_root, None) — бросает
    ToolError с инструкцией что делать.

    Args:
        services: ServiceCollection.
        explicit_project_root: project_path из аргументов вызова.

    Returns:
        Indexer (singleton per project_path, из ProjectIndexerRegistry).

    Raises:
        ToolError: если target — self-indexing path. Error содержит
            hint и safe alternatives (открыть правильный проект).
    """
    from src.mcp.server import resolve_project_root as _rpr
    from src.core.di_container import ProjectRootKey

    if explicit_project_root and explicit_project_root.strip():
        target = Path(explicit_project_root).resolve()
    else:
        try:
            target = _rpr()
        except Exception:
            target = services.resolve(ProjectRootKey)

    # Self-indexing guard (INC-6BCB-v3)
    if _is_self_index_path(target):
        raise ToolError(
            status="error",
            message=(
                f"Self-indexing blocked: target path is not a user project. "
                f"Resolved: {target}"
            ),
            detail=(
                "🚨 ПРОЕКТ НЕ ОПРЕДЕЛЁН. Текущий project_root = ext_root (само расширение).\n\n"
                "Причина: LSP bridge пуст — ZED_WORKTREE_ROOT не установлен на Windows,\n"
                "и LSP-сервер ещё не записал project_root в bridge-файл.\n\n"
                "Что делать:\n"
                "  1. Открой ЛЮБОЙ .py файл в твоём проекте (вкладка редактора).\n"
                "     LSP стартанёт → запишет project_root в bridge → MCP прочитает.\n"
                "  2. Или передай project_root явно в каждый инструмент.\n"
                "  3. Или установи PROJECT_PATH в .zed/settings.json проекта.\n\n"
                "Проверка: intel_get_runtime_status → bridge: None = LSP ещё не запущен."
            ),
        )

    registry: ProjectIndexerRegistry = services.resolve(ProjectIndexerRegistry)
    factory = services.resolve(IndexerFactoryKey)
    return registry.get_indexer(target, factory=factory)


class MCPTool(ABC):
    """Базовый класс для всех MCP-инструментов.

    Каждый инструмент:
    - Получает зависимости через self._services (DI)
    - Имеет единый интерфейс execute()
    - Может проверять готовность индекса через require_index()
    - Вызывает resolve_indexer_for_request() для получения per-project indexer
    """

    def __init__(self, services: ServiceCollection, *, tool_name: Optional[str] = None):
        self._services = services
        self._tool_name = tool_name or self.__class__.__name__
        # Multi-window: lazy cached Indexer. Первый resolve_indexer() создаёт,
        # последующие вызовы того же tool-а возвращают тот же instance.
        # При вызове resolve_indexer(explicit_project_root=other) — сбрасывается
        # (для cross-project tools типа IndexProjectDir).
        self._cached_indexer: Optional[Any] = None
        self._cached_indexer_path: Optional[Path] = None

    @property
    def name(self) -> str:
        """Имя инструмента (для регистрации в MCP)."""
        return self._tool_name

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """Выполняет инструмент.

        Должен возвращать dict (JSON-сериализуемый) или str.
        Ошибки выбрасываются через ToolError.
        """
        ...

    def resolve_indexer(
        self,
        explicit_project_root: Optional[str] = None,
        bypass_cache: bool = False,
    ) -> Any:
        """Получает per-project Indexer для текущего запроса.

        С кэшированием: если project_path совпадает с предыдущим вызовом,
        возвращается тот же instance (singleton per project per tool).
        При смене project_path (cross-project tool) кэш сбрасывается.

        bypass_cache=True: всегда создаёт новый resolve (для случая когда
        registry мог вытеснить Indexer из LRU).
        """
        target = self._resolve_target_path(explicit_project_root)

        if (
            not bypass_cache
            and self._cached_indexer is not None
            and self._cached_indexer_path is not None
            and self._cached_indexer_path == target
        ):
            return self._cached_indexer

        idx = resolve_indexer_for_request(
            self._services,
            explicit_project_root=str(target) if target else None,
        )
        self._cached_indexer = idx
        self._cached_indexer_path = target
        return idx

    def resolve_searcher(self, explicit_project_root: Optional[str] = None) -> Any:
        """Возвращает searcher, привязанный к текущему indexer.

        Per-project: searcher живёт в indexer (см. DI factory).
        """
        return self.resolve_indexer(explicit_project_root).searcher

    def resolve_symbol_index(self, explicit_project_root: Optional[str] = None) -> Any:
        """Возвращает per-project symbol_index (через indexer)."""
        return self.resolve_indexer(explicit_project_root)._symbol_index

    def resolve_embedder(self) -> Any:
        """Embedder шарится между всеми проектами (singleton в DI)."""
        from src.core.remote_embedder import RemoteEmbedder
        return self._services.resolve(RemoteEmbedder)

    def resolve_parser(self) -> Any:
        """CodeParser — stateless, шарится."""
        from src.core.parser import CodeParser
        return self._services.resolve(CodeParser)

    def _resolve_target_path(self, explicit_project_root: Optional[str]) -> Optional[Path]:
        """Резолвит Path для Indexer-lookup (multi-window)."""
        if explicit_project_root and explicit_project_root.strip():
            return Path(explicit_project_root).resolve()
        # Default: сначала пробуем resolve_project_root, потом DI.
        try:
            from src.mcp.server import resolve_project_root as _rpr
            return _rpr()
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        try:
            from src.core.di_container import ProjectRootKey
            return self._services.resolve(ProjectRootKey)
        except Exception:
            return None

    def _safe_resolve_indexer(self, explicit_project_root: Optional[str] = None) -> Any:
        """Резолвит Indexer с late-fallback на non-self-indexing workspace.

        INC-6BCB-v3.1: для read-only tools (get_index_status, get_index_progress,
        watcher_status, intel_*) — если default indexer = self-indexing,
        и в реестре есть non-self-indexing — возвращаем тот.

        Для write-tools (search_code, index_project_dir, notify_change) —
        используй resolve_indexer() напрямую, чтобы избежать silent redirect
        на чужой проект.

        Returns:
            Indexer (никогда None — fallback на self._cached_indexer или
            registry._indexers[next(iter)] если вообще ничего нет).
        """
        try:
            idx = self.resolve_indexer(explicit_project_root)
            from src.mcp.tools.base import _is_self_index_path
            if not _is_self_index_path(idx.project_path):
                return idx
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        # Fallback: первый non-self-indexing из реестра.
        try:
            from src.core.di_container import ProjectIndexerRegistry
            from src.core.project_indexer_registry import ProjectIndexerRegistry as PIReg
            registry = self._services.resolve(ProjectIndexerRegistry)
            with registry._meta_lock:
                for p, idx in registry._indexers.items():
                    from src.mcp.tools.base import _is_self_index_path
                    if not _is_self_index_path(p):
                        return idx
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        # Last resort: текущий (даже если self-indexing).
        try:
            return self.resolve_indexer(explicit_project_root)
        except Exception:
            raise ToolError(
                status="error",
                message="No active workspace found in registry",
                detail=(
                    "LSP didn't write project_root to bridge, AND no other "
                    "workspace is open in Zed. Open a project in Zed first."
                ),
            )

    async def require_ready_project(
        self,
        explicit_project_root: Optional[str] = None,
        timeout: float = 5.0,
    ):
        """Ожидает, пока проект не станет READY.

        Делегирует RuntimeCoordinator — единую точку принятия решения.
        Если Coordinator говорит "не готов" — поднимает ToolError
        с human-readable причиной.

        Двухстадийное ожидание:
        1. Быстрая проверка bridge (1с) — если LSP ещё не синхронизировался,
           сразу сообщаем "инициализация в процессе" вместо ожидания 5с.
        2. Полное ожидание READY (оставшиеся timeout секунд).

        Args:
            explicit_project_root: явный project_path (если None — default).
            timeout: макс. время ожидания в секундах (по умолч. 5с).

        Raises:
            ToolError: если проект не готов.
            IndexNotReadyError: если проект READY, но индекс пуст.
        """
        from src.core.runtime_coordinator import RuntimeCoordinator

        coord = RuntimeCoordinator(self._services)
        target = self._resolve_target_path(explicit_project_root)

        # Stage 1: быстрая проверка bridge (1с)
        try:
            from src.core.lsp_project_bridge import read_project_from_bridge
            _bridge = read_project_from_bridge(max_wait=1.0)
            if _bridge is None:
                logger.info(
                    f"⏳ require_ready_project({target.name}): "
                    f"Bridge ещё пуст (LSP не синхронизирован). "
                    f"Жду READY..."
                )
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        # Stage 2: полное ожидание через Coordinator
        verdict = await coord.can_execute(target, timeout=timeout)
        if not verdict:
            if verdict.reason in ("system_path", "project_resolution_failed"):
                raise ToolError(status="error", message=verdict.detail)
            raise ToolError(
                status="error",
                message=(
                    f"Project {target.name} is not ready "
                    f"({verdict.reason}, state={verdict.state}). "
                    f"Try again in a few seconds."
                ),
                detail=verdict.detail,
            )

        # Проверяем, что индекс не пуст
        try:
            indexer = self.resolve_indexer(explicit_project_root)
            status = indexer.get_status()
            if status.get("total_chunks", 0) == 0:
                raise IndexNotReadyError(
                    detail=(
                        f"Index is empty for project: {indexer.project_path}. "
                        f"Run index_project_dir() first."
                    )
                )
        except IndexNotReadyError:
            raise
        except Exception as e:
            raise ToolError(
                status="error",
                message=f"Failed to check index status: {e}",
            )

    def require_index(self, explicit_project_root: Optional[str] = None):
        """Проверяет, что индекс готов. Бросает IndexNotReadyError если пуст."""
        indexer = self.resolve_indexer(explicit_project_root)
        status = indexer.get_status()
        if status.get("total_chunks", 0) == 0:
            raise IndexNotReadyError(
                detail=(
                    f"Index is empty for project: {indexer.project_path}. "
                    f"Run index_project_dir() to initialize the vector index."
                )
            )

    def _project_header(
        self,
        explicit_project_root: Optional[str] = None,
        prefix: str = "📂 Project: ",
    ) -> str:
        """Возвращает строку вида "📂 Project: <path>" для вывода в tool output.

        Используется инструментами чтобы пользователь сразу видел,
        ГДЕ именно идёт индексация/поиск. Не выбрасывает ошибок —
        если resolve_indexer упал (например, self-indexing), возвращает
        "📂 Project: <unknown>".

        Args:
            explicit_project_root: явный project_path (если None — default).
            prefix: эмодзи/префикс перед путём. По умолчанию "📂 Project: ".

        Returns:
            Готовая строка для добавления в output.

        Example:
            >>> self._project_header()
            '📂 Project: D:\\\\Project\\\\MSCodeBase'
        """
        try:
            indexer = self.resolve_indexer(explicit_project_root)
            path = indexer.project_path
            return f"{prefix}{path}"
        except Exception:
            return f"{prefix}<unknown — indexer unavailable>"

    def _project_metadata(
        self,
        explicit_project_root: Optional[str] = None,
    ) -> dict:
        """Возвращает dict с project_path + chunks_count для tool output.

        Полезно для MCP tools, которые возвращают структурированный JSON
        (Intel layer, GraphRAG, и т.п.). Пользователь видит в ответе
        ГДЕ искали + СКОЛЬКО чанков доступно.

        Example:
            >>> self._project_metadata()
            {'project_path': 'D:\\\\Project\\\\MSCodeBase', 'total_chunks': 519}
        """
        try:
            indexer = self.resolve_indexer(explicit_project_root)
            status = indexer.get_status()
            return {
                "project_path": str(indexer.project_path),
                "db_path": str(indexer.db_path) if hasattr(indexer, "db_path") else None,
                "total_chunks": status.get("total_chunks", 0),
                "unique_files": status.get("unique_files", 0),
            }
        except Exception as e:
            return {
                "project_path": None,
                "error": str(e),
            }


__all__ = ["MCPTool", "resolve_indexer_for_request", "resolve_indexer_for_intel", "_is_self_index_path"]
