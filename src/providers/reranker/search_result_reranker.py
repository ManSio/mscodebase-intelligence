"""SearchResultReranker — BM25 + dense комбинация результатов поиска.

Устаревший реранкер. Для нового функционала используйте MultiProviderReranker.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class SearchResultReranker:
    """Устаревший реранкер (BM25 + dense комбинация).

    Сохранён для обратной совместимости.
    Для нового функционала используйте MultiProviderReranker.
    """

    def __init__(self, bm25_weight: float = 0.3, dense_weight: float = 0.7):
        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight
        self._is_initialized = False

    def rerank_results(
        self,
        query: str,
        bm25_results: List[Dict[str, Any]],
        dense_results: List[Dict[str, Any]],
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Переранжирует результаты поиска, комбинируя BM25 и векторные скоры."""
        if not bm25_results and not dense_results:
            return []

        results_map = self._create_results_map(bm25_results, dense_results)
        combined_results = self._combine_scores(results_map, query)
        sorted_results = sorted(
            combined_results.items(), key=lambda x: x[1]["final_score"], reverse=True
        )[:limit]

        return [result for _, result in sorted_results]

    def _create_results_map(
        self, bm25_results: List[Dict[str, Any]], dense_results: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        results_map = {}
        for i, result in enumerate(bm25_results):
            key = self._create_result_key(result)
            results_map[key] = {
                "text": result["text"],
                "metadata": result["metadata"],
                "bm25_score": 1.0 - (i / len(bm25_results)) if bm25_results else 0,
                "dense_score": 0.0,
                "source": "bm25",
            }
        for i, result in enumerate(dense_results):
            if "error" in result:
                continue
            key = self._create_result_key(result)
            if key in results_map:
                results_map[key]["dense_score"] = 1.0 - (i / len(dense_results))
            else:
                results_map[key] = {
                    "text": result["text"],
                    "metadata": result["metadata"],
                    "bm25_score": 0.0,
                    "dense_score": 1.0 - (i / len(dense_results)),
                    "source": "dense",
                }
        return results_map

    @staticmethod
    def _create_result_key(result: Dict[str, Any]) -> str:
        file_path = result["metadata"]["file"]
        chunk_index = result["metadata"]["chunk_index"]
        return f"{file_path}:{chunk_index}"

    def _combine_scores(
        self, results_map: Dict[str, Dict[str, Any]], query: str
    ) -> Dict[str, Dict[str, Any]]:
        combined = {}
        for key, result in results_map.items():
            final_score = (
                result["bm25_score"] * self.bm25_weight
                + result["dense_score"] * self.dense_weight
            )
            relevance_factor = self._calculate_relevance_factor(query, result)
            final_score *= relevance_factor
            result["final_score"] = final_score
            result["query_relevance"] = relevance_factor
            combined[key] = result
        return combined

    @staticmethod
    def _calculate_relevance_factor(query: str, result: Dict[str, Any]) -> float:
        query_words = set(query.lower().split())
        result_text = result["text"].lower()
        exact_matches = sum(1 for word in query_words if word in result_text)
        if exact_matches > 0:
            return 1.5
        long_words = [w for w in query_words if len(w) >= 3]
        long_matches = sum(1 for word in long_words if word in result_text)
        if long_matches > 0:
            return 1.2
        return 1.0

    def update_weights(self, bm25_weight: float, dense_weight: float):
        total_weight = bm25_weight + dense_weight
        if total_weight > 0:
            self.bm25_weight = bm25_weight / total_weight
            self.dense_weight = dense_weight / total_weight
        else:
            self.bm25_weight = 0.5
            self.dense_weight = 0.5
        logger.info(
            f"Обновлены веса реранкера: BM25={self.bm25_weight:.2f}, Dense={self.dense_weight:.2f}"
        )

    def get_stats(self) -> Dict[str, Any]:
        return {
            "bm25_weight": self.bm25_weight,
            "dense_weight": self.dense_weight,
            "is_initialized": self._is_initialized,
        }


__all__ = ["SearchResultReranker"]
