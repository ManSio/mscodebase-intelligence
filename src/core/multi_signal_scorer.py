"""
Multi-Signal Scorer — комбинированная оценка релевантности из нескольких сигналов.

Дополняет существующий RRF-пайплайн (BM25 + Dense + Reranker) дополнительными
сигналами:
  - API Signature Match  — совпадение сигнатуры функции (параметры, return type)
  - Graph Diffusion       — PageRank-центральность узла в графе вызовов
  - Module Proximity      — близость в иерархии модулей
  - Co-change Boost       — частота совместных изменений (из commit_memory)

Архитектура:
    Scorer.get_scores(query, candidates, property_graph) -> {chunk_id: score}
    → объединяется с существующим RRF через взвешенную сумму

Использование:
    scorer = MultiSignalScorer(property_graph)
    scores = scorer.compute(query, candidates, base_rrf_scores)
    # scores = {chunk_id: final_score} — финальный скор для ранжирования
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set

from src.core.graph import PropertyGraph

logger = logging.getLogger(__name__)


# ── Утилиты ───────────────────────────────────────────────

def _tokenize(text: str) -> Set[str]:
    """Простая токенизация для сигнатур."""
    return set(re.findall(r"[a-zA-Z_]\w*", text.lower()))


def _jaccard(a: Set[str], b: Set[str]) -> float:
    """Jaccard similarity."""
    if not a and not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union) if union else 0.0


# ── Multi-Signal Scorer ───────────────────────────────────

class MultiSignalScorer:
    """Вычисляет дополнительные сигналы релевантности для результатов поиска.

    Каждый сигнал возвращает нормализованный скор [0, 1].
    Сигналы объединяются через взвешенную сумму.

    Сигналы и их веса по умолчанию:
        api_signature:  0.25
        graph_diffusion: 0.20
        module_proximity: 0.15
        cochange_boost:  0.40

    Итоговый скор = base_rrf * (1 - signal_weight_sum) + sum(signal * weight)
    """

    DEFAULT_WEIGHTS = {
        "api_signature": 0.25,
        "graph_diffusion": 0.20,
        "module_proximity": 0.15,
        "cochange_boost": 0.40,
    }

    def __init__(
        self,
        graph: Optional[PropertyGraph] = None,
        commit_memory: Optional[Any] = None,
        weights: Optional[Dict[str, float]] = None,
    ):
        self._graph = graph
        self._commit_memory = commit_memory
        self._weights = weights or dict(self.DEFAULT_WEIGHTS)

        # Кэш PageRank (вычисляется лениво)
        self._pagerank: Optional[Dict[str, float]] = None
        self._pagerank_cache_key: Optional[str] = None

    @property
    def signal_names(self) -> List[str]:
        return list(self._weights.keys())

    def compute(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        base_rrf_scores: Dict[str, float],
    ) -> Dict[str, float]:
        """Вычисляет финальные скоры с учётом всех сигналов.

        Args:
            query: Поисковый запрос
            candidates: Список кандидатов (с полями file, symbol_name, chunk_id...)
            base_rrf_scores: {chunk_id: rrf_score} — базовые RRF скоры

        Returns:
            {chunk_id: final_score} — финальные скоры для ранжирования
        """
        if not candidates:
            return base_rrf_scores

        signal_weights = self._weights
        signal_total_weight = sum(signal_weights.values())

        if signal_total_weight == 0:
            return base_rrf_scores

        # Вычисляем каждый сигнал
        api_scores = self._compute_api_signature(query, candidates)
        diff_scores = self._compute_graph_diffusion(candidates)
        prox_scores = self._compute_module_proximity(query, candidates)
        cochange_scores = self._compute_cochange_boost(query, candidates)

        signal_maps = {
            "api_signature": api_scores,
            "graph_diffusion": diff_scores,
            "module_proximity": prox_scores,
            "cochange_boost": cochange_scores,
        }

        # Объединяем
        final_scores: Dict[str, float] = {}

        for chunk in candidates:
            cid = self._chunk_id(chunk)

            # Базовый RRF скор
            base = base_rrf_scores.get(cid, 0.0)

            # Взвешенная сумма сигналов
            signal_sum = 0.0
            for signal_name, scores in signal_maps.items():
                weight = signal_weights.get(signal_name, 0.0)
                score = scores.get(cid, 0.0)
                signal_sum += weight * score

            # Финальный скор: base_rrf + signal_sum
            # base_rrf масштабируется на (1 - signal_total_weight) чтобы
            # итоговый скор оставался в диапазоне [0, 1]
            final_scores[cid] = base * (1.0 - signal_total_weight) + signal_sum

        return final_scores

    # ── Signal 1: API Signature Match ─────────────────────

    def _compute_api_signature(
        self, query: str, candidates: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """Оценивает совпадение сигнатуры API.

        Анализирует:
        - Тип символа (function/class vs variable)
        - Имя функции/метода
        - Контекст (класс, модуль)

        Returns:
            {chunk_id: score} — нормализованный скор [0, 1]
        """
        query_tokens = _tokenize(query)
        if not query_tokens:
            return {}

        scores: Dict[str, float] = {}

        for chunk in candidates:
            cid = self._chunk_id(chunk)
            symbol_name = chunk.get("symbol_name", "") or chunk.get("name", "")

            if not symbol_name:
                scores[cid] = 0.0
                continue

            symbol_tokens = _tokenize(symbol_name)
            score = _jaccard(query_tokens, symbol_tokens)

            # Повышаем если тип символа совпадает с интентом запроса
            symbol_type = chunk.get("type", "")
            if any(kw in query.lower() for kw in ["function", "method", "api", "route"]):
                if symbol_type in ("function_definition", "method_definition"):
                    score = score * 0.5 + 0.5  # boost
                else:
                    score *= 0.5

            scores[cid] = min(score, 1.0)

        return scores

    # ── Signal 2: Graph Diffusion (PageRank) ──────────────

    def _compute_graph_diffusion(
        self, candidates: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """Оценивает центральность узла в графе вызовов.

        Использует PageRank из SymbolIndexAdapter.compute_repo_rank().
        Чем выше PageRank — тем важнее символ для проекта.

        Returns:
            {chunk_id: score} — нормализованный скор [0, 1]
        """
        if not self._graph:
            return {}

        # Ленивое вычисление PageRank
        if self._pagerank is None:
            try:
                # Используем прямой SQL для подсчёта PageRank
                conn = self._graph._get_conn()
                rows = conn.execute(
                    """SELECT dst.qualified_name, COUNT(*) AS call_count
                       FROM edges e
                       JOIN nodes src ON e.source_id = src.id
                       JOIN nodes dst ON e.target_id = dst.id
                       WHERE e.type IN ('CALLS', 'ASYNC_CALLS')
                       GROUP BY dst.qualified_name
                       ORDER BY call_count DESC"""
                ).fetchall()

                total = sum(row[1] for row in rows) or 1
                self._pagerank = {
                    row[0]: row[1] / total for row in rows
                }
            except Exception as e:
                logger.debug(f"PageRank computation failed: {e}")
                self._pagerank = {}

        if not self._pagerank:
            return {}

        # Для каждого кандидата — PageRank скор
        max_pr = max(self._pagerank.values()) if self._pagerank else 1.0
        scores: Dict[str, float] = {}

        for chunk in candidates:
            cid = self._chunk_id(chunk)
            symbol_name = chunk.get("symbol_name", "") or chunk.get("name", "")
            file_path = chunk.get("file", "")

            # Ищем PageRank по qualified_name
            best_score = 0.0
            for qname, pr in self._pagerank.items():
                if symbol_name and symbol_name in qname:
                    best_score = max(best_score, pr / max_pr)
                if file_path and file_path in qname:
                    best_score = max(best_score, pr / max_pr * 0.5)

            scores[cid] = best_score

        return scores

    # ── Signal 3: Module Proximity ────────────────────────

    def _compute_module_proximity(
        self, query: str, candidates: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """Оценивает близость в иерархии модулей.

        Если запрос содержит имя модуля (например, "core.parser"),
        то файлы в том же модуле получают выше скор.

        Returns:
            {chunk_id: score} — нормализованный скор [0, 1]
        """
        query_lower = query.lower()
        query_tokens = _tokenize(query)

        # Определяем целевой модуль из запроса
        target_modules: Set[str] = set()

        # Из пути: "core.parser" или "src/core/parser"
        path_match = re.findall(r'(?:src/)?(\w+(?:\.\w+)*)', query_lower)
        for m in path_match:
            parts = m.split(".")
            for i in range(len(parts)):
                target_modules.add("/".join(parts[: i + 1]))

        # Из имён: "parser", "indexer"
        for token in query_tokens:
            if token not in ("get", "set", "find", "create", "update", "delete", "search"):
                target_modules.add(token)

        if not target_modules:
            return {}

        scores: Dict[str, float] = {}

        for chunk in candidates:
            cid = self._chunk_id(chunk)
            file_path = chunk.get("file", "")
            file_lower = file_path.lower()

            # Считаем совпадения модулей
            max_proximity = 0.0
            for module in target_modules:
                if module in file_lower:
                    # Чем глубже совпадение — тем выше скор
                    depth = len(module.split("/"))
                    max_proximity = max(max_proximity, min(1.0, depth * 0.3))

            scores[cid] = max_proximity

        return scores

    # ── Signal 4: Co-change Boost ─────────────────────────

    def _compute_cochange_boost(
        self, query: str, candidates: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """Оценивает частоту совместных изменений файла.

        Файлы, которые часто меняются вместе с другими файлами,
        получают буст — они скорее релевантны.

        Returns:
            {chunk_id: score} — нормализованный скор [0, 1]
        """
        if not self._commit_memory:
            return {}

        scores: Dict[str, float] = {}

        try:
            cochange = self._commit_memory.get_cochange_frequency()
            if not cochange:
                return {}

            # Нормализуем частоты
            max_freq = max(cochange.values()) if cochange else 1.0

            for chunk in candidates:
                cid = self._chunk_id(chunk)
                file_path = chunk.get("file", "")

                if not file_path:
                    scores[cid] = 0.0
                    continue

                # Суммируем co-change частоты для этого файла
                total = 0.0
                for pair, freq in cochange.items():
                    if file_path in pair:
                        total += freq / max_freq

                scores[cid] = min(total, 1.0)

        except Exception as e:
            logger.debug(f"Co-change computation failed: {e}")

        return scores

    # ── Helpers ───────────────────────────────────────────

    @staticmethod
    def _chunk_id(chunk: Dict[str, Any]) -> str:
        """Уникальный ID для кандидата."""
        cid = chunk.get("chunk_id") or chunk.get("id")
        if cid:
            return str(cid)
        # Fallback: file + symbol_name + line
        return f"{chunk.get('file', '')}:{chunk.get('symbol_name', '')}:{chunk.get('start_line', 0)}"

    def get_signal_debug(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        base_rrf_scores: Dict[str, float],
    ) -> Dict[str, Any]:
        """Возвращает детальную разбивку сигналов для отладки.

        Returns:
            {chunk_id: {signal_name: score, final: score, base: score}}
        """
        api_scores = self._compute_api_signature(query, candidates)
        diff_scores = self._compute_graph_diffusion(candidates)
        prox_scores = self._compute_module_proximity(query, candidates)
        cochange_scores = self._compute_cochange_boost(query, candidates)

        signal_maps = {
            "api_signature": api_scores,
            "graph_diffusion": diff_scores,
            "module_proximity": prox_scores,
            "cochange_boost": cochange_scores,
        }

        debug: Dict[str, Any] = {}
        for chunk in candidates:
            cid = self._chunk_id(chunk)
            signals = {}
            for name, scores in signal_maps.items():
                signals[name] = round(scores.get(cid, 0.0), 4)
            signals["base_rrf"] = round(base_rrf_scores.get(cid, 0.0), 4)
            signals["symbol"] = chunk.get("symbol_name", chunk.get("name", ""))
            signals["file"] = chunk.get("file", "")
            debug[cid] = signals

        return debug


__all__ = ["MultiSignalScorer"]
