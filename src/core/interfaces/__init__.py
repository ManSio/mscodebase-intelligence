"""
Интерфейсы для компонентов MSCodeBase Intelligence.

Позволяют подменять реализации (провайдеры) без изменения core-логики.
"""

from src.core.interfaces.embedder import IEmbedder
from src.core.interfaces.reranker import IReranker
from src.core.interfaces.searcher import ISearcher
from src.core.interfaces.workspace_source import FileChangeEvent, WorkspaceSource

__all__ = ["IEmbedder", "IReranker", "ISearcher", "WorkspaceSource", "FileChangeEvent"]
