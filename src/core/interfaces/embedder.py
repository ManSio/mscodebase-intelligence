"""
IEmbedder — абстрактный контракт для эмбеддера.

Позволяет подменять реализацию (ONNX, OpenVINO, LM Studio)
без изменения core-логики. Все реализации — в providers/embedder/.
"""

from abc import ABC, abstractmethod
from typing import List

__all__ = [
    "IEmbedder",
]
class IEmbedder(ABC):
    """Интерфейс эмбеддера (векторизация текста)."""

    @abstractmethod
    def embed(self, text: str, is_query: bool = False) -> List[float]:
        """Вектор для одного текста."""
        ...

    @abstractmethod
    def embed_batch(
        self, texts: List[str], is_query: bool = False
    ) -> List[List[float]]:
        """Векторы для нескольких текстов."""
        ...

    def get_embedding_dim(self) -> int:
        """Размерность вектора (768 для E5-base, 1024 для BGE-M3)."""
        raise NotImplementedError

    def get_mode(self) -> str:
        """Текущий режим: onnx, lm_studio, ollama, fallback."""
        raise NotImplementedError
