"""
Интерфейсы для компонентов MSCodeBase Intelligence.

Позволяют подменять реализации (провайдеры) без изменения core-логики.
"""

from src.core.interfaces.embedder import IEmbedder

__all__ = ["IEmbedder"]
