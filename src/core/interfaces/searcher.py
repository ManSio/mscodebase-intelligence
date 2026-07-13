"""Интерфейс поискового движка для MSCodeBase Intelligence."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class ISearcher(ABC):
    """Абстрактный поисковый движок."""

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int = 5,
        mode: str = "quality",
        filter_layer: Optional[str] = None,
        intent_hint: str = "auto",
    ) -> str:
        """Основной метод поиска. Возвращает Markdown-строку."""
        ...

    @abstractmethod
    def search_with_mode(
        self,
        query: str,
        mode: str = "auto",
        limit: int = 5,
        filter_layer: Optional[str] = None,
        intent_hint: str = "auto",
    ) -> Dict[str, Any]:
        """Поиск с выбором режима. Возвращает Dict с results и timing."""
        ...

    @abstractmethod
    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        filter_layer: Optional[str] = None,
        intent_hint: str = "auto",
    ) -> List[Dict[str, Any]]:
        """Гибридный поиск (BM25 + Vector + RRF)."""
        ...

    @abstractmethod
    def reindex(self) -> None:
        """Сброс BM25 индекса."""
        ...
