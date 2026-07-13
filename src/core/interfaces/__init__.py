"""
Интерфейсы для компонентов MSCodeBase Intelligence.

Позволяют подменять реализации (провайдеры) без изменения core-логики.
"""

from src.core.interfaces.embedder import IEmbedder
from src.core.interfaces.reranker import IReranker
from src.core.interfaces.searcher import ISearcher

__all__ = ["IEmbedder", "IReranker", "ISearcher"]
