"""
MSCodeBase Intelligence Store — Хранилища данных для Project Memory и Incidents

Содержит:
- Incident — датакласс инцидента
- MemoryNode — датакласс узла проектной памяти
- IntelligenceStore — JSON-хранилище для incidents + project memory
- JobHistoryStore — rolling history для адаптивного ETA индексации
"""

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "Incident",
    "MemoryNode",
    "IntelligenceStore",
    "JobHistoryStore",
]
logger = logging.getLogger("MSCodeBase.Intelligence.Store")


# =====================================================================
# ДАТАКЛАССЫ
# =====================================================================


@dataclass
class Incident:
    """Инцидент или баг в проекте."""

    incident_id: str
    timestamp: str
    component: str
    symptom: str
    root_cause: str
    fix: str
    success: bool


@dataclass
class MemoryNode:
    """Узел проектной памяти."""

    node_id: str
    section: str  # 'adrs', 'known_issues', 'tech_debt', 'failed_attempts'
    timestamp: str
    data: Dict[str, Any]


# =====================================================================
# INTELLIGENCE STORE
# =====================================================================


class IntelligenceStore:
    """Хранилище Project Memory и Incident History в .codebase_indices/intelligence/.

    Данные хранятся в JSON-файлах для прозрачности и версионирования.
    """

    def __init__(self, project_path: Path):
        self.store_dir = project_path / ".codebase_indices" / "intelligence"
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def _load_json(self, filename: str) -> List[Dict]:
        path = self.store_dir / filename
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save_json(self, filename: str, data: List[Dict]):
        path = self.store_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_incidents(self) -> List[Dict]:
        return self._load_json("incidents.json")

    def save_incidents(self, incidents: List[Dict]):
        self._save_json("incidents.json", incidents)

    def load_memory(self) -> Dict[str, List[Dict]]:
        """Загружает проектную память.

        Поддерживает два формата:
        - Новый: список узлов с полем "section"
        - Старый: dict с секциями как ключами
        """
        data = self._load_json("project_memory.json")
        if isinstance(data, dict):
            # Старый формат: {"adrs": [...], "known_issues": [...]}
            sections = {
                "adrs": [],
                "known_issues": [],
                "tech_debt": [],
                "failed_attempts": [],
            }
            sections.update({k: v for k, v in data.items() if k in sections})
            return sections
        # Новый формат: список узлов с полем "section"
        sections = {
            "adrs": [],
            "known_issues": [],
            "tech_debt": [],
            "failed_attempts": [],
        }
        for n in data:
            if isinstance(n, dict):
                sec = n.get("section", "")
                if sec in sections:
                    sections[sec].append(n)
        return sections

    def save_memory(self, nodes: List[Dict]):
        self._save_json("project_memory.json", nodes)


# =====================================================================
# JOB HISTORY STORE (для адаптивного ETA)
# =====================================================================


class JobHistoryStore:
    """Persistent история индексаций для адаптивного ETA.

    Хранится в .codebase_indices/metrics/job_history.json как список записей:
    {"project_size": int, "duration_sec": float, "timestamp": float}

    Используется для rolling average по размеру проекта (+-20%).
    """

    def __init__(self, project_path: Path):
        self.metrics_dir = project_path / ".codebase_indices" / "metrics"
        self.metrics_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.metrics_dir / "job_history.json"
        self._lock: Optional[threading.Lock] = None  # лениво создаётся при записи

    def _get_lock(self) -> threading.Lock:
        if self._lock is None:
            self._lock = threading.Lock()
        return self._lock

    def load_history(self) -> List[Dict[str, Any]]:
        """Загружает историю. Возвращает [] при ошибке/отсутствии."""
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def append_record(self, project_size: int, duration_sec: float) -> None:
        """Дописывает запись и обрезает историю до 50 последних."""
        with self._get_lock():
            history = self.load_history()
            history.append(
                {
                    "project_size": project_size,
                    "duration_sec": round(duration_sec, 1),
                    "timestamp": time.time(),
                }
            )
            # Ограничиваем размер: храним последние 50 записей
            if len(history) > 50:
                history = history[-50:]
            try:
                with open(self.history_file, "w", encoding="utf-8") as f:
                    json.dump(history, f, ensure_ascii=False, indent=2)
            except OSError:
                logger.warning("Failed to append job history record", exc_info=True)

    def get_estimated_duration(
        self, project_size: int, fallback: float = 120.0
    ) -> float:
        """Rolling average по размеру проекта (+-20%).

        Возвращает среднее время последних 3-х похожих запусков,
        либо fallback, если истории нет или похожих проектов не найдено.
        """
        history = self.load_history()
        if not history:
            return fallback

        # Ищем похожие проекты по размеру (отклонение +-20%)
        lo, hi = 0.8 * project_size, 1.2 * project_size
        similar = [j for j in history if lo <= j.get("project_size", 0) <= hi]
        if not similar:
            # Fallback: среднее по всем (если размер сильно изменился)
            similar = history

        # Берём последние 3 запуска
        recent = similar[-3:]
        avg = sum(j["duration_sec"] for j in recent) / len(recent)
        return max(avg, 5.0)
