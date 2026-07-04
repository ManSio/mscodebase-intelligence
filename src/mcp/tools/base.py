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


def resolve_indexer_for_request(
    services: ServiceCollection,
    explicit_project_root: Optional[str] = None,
) -> Any:
    """Резолвит Indexer для текущего MCP-запроса с учётом multi-window.

    Приоритет project_path:
    1) explicit_project_root (из kwargs инструмента)
    2) resolve_project_root() (PROJECT_PATH env → bridge → CWD → ext_root)
    3) fallback: default project_path из DI

    Args:
        services: ServiceCollection.
        explicit_project_root: project_path из аргументов вызова.

    Returns:
        Indexer (singleton per project_path, из ProjectIndexerRegistry).
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
        except Exception:
            pass
        try:
            from src.core.di_container import ProjectRootKey
            return self._services.resolve(ProjectRootKey)
        except Exception:
            return None

    def require_index(self, explicit_project_root: Optional[str] = None):
        """Проверяет, что индекс готов. Бросает IndexNotReadyError если пуст."""
        indexer = self.resolve_indexer(explicit_project_root)
        status = indexer.get_status()
        if status.get("total_chunks", 0) == 0:
            raise IndexNotReadyError(
                detail="Run index_project_dir() to initialize the vector index"
            )


__all__ = ["MCPTool", "resolve_indexer_for_request"]
