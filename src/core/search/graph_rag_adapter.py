"""GraphRAGAdapter — PropertyGraph → GraphRAGQueryEngine.

Адаптер для RAG-запросов поверх PropertyGraph + SymbolIndexAdapter.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

from src.core.graph import (
    EdgeType,
    PropertyGraph,
)
from src.core.search.graph_adapter import SymbolIndexAdapter

logger = logging.getLogger(__name__)


# GraphRAGAdapter — PropertyGraph → GraphRAGQueryEngine
# ════════════════════════════════════════════════════════════

class GraphRAGAdapter:
    """
    Адаптер PropertyGraph → интерфейс GraphRAGQueryEngine.

    Оборачивает PropertyGraph + SymbolIndexAdapter в интерфейс
    query_impact / query_feature / query_dependencies / query_tests.
    """

    def __init__(
        self,
        project_path: Path,
        graph: PropertyGraph,
        symbol_adapter: SymbolIndexAdapter,
        commit_memory=None,
    ):
        self.project_path = project_path
        self._graph = graph
        self._symbol_adapter = symbol_adapter
        self.commit_memory = commit_memory

    def query_impact(self, symbol_name: str, depth: int = 2) -> Dict:
        """Анализ влияния изменения символа."""
        result = {
            "symbol": symbol_name,
            "direct_impact": [],
            "transitive_impact": [],
            "tests_to_run": [],
            "risk_score": 0,
        }

        try:
            impact = self._symbol_adapter.get_impact_analysis(symbol_name, depth=depth)
            result["direct_impact"] = impact.get("affected_files", [])[:10]
            result["transitive_impact"] = impact.get("affected_files", [])[10:]
            result["risk_score"] = impact.get("risk_score", 0)
            result["tests_to_run"] = self._find_related_tests(result["direct_impact"])
        except Exception as e:
            logger.error(f"Impact query failed: {e}")

        return result

    def query_feature(self, feature_name: str) -> Dict:
        """Находит код, связанный с фичей."""
        result = {"feature": feature_name, "files": [], "symbols": [], "related_commits": []}

        try:
            symbols = self._symbol_adapter.search_symbols(feature_name)
            result["symbols"] = symbols[:20]
            for sym_info in symbols[:10]:
                file_path = getattr(sym_info, "file_path", None) or sym_info.file_path
                if file_path and file_path not in result["files"]:
                    result["files"].append(file_path)
        except Exception as e:
            logger.warning(f"Symbol search failed: {e}")

        if self.commit_memory:
            try:
                commits = self.commit_memory.search_commits(feature_name)
                result["related_commits"] = [
                    {"hash": c.get("hash", "")[:8], "message": c.get("message", "")}
                    for c in commits[:5]
                ]
            except Exception as e:
                logger.warning(f"Commit search failed: {e}")

        return result

    def query_dependencies(self, file_path: str, direction: str = "both") -> Dict:
        """Находит зависимости файла."""
        result = {
            "file": file_path,
            "depends_on": [],
            "depended_by": [],
            "cochange_files": [],
        }

        file_path = Path(file_path).resolve().as_posix()
        try:
            nodes = self._graph.find_nodes(file_path=file_path)
            depends_on = set()
            depended_by = set()

            for node in nodes:
                # Outgoing CALLS → depends_on
                for neighbor, edge, _depth in self._graph.get_neighbors(
                    node.qualified_name, edge_type=EdgeType.CALLS, direction="outgoing"
                ):
                    if neighbor.file_path and neighbor.file_path != file_path:
                        depends_on.add(neighbor.file_path)

                # Incoming CALLS → depended_by
                for neighbor, edge, _depth in self._graph.get_neighbors(
                    node.qualified_name, edge_type=EdgeType.CALLS, direction="incoming"
                ):
                    if neighbor.file_path and neighbor.file_path != file_path:
                        depended_by.add(neighbor.file_path)

            result["depends_on"] = list(depends_on)[:10]
            result["depended_by"] = list(depended_by)[:10]

        except Exception as e:
            logger.error(f"Dependency query failed: {e}")

        return result

    def query_tests(self, file_path: str) -> List[str]:
        """Находит тесты, связанные с файлом."""
        return self._find_related_tests([file_path])

    def _find_related_tests(self, file_paths: List[str]) -> List[str]:
        """Находит тесты для списка файлов."""
        tests = []
        test_dir = self.project_path / "tests"
        if not test_dir.exists():
            return tests

        for fpath in file_paths:
            stem = Path(fpath).stem
            for test_file in test_dir.glob("test_*.py"):
                if stem in test_file.name:
                    tests.append(str(test_file.relative_to(self.project_path)))

        return list(set(tests))[:10]

    def query_hotspots(self, min_changes: int = 3) -> List[Dict]:
        """Горячие точки из commit_memory."""
        if not self.commit_memory:
            return []
        try:
            return self.commit_memory.get_hotspots(min_changes=min_changes)
        except Exception as e:
            logger.error(f"Hotspots query failed: {e}")
            return []

    def query_similar_bugs(self, error_message: str) -> List[Dict]:
        """Поиск похожих багов."""
        if not self.commit_memory:
            return []
        try:
            return self.commit_memory.find_similar_bugs(error_message)
        except Exception as e:
            logger.error(f"Similar bugs query failed: {e}")
            return []


# ════════════════════════════════════════════════════════════
