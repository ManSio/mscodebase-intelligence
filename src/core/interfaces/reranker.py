"""Интерфейс реранкера для MSCodeBase Intelligence."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class IReranker(ABC):
    """Абстрактный реранкер результатов поиска."""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        top_n: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Реранкинг чанков по релевантности к запросу.

        Args:
            query: Поисковый запрос
            chunks: Список чанков для реранкинга
            top_n: Сколько чанков вернуть (None = все)

        Returns:
            Отсортированный список чанков с обновлённым final_score
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Доступен ли реранкер (модель загружена/есть соединение)."""
        ...

    @abstractmethod
    def get_model_info(self) -> Dict[str, Any]:
        """Информация о текущей модели реранкера."""
        ...
