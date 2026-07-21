"""CompositionAdapter — единая точка входа для всех адаптеров.

Композирует SymbolIndexAdapter + GraphRAGAdapter в единый интерфейс.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

# Forward references for type annotations
from src.core.graph import Node as _Node  # noqa: F401 — used in type annotation
from src.core.search.graph_adapter import SymbolRef as _SymbolRef  # noqa: F401 — used in type annotation

from src.core.graph import PropertyGraph
from src.core.search.graph_adapter import SymbolIndexAdapter
from src.core.search.graph_rag_adapter import GraphRAGAdapter

logger = __import__("logging").getLogger(__name__)


# CompositionAdapter — единая точка входа
# ════════════════════════════════════════════════════════════

class CompositionAdapter:
    """
    Композиционный адаптер — заменяет все три исходных сервиса одним.

    Использование:
        adapter = CompositionAdapter(project_root, graph_db_path)
        adapter.index_project(...)  # → SymbolIndexAdapter
        adapter.query_impact(...)   # → GraphRAGAdapter
        adapter.extract_relations() # → RelationExtractor (прямой вызов)
    """

    def __init__(
        self,
        project_path: Path,
        graph_db_path: Optional[Path] = None,
        commit_memory=None,
        mode: str = SymbolIndexAdapter.MODE_HYBRID,
    ):
        if graph_db_path is None:
            graph_db_path = project_path / ".codebase" / "graph.db"

        self._graph = PropertyGraph(graph_db_path)
        self._symbol_adapter = SymbolIndexAdapter(self._graph, mode=mode)
        self._graph_rag = GraphRAGAdapter(
            project_path, self._graph, self._symbol_adapter, commit_memory
        )

    @property
    def graph(self) -> PropertyGraph:
        return self._graph

    @property
    def symbol_index(self) -> SymbolIndexAdapter:
        return self._symbol_adapter

    @property
    def graph_rag(self) -> GraphRAGAdapter:
        return self._graph_rag

    # Делегирование SymbolIndex
    def add_definitions(self, file_path: str, symbols: List[Dict]) -> None:
        self._symbol_adapter.add_definitions(file_path, symbols)

    def add_references(self, file_path: str, calls: List[Dict]) -> None:
        self._symbol_adapter.add_references(file_path, calls)

    def remove_file(self, file_path: str) -> None:
        self._symbol_adapter.remove_file(file_path)

    def get_call_chain(self, symbol: str, direction: str = "both", max_depth: int = 3) -> Dict:
        return self._symbol_adapter.get_call_chain(symbol, direction, max_depth)

    def search_symbols(self, query: str, top_k: int = 10) -> List[SymbolRef]:
        return self._symbol_adapter.search_symbols(query, top_k)

    def get_impact_analysis(self, symbol: str, depth: int = 3) -> Dict:
        return self._symbol_adapter.get_impact_analysis(symbol, depth)

    def detect_dead_code(self) -> List[Node]:
        return self._graph.detect_dead_code()

    def get_graph_summary(self) -> Dict:
        return self._graph.get_graph_summary()

    def close(self):
        self._graph.close()


__all__ = [
    "SymbolIndexAdapter",
    "GraphRAGAdapter",
    "CompositionAdapter",
]
