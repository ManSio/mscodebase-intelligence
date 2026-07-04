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


def _indexer_factory_from_services(services: ServiceCollection):
    """Извлекает сохранённую factory для Indexer из services."""
    for key in services.list_registered():
        if key.__name__ == "_IndexerFactory":
            return services.resolve(key)
    raise RuntimeError("IndexerFactory не зарегистрирована в DI")


class _IndexerFactoryKey:
    """Sentinel-ключ для IndexerFactory в DI."""
    pass


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

    def resolve_indexer(self, explicit_project_root: Optional[str] = None) -> Any:
        """Получает per-project Indexer для текущего запроса.

        Заменяет старое services.resolve(Indexer) для multi-window.
        """
        return resolve_indexer_for_request(
            self._services,
            explicit_project_root=explicit_project_root,
        )

    def require_index(self, explicit_project_root: Optional[str] = None):
        """Проверяет, что индекс готов. Бросает IndexNotReadyError если пуст."""
        indexer = self.resolve_indexer(explicit_project_root)
        status = indexer.get_status()
        if status.get("total_chunks", 0) == 0:
            raise IndexNotReadyError(
                detail="Run index_project_dir() to initialize the vector index"
            )


__all__ = ["MCPTool", "resolve_indexer_for_request"]
