"""
GraphRAG Query Engine — навигация по графу знаний.

Позволяет отвечать на сложные вопросы:
- "Какие файлы сломаются если изменить X?"
- "Какой код связан с этой фичей?"
- "Покажи цепочку зависимостей"
- "Какие тесты запустить после изменения?"
"""

import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger("graph_rag")


class GraphRAGQueryEngine:
    """Движок запросов к графу знаний."""

    def __init__(self, project_path: Path, symbol_index=None, commit_memory=None):
        self.project_path = project_path
        self.symbol_index = symbol_index
        self.commit_memory = commit_memory
        self._graph: Dict[str, Dict[str, float]] = {}
        self._file_symbols: Dict[str, Set[str]] = {}
        self._symbol_files: Dict[str, str] = {}
        self._graph_built = False

    def _ensure_graph(self):
        """Ленивое построение графа при первом запросе."""
        if not self._graph_built:
            self.build_graph()
            self._graph_built = True

    def build_graph(self) -> Dict:
        """Строит граф знаний из всех источников."""
        graph = {
            "nodes": [],
            "edges": [],
            "stats": {},
        }

        # Add file nodes
        if self.symbol_index:
            try:
                repo_map = self.symbol_index.get_repo_map(str(self.project_path))
                if repo_map:
                    for file_path, symbols in repo_map.get("symbols_by_file", {}).items():
                        graph["nodes"].append({
                            "type": "file",
                            "id": file_path,
                            "symbols": len(symbols),
                        })
                        self._file_symbols[file_path] = set(symbols)
                        for sym in symbols:
                            self._symbol_files[sym] = file_path
            except Exception as e:
                logger.warning(f"Failed to build graph from symbol_index: {e}")

        graph["stats"] = {
            "total_nodes": len(graph["nodes"]),
            "total_files": len(self._file_symbols),
            "total_symbols": len(self._symbol_files),
        }

        return graph

    def query_impact(self, symbol_name: str, depth: int = 2) -> Dict:
        """Находит что затронет изменение символа."""
        self._ensure_graph()
        result = {
            "symbol": symbol_name,
            "direct_impact": [],
            "transitive_impact": [],
            "tests_to_run": [],
            "risk_score": 0,
        }

        if not self.symbol_index:
            return result

        try:
            impact = self.symbol_index.get_impact_analysis(symbol_name, depth=depth)
            result["direct_impact"] = impact.get("affected_files", [])[:10]
            result["transitive_impact"] = impact.get("affected_files", [])[10:]
            result["risk_score"] = impact.get("risk_score", 0)

            # Find related tests
            result["tests_to_run"] = self._find_related_tests(result["direct_impact"])

        except Exception as e:
            logger.error(f"Impact query failed: {e}")

        return result

    def query_feature(self, feature_name: str) -> Dict:
        """Находит весь код связанный с фичей."""
        self._ensure_graph()
        result = {
            "feature": feature_name,
            "files": [],
            "symbols": [],
            "related_commits": [],
        }

        # Search in symbols
        if self.symbol_index:
            try:
                symbols = self.symbol_index.search_symbols(feature_name)
                result["symbols"] = symbols[:20]

                # Get files for symbols
                for sym_info in symbols[:10]:
                    file_path = sym_info.get("file")
                    if file_path and file_path not in result["files"]:
                        result["files"].append(file_path)
            except Exception as e:
                logger.warning(f"Symbol search failed: {e}")

        # Search in commits
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
        self._ensure_graph()
        result = {
            "file": file_path,
            "depends_on": [],
            "depended_by": [],
            "cochange_files": [],
        }

        if not self.symbol_index:
            return result

        try:
            # Get symbols in this file
            symbols = self.symbol_index.get_symbols_in_file(file_path)

            # Find what these symbols call
            for sym in symbols[:10]:
                try:
                    call_chain = self.symbol_index.get_call_chain(sym, direction="down")
                    if call_chain and "callees" in call_chain:
                        for callee in call_chain["callees"]:
                            callee_file = self._symbol_files.get(callee)
                            if callee_file and callee_file != file_path:
                                result["depends_on"].append(callee_file)
                except Exception:
                    pass

            # Find who calls these symbols
            for sym in symbols[:10]:
                try:
                    call_chain = self.symbol_index.get_call_chain(sym, direction="up")
                    if call_chain and "callers" in call_chain:
                        for caller in call_chain["callers"]:
                            caller_file = self._symbol_files.get(caller)
                            if caller_file and caller_file != file_path:
                                result["depended_by"].append(caller_file)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Dependency query failed: {e}")

        # Deduplicate
        result["depends_on"] = list(set(result["depends_on"]))[:10]
        result["depended_by"] = list(set(result["depended_by"]))[:10]

        return result

    def query_tests(self, file_path: str) -> List[str]:
        """Находит тесты связанные с файлом."""
        return self._find_related_tests([file_path])

    def _find_related_tests(self, file_paths: List[str]) -> List[str]:
        """Находит тесты для списка файлов."""
        tests = []
        test_dir = self.project_path / "tests"

        if not test_dir.exists():
            return tests

        for file_path in file_paths:
            # Get file name without extension
            stem = Path(file_path).stem

            # Look for test files
            for test_file in test_dir.glob("test_*.py"):
                if stem in test_file.name:
                    tests.append(str(test_file.relative_to(self.project_path)))

        return list(set(tests))[:10]

    def query_hotspots(self, min_changes: int = 3) -> List[Dict]:
        """Находит горячие точки — файлы с частыми изменениями."""
        if not self.commit_memory:
            return []

        try:
            return self.commit_memory.get_hotspots(min_changes=min_changes)
        except Exception as e:
            logger.error(f"Hotspots query failed: {e}")
            return []

    def query_similar_bugs(self, error_message: str) -> List[Dict]:
        """Находит похожие баги из истории."""
        if not self.commit_memory:
            return []

        try:
            return self.commit_memory.find_similar_bugs(error_message)
        except Exception as e:
            logger.error(f"Similar bugs query failed: {e}")
            return []


def get_query_engine(project_path: Path, symbol_index=None, commit_memory=None) -> GraphRAGQueryEngine:
    """Возвращает глобальный QueryEngine."""
    return GraphRAGQueryEngine(project_path, symbol_index, commit_memory)
