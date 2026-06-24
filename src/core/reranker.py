"""
Реранкер результатов поиска для улучшения релевантности контекста.
Использует легковесные модели для переранжирования результатов BM25 + Dense поиска.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class SearchResultReranker:
    """Реранкер результатов поиска, комбинирующий BM25 и векторные скоры."""

    def __init__(self, bm25_weight: float = 0.3, dense_weight: float = 0.7):
        """
        Инициализирует реранкер.

        Args:
            bm25_weight: Вес BM25 скоров (0.0 - 1.0)
            dense_weight: Вес векторных скоров (0.0 - 1.0)
        """
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
        """
        Переранживает результаты поиска, комбинируя BM25 и векторные скоры.

        Args:
            query: Исходный запрос пользователя
            bm25_results: Результаты BM25 поиска
            dense_results: Результаты векторного поиска
            limit: Максимальное количество результатов для возврата

        Returns:
            Переранжированные результаты, отсортированные по релевантности
        """
        if not bm25_results and not dense_results:
            return []

        # Создаем карту результатов для комбинирования
        results_map = self._create_results_map(bm25_results, dense_results)

        # Комбинируем скоры
        combined_results = self._combine_scores(results_map, query)

        # Сортируем и ограничиваем
        sorted_results = sorted(
            combined_results.items(), key=lambda x: x[1]["final_score"], reverse=True
        )[:limit]

        return [result for _, result in sorted_results]

    def _create_results_map(
        self, bm25_results: List[Dict[str, Any]], dense_results: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Создает карту результатов с уникальными ключами."""
        results_map = {}

        # BM25 результаты
        for i, result in enumerate(bm25_results):
            key = self._create_result_key(result)
            results_map[key] = {
                "text": result["text"],
                "metadata": result["metadata"],
                "bm25_score": 1.0 - (i / len(bm25_results)) if bm25_results else 0,
                "dense_score": 0.0,
                "source": "bm25",
            }

        # Dense результаты
        for i, result in enumerate(dense_results):
            if "error" in result:
                continue

            key = self._create_result_key(result)
            if key in results_map:
                # Обновляем существующую запись
                results_map[key]["dense_score"] = 1.0 - (i / len(dense_results))
            else:
                # Создаем новую запись
                results_map[key] = {
                    "text": result["text"],
                    "metadata": result["metadata"],
                    "bm25_score": 0.0,
                    "dense_score": 1.0 - (i / len(dense_results)),
                    "source": "dense",
                }

        return results_map

    def _create_result_key(self, result: Dict[str, Any]) -> str:
        """Создает уникальный ключ для результата на основе его метаданных."""
        file_path = result["metadata"]["file"]
        chunk_index = result["metadata"]["chunk_index"]
        return f"{file_path}:{chunk_index}"

    def _combine_scores(
        self, results_map: Dict[str, Dict[str, Any]], query: str
    ) -> Dict[str, Dict[str, Any]]:
        """Комбинирует BM25 и векторные скоры."""
        combined = {}

        for key, result in results_map.items():
            # Базовый комбинированный скор
            final_score = (
                result["bm25_score"] * self.bm25_weight
                + result["dense_score"] * self.dense_weight
            )

            # Применяем фактор релевантности на основе запроса
            relevance_factor = self._calculate_relevance_factor(query, result)
            final_score *= relevance_factor

            # Добавляем дополнительные поля для отладки
            result["final_score"] = final_score
            result["query_relevance"] = relevance_factor

            combined[key] = result

        return combined

    def _calculate_relevance_factor(self, query: str, result: Dict[str, Any]) -> float:
        """
        Вычисляет фактор релевантности на основе запроса и результата.

        Args:
            query: Исходный запрос
            result: Результат поиска

        Returns:
            Фактор релевантности (0.5 - 1.5)
        """
        query_words = set(query.lower().split())
        result_text = result["text"].lower()

        # Проверяем точные совпадения слов
        exact_matches = sum(1 for word in query_words if word in result_text)
        if exact_matches > 0:
            return 1.5  # Высокая релевантность для точных совпадений

        # Проверяем длинные совпадения (3+ символов)
        long_words = [w for w in query_words if len(w) >= 3]
        long_matches = sum(1 for word in long_words if word in result_text)
        if long_matches > 0:
            return 1.2  # Средняя релевантность для длинных слов

        # Проверяем наличие специальных терминов (технических терминов, имен функций и т.д.)
        if self._contains_technical_terms(result_text):
            return 1.3

        # Базовый фактор релевантности
        return 1.0

    def _contains_technical_terms(self, text: str) -> bool:
        """Проверяет, содержит ли текст технические термины."""
        technical_patterns = [
            r"def ",
            r"class ",
            r"import ",
            r"from ",
            r"function ",
            r"#",
            r"//",
            r"/*",
            r"*/",
            r"@",
            r"<",
            r">",
            r"\{",
            r"\}",
            r"\(",
            r"\)",
            r"\[",
            r"\]",
            r"\.",
            r"\,",
            r";",
            r":",
            r"=",
            r"==",
            r"!=",
            r"\+",
            r"-",
            r"\*",
            r"/",
            r"%",
            r"\^",
        ]

        import re

        for pattern in technical_patterns:
            if re.search(pattern, text):
                return True

        return False

    def update_weights(self, bm25_weight: float, dense_weight: float):
        """Обновляет веса BM25 и векторных скоров."""
        # Нормализуем веса
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
        """Возвращает статистику реранкера."""
        return {
            "bm25_weight": self.bm25_weight,
            "dense_weight": self.dense_weight,
            "is_initialized": self._is_initialized,
        }
