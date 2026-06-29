"""
Auto Relation Extraction — автоматическое извлечение связей между символами и файлами.

Извлекает связи:
1. Co-change relations — файлы меняющиеся вместе
2. Call relations — вызовы между символами (из SymbolIndex)
3. Semantic relations — семантически похожие чанки
4. Bug correlation — файлы связанные через баг-фиксы

Формирует граф знаний проекта.
"""

import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("relation_extractor")


class RelationExtractor:
    """Автоматическое извлечение связей между элементами кода."""

    def __init__(self, commit_memory, symbol_index=None):
        """
        Args:
            commit_memory: Инстанс CommitMemory
            symbol_index: Инстанс SymbolIndex (опционально, для call relations)
        """
        self.commit_memory = commit_memory
        self.symbol_index = symbol_index
        self._relations: Dict[str, List[Dict]] = {}
        self._graph: Dict[str, Dict[str, float]] = {}

    def extract_all_relations(self) -> Dict[str, List[Dict]]:
        """Извлекает все типы связей.

        Returns:
            {relation_type: [relations]}
        """
        relations = {
            "cochange": self.extract_cochange_relations(),
            "bug_correlation": self.extract_bug_correlations(),
        }

        if self.symbol_index:
            relations["call_graph"] = self.extract_call_relations()

        self._relations = relations
        return relations

    def extract_cochange_relations(self, min_frequency: int = 1) -> List[Dict]:
        """Извлекает связи со-изменения файлов.

        Если два файла часто меняются в одних коммитах — они связаны.

        Args:
            min_frequency: Минимальная частота со-изменения

        Returns:
            [{source, target, weight, type}]
        """
        cochange = self.commit_memory.get_cochange_frequency()

        relations = []
        for pair_str, frequency in cochange.items():
            if frequency < min_frequency:
                continue

            parts = pair_str.split("|", 1)
            if len(parts) == 2:
                relations.append({
                    "source": parts[0],
                    "target": parts[1],
                    "weight": frequency,
                    "type": "cochange",
                })

        # Сортируем по весу
        relations.sort(key=lambda x: x["weight"], reverse=True)
        return relations

    def extract_bug_correlations(self) -> List[Dict]:
        """Извлекает связи через баг-фиксы.

        Если файлы исправлялись в одних баг-фиксах — они связаны.

        Returns:
            [{source, target, weight, type, common_bugs}]
        """
        commits = self.commit_memory._commits
        if not commits:
            self.commit_memory.fetch_commits()
            commits = self.commit_memory._commits

        # Фильтруем баг-фиксы
        bug_keywords = ['fix', 'bug', 'hotfix', 'resolve', 'error', 'crash']
        bug_commits = []

        import re
        pattern = re.compile('|'.join(bug_keywords), re.IGNORECASE)

        for commit in commits:
            message = commit.get("message", "")
            if pattern.search(message):
                bug_commits.append(commit)

        # Считаем со-изменения в баг-фиксах
        cochange = defaultdict(int)
        common_bugs = defaultdict(list)

        for commit in bug_commits:
            files = commit.get("files", [])
            message = commit.get("message", "")

            for i, f1 in enumerate(files):
                for f2 in files[i + 1:]:
                    pair = tuple(sorted([f1, f2]))
                    key = f"{pair[0]}|{pair[1]}"
                    cochange[key] += 1
                    common_bugs[key].append(message)

        relations = []
        for pair_str, frequency in cochange.items():
            parts = pair_str.split("|", 1)
            if len(parts) == 2:
                relations.append({
                    "source": parts[0],
                    "target": parts[1],
                    "weight": frequency,
                    "type": "bug_correlation",
                    "common_bugs": common_bugs[pair_str][:5],  # Топ-5 сообщений
                })

        relations.sort(key=lambda x: x["weight"], reverse=True)
        return relations

    def extract_call_relations(self) -> List[Dict]:
        """Извлекает связи вызовов из SymbolIndex.

        Returns:
            [{source, target, weight, type}]
        """
        if not self.symbol_index:
            return []

        relations = []
        try:
            # Получаем граф вызовов из SymbolIndex
            if hasattr(self.symbol_index, '_call_graph'):
                graph = self.symbol_index._call_graph
                for caller, callees in graph.items():
                    for callee in callees:
                        relations.append({
                            "source": caller,
                            "target": callee,
                            "weight": 1,
                            "type": "call",
                        })
        except Exception as e:
            logger.warning(f"Failed to extract call relations: {e}")

        return relations

    def build_knowledge_graph(self) -> Dict[str, Dict[str, float]]:
        """Строит единый граф знаний.

        Объединяет все типы связей в один взвешенный граф.

        Returns:
            {node: {neighbor: weight}}
        """
        if not self._relations:
            self.extract_all_relations()

        graph = defaultdict(lambda: defaultdict(float))

        # Добавляем все связи в граф
        for rel_type, rels in self._relations.items():
            # Веса по типу связи
            type_weights = {
                "call": 3.0,
                "cochange": 2.0,
                "bug_correlation": 2.5,
                "semantic": 1.5,
            }
            type_weight = type_weights.get(rel_type, 1.0)

            for rel in rels:
                source = rel["source"]
                target = rel["target"]
                weight = rel.get("weight", 1) * type_weight

                graph[source][target] += weight
                graph[target][source] += weight  # Неориентированный

        self._graph = dict(graph)
        return dict(graph)

    def get_related_files(self, file_path: str, max_depth: int = 1) -> List[Dict]:
        """Находит файлы связанные с данным.

        Args:
            file_path: Целевой файл
            max_depth: Глубина поиска (1 = прямые связи, 2 = через посредника)

        Returns:
            [{file, path, total_weight, relation_types}]
        """
        if not self._graph:
            self.build_knowledge_graph()

        if file_path not in self._graph:
            return []

        # Прямые связи (depth=1)
        direct = self._graph[file_path]
        related = {}

        for neighbor, weight in direct.items():
            related[neighbor] = {
                "file": neighbor,
                "path": [file_path, neighbor],
                "total_weight": weight,
                "depth": 1,
            }

        # Если нужна глубина 2 — ищем через посредников
        if max_depth >= 2:
            for intermediate in direct:
                if intermediate in self._graph:
                    for neighbor, weight in self._graph[intermediate].items():
                        if neighbor == file_path or neighbor in related:
                            continue

                        # Вес через посредник — среднее геометрическое
                        indirect_weight = (direct[intermediate] * weight) ** 0.5

                        if neighbor not in related or related[neighbor]["total_weight"] < indirect_weight:
                            related[neighbor] = {
                                "file": neighbor,
                                "path": [file_path, intermediate, neighbor],
                                "total_weight": round(indirect_weight, 2),
                                "depth": 2,
                            }

        result = sorted(related.values(), key=lambda x: x["total_weight"], reverse=True)
        return result

    def get_relation_summary(self) -> Dict:
        """Сводка по всем связям."""
        if not self._relations:
            self.extract_all_relations()

        summary = {
            "total_relations": sum(len(rels) for rels in self._relations.values()),
            "by_type": {rel_type: len(rels) for rel_type, rels in self._relations.items()},
        }

        if self._graph:
            summary["unique_nodes"] = len(self._graph)
            total_edges = sum(len(neighbors) for neighbors in self._graph.values())
            summary["total_edges"] = total_edges // 2  # Неориентированный

        return summary
