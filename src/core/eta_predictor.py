"""
ETA Predictor — предсказание времени выполнения операций.

Использует реальные метрики из бенчмарка для точных предсказаний.
Интегрируется в MCP как инструмент для планирования задач.
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("eta_predictor")


@dataclass
class OperationProfile:
    """Профиль операции — базовые метрики."""
    name: str
    base_ms: float  # базовое время в ms
    per_item_ms: float  # время на единицу (файл, чанк, etc)
    tokens_estimate: int  # примерное количество токенов


# Базовые профили (обновляются после бенчмарка)
DEFAULT_PROFILES = {
    "search": OperationProfile("Search (hybrid)", 500, 0, 200),
    "index_file": OperationProfile("Index single file", 50, 50, 0),
    "index_project": OperationProfile("Index project", 1000, 50, 0),
    "bug_correlation": OperationProfile("Bug correlation analysis", 2000, 0, 500),
    "knowledge_graph": OperationProfile("Build knowledge graph", 3000, 0, 1000),
    "impact_analysis": OperationProfile("Impact analysis", 500, 0, 100),
    "file_history": OperationProfile("File history", 200, 0, 50),
    "commit_analysis": OperationProfile("Commit analysis", 1000, 0, 300),
}


class ETAPredictor:
    """Предсказатель времени выполнения."""

    def __init__(self, profiles: Optional[Dict[str, OperationProfile]] = None):
        self.profiles = profiles or DEFAULT_PROFILES.copy()
        self._measurements: Dict[str, list] = {}

    def estimate(self, operation: str, items: int = 1) -> Dict:
        """Предсказывает время выполнения операции.

        Args:
            operation: Тип операции (search, index_file, etc)
            items: Количество элементов (файлов, и т.д.)

        Returns:
            {operation, items, estimated_ms, confidence, tokens_estimate}
        """
        profile = self.profiles.get(operation)
        if not profile:
            return {
                "operation": operation,
                "items": items,
                "estimated_ms": 0,
                "confidence": "unknown",
                "tokens_estimate": 0,
                "error": f"Unknown operation: {operation}",
            }

        # Базовое время + время на элементы
        base_ms = profile.base_ms
        items_ms = profile.per_item_ms * items
        total_ms = base_ms + items_ms

        # Корректировка на основе истории измерений
        if operation in self._measurements:
            history = self._measurements[operation]
            if len(history) >= 3:
                # Используем среднее из последних измерений
                avg_measured = sum(history[-10:]) / min(len(history), 10)
                # Взвешенное среднее: 30% профиль, 70% реальные измерения
                total_ms = 0.3 * total_ms + 0.7 * avg_measured

        # Confidence
        if operation in self._measurements and len(self._measurements[operation]) >= 5:
            confidence = "high"
        elif operation in self._measurements:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "operation": operation,
            "items": items,
            "estimated_ms": round(total_ms, 0),
            "estimated_sec": round(total_ms / 1000, 1),
            "confidence": confidence,
            "tokens_estimate": profile.tokens_estimate * max(items, 1),
        }

    def record_measurement(self, operation: str, actual_ms: float):
        """Записывает реальное время выполнения для улучшения предсказаний."""
        if operation not in self._measurements:
            self._measurements[operation] = []
        self._measurements[operation].append(actual_ms)

    def batch_estimate(self, operations: list) -> Dict:
        """Предсказывает время для серии операций.

        Args:
            operations: [{"operation": str, "items": int}, ...]

        Returns:
            {operations: [...], total_ms, total_tokens}
        """
        results = []
        total_ms = 0
        total_tokens = 0

        for op in operations:
            est = self.estimate(op["operation"], op.get("items", 1))
            results.append(est)
            total_ms += est["estimated_ms"]
            total_tokens += est["tokens_estimate"]

        return {
            "operations": results,
            "total_ms": round(total_ms, 0),
            "total_sec": round(total_ms / 1000, 1),
            "total_tokens": total_tokens,
        }

    def format_eta(self, estimate: Dict) -> str:
        """Форматирует ETA в читаемый вид."""
        sec = estimate.get("estimated_sec", 0)
        if sec < 1:
            time_str = f"{estimate['estimated_ms']:.0f}ms"
        elif sec < 60:
            time_str = f"{sec:.1f}s"
        else:
            minutes = int(sec // 60)
            secs = sec % 60
            time_str = f"{minutes}m {secs:.0f}s"

        confidence_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(
            estimate.get("confidence", "low"), "⚪"
        )

        return f"{confidence_emoji} ~{time_str}"


# Глобальный инстанс
_predictor = ETAPredictor()


def get_predictor() -> ETAPredictor:
    """Возвращает глобальный predictor."""
    return _predictor


def estimate_eta(operation: str, items: int = 1) -> str:
    """Утилита для быстрого предсказания ETA."""
    pred = get_predictor()
    est = pred.estimate(operation, items)
    return pred.format_eta(est)
