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

# Терминальные статусы, скрытые при чтении по умолчанию (ADR-0002/0003):
# REFUTED — опровергнут, SUPERSEDED — заменён более свежим фактом.
# include_retracted=True возвращает их для аудита.
_HIDDEN_STATUSES = ("REFUTED", "SUPERSEDED")


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
    """Хранилище Project Memory и Incident History (вне проекта, Задача 4/5).

    Данные хранятся в JSON-файлах в системной папке:
    <data_root>/projects/<hash>/intelligence/.
    """

    def __init__(self, project_path: Path):
        from src.core.artifact_paths import get_intelligence_dir

        self.store_dir = get_intelligence_dir(project_path)

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

    def load_memory(self, include_retracted: bool = False) -> Dict[str, List[Dict]]:
        """Загружает проектную память.

        Поддерживает два формата:
        - Новый: список узлов с полем "section" и опциональным "status"
        - Старый: dict с секциями как ключами

        ADR-0002: узлы со status == "REFUTED" скрыты по умолчанию;
        SUPERSEDED (ADR-0002 follow-up: intel_supersede_memory_node) — тоже
        терминальный, скрывается аналогично (заменён более свежим фактом);
        include_retracted=True возвращает их (для аудита). Узлы без поля
        "status" интерпретируются как ACTIVE (backward-compat).
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
            for k, v in data.items():
                if k not in sections:
                    continue
                if not include_retracted and isinstance(v, list):
                    v = [
                        item
                        for item in v
                        if not (
                            isinstance(item, dict)
                            and item.get("status") in _HIDDEN_STATUSES
                        )
                    ]
                sections[k] = v
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
                    if n.get("status") in _HIDDEN_STATUSES and not include_retracted:
                        continue
                    sections[sec].append(n)
        return sections

    def save_memory(self, nodes: List[Dict]):
        self._save_json("project_memory.json", nodes)

    def memory_metrics(self) -> Dict[str, Any]:
        """Метрики памяти для мониторинга (спека v1, раздел «Метрика»).

        false_retraction_rate — доля когда-либо отозванных узлов (текущие
        REFUTED + восстановленные с false_retraction=true), которые человек
        вручную вернул как ложные отзывы (intel_restore_memory_node).
        Рост метрики сигнализирует о false-negative дрифте самой системы
        проверки (неточные якоря / verify-on-read), а не только о дрейфе
        фактов против кода.
        """
        nodes = self._load_json("project_memory.json")
        if isinstance(nodes, dict):
            # Legacy-формат: {"section": [...]} -> флеттим для подсчёта
            nodes = [n for v in nodes.values() if isinstance(v, list) for n in v]
        total = 0
        by_status: Dict[str, int] = {}
        false_retractions = 0
        for n in nodes:
            if not isinstance(n, dict):
                continue
            total += 1
            status = n.get("status") or "ACTIVE"
            by_status[status] = by_status.get(status, 0) + 1
            if n.get("false_retraction"):
                false_retractions += 1
        refuted_total = by_status.get("REFUTED", 0) + false_retractions
        rate = round(false_retractions / refuted_total, 4) if refuted_total else 0.0
        return {
            "total": total,
            "by_status": by_status,
            "refuted_total": refuted_total,
            "false_retractions": false_retractions,
            "false_retraction_rate": rate,
        }


# =====================================================================
# JOB HISTORY STORE (для адаптивного ETA)
# =====================================================================


class JobHistoryStore:
    """Persistent история индексаций для адаптивного ETA.

    Хранится в <data_root>/projects/<hash>/metrics/job_history.json
    (вне проекта, Задача 4/5) как список записей:
    {"project_size": int, "duration_sec": float, "timestamp": float}

    Используется для rolling average по размеру проекта (+-20%).
    """

    def __init__(self, project_path: Path):
        from src.core.artifact_paths import get_metrics_dir

        self.metrics_dir = get_metrics_dir(project_path)
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
