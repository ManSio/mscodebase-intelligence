"""Базовый класс для MCP-инструментов с DI и ErrorBoundary.

Все инструменты наследуют MCPTool и получают зависимости через конструктор.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import ToolError


class MCPTool(ABC):
    """Базовый класс для всех MCP-инструментов.

    Каждый инструмент:
    - Получает зависимости через self._services (DI)
    - Имеет единый интерфейс execute()
    - Может проверять готовность индекса через require_index()
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

    def require_index(self):
        """Проверяет, что индекс готов. Бросает IndexNotReadyError если пуст."""
        from src.core.indexer import Indexer
        from src.core.error_handler import IndexNotReadyError

        indexer = self._services.resolve(Indexer)
        status = indexer.get_status()
        if status.get("total_chunks", 0) == 0:
            raise IndexNotReadyError(
                detail="Run index_project_dir() to initialize the vector index"
            )


__all__ = ["MCPTool"]
