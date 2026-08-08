"""
Consistency Engine — модель состояний согласованности артефактов MCP.

Проблема: source state (файлы на диске), index state (LanceDB), graph state
(SQLite PropertyGraph), symbol state (SymbolIndex) и memory state (commit/project
memory) рассинхронизируются. Без формальной модели расхождения "тихие":
stale-результаты поиска, enrichment по устаревшему графу, ложные диагнозы.

Состояния:
    CONSISTENT — артефакт отражает источник (актуален)
    STALE      — источник изменился, артефакт ещё не обновлён
    UPDATING   — обновление в процессе
    PARTIAL    — обновлён частично (часть данных устарела)
    CORRUPTED  — артефакт повреждён/нечитаем
    UNKNOWN    — состояние не определено (артефакт не инициализирован)

Домены:
    source         — файлы на диске
    index          — LanceDB (chunks)
    graph          — PropertyGraph (SQLite)
    symbols        — SymbolIndex
    memory         — project memory (ADRs/incidents)
    commit_memory  — семантическая память коммитов

Переходы (событийная модель, НЕ polling):
    notify_change(...)                -> source=STALE, index=STALE
    reindex job started               -> index=UPDATING
    reindex job completed             -> index/graph/symbols=CONSISTENT
    reindex job failed                -> index=CORRUPTED
    intel_reset_index                 -> index=CORRUPTED -> UPDATING
    refresh_db_connection() ok        -> index=CONSISTENT
    commit_memory refresh ok          -> commit_memory=CONSISTENT

Thread-safety: threading.Lock (НЕ asyncio.Lock) — см. INC-53EC/REFC-03:
Lock шарится между event-loop-ами LSP и MCP, asyncio.Lock привязывается к
loop-у первого await и дедлочит.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Dict, Optional, Tuple

__all__ = [
    "ConsistencyState",
    "ConsistencyTracker",
    "get_consistency_tracker",
    "DOMAINS",
]

logger = logging.getLogger("consistency")

# Канонический набор доменов.
DOMAINS = ("source", "index", "graph", "symbols", "memory", "commit_memory")


class ConsistencyState(str, Enum):
    """Состояние согласованности артефакта."""

    CONSISTENT = "CONSISTENT"
    STALE = "STALE"
    UPDATING = "UPDATING"
    PARTIAL = "PARTIAL"
    CORRUPTED = "CORRUPTED"
    UNKNOWN = "UNKNOWN"


class ConsistencyTracker:
    """Событийный трекер состояний артефактов (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: Dict[str, Tuple[ConsistencyState, str, float]] = {}

    # ── записи ────────────────────────────────────────────────────────────

    def set(self, domain: str, state: ConsistencyState, reason: str = "") -> None:
        """Устанавливает состояние домена с отметкой времени."""
        if domain not in DOMAINS:
            logger.debug(f"consistency: неизвестный домен '{domain}' (игнор)")
            return
        now = time.time()
        with self._lock:
            prev = self._states.get(domain)
            self._states[domain] = (state, reason, now)
        if prev is None or prev[0] != state:
            logger.debug(
                f"consistency: {domain} {prev[0].value if prev else '-'} -> {state.value}"
                + (f" ({reason})" if reason else "")
            )

    def mark_consistent(self, domain: str, reason: str = "") -> None:
        self.set(domain, ConsistencyState.CONSISTENT, reason)

    def mark_stale(self, domain: str, reason: str = "") -> None:
        self.set(domain, ConsistencyState.STALE, reason)

    def mark_updating(self, domain: str, reason: str = "") -> None:
        self.set(domain, ConsistencyState.UPDATING, reason)

    def mark_corrupted(self, domain: str, reason: str = "") -> None:
        self.set(domain, ConsistencyState.CORRUPTED, reason)

    def mark_partial(self, domain: str, reason: str = "") -> None:
        self.set(domain, ConsistencyState.PARTIAL, reason)

    # ── чтение ────────────────────────────────────────────────────────────

    def get(self, domain: str) -> Dict[str, object]:
        """Состояние домена: {domain, state, updated_ts, age_sec, reason}."""
        with self._lock:
            entry = self._states.get(domain)
        if entry is None:
            return {
                "domain": domain,
                "state": ConsistencyState.UNKNOWN.value,
                "updated_ts": None,
                "age_sec": None,
                "reason": "",
            }
        state, reason, ts = entry
        return {
            "domain": domain,
            "state": state.value,
            "updated_ts": ts,
            "age_sec": round(time.time() - ts, 2) if ts else None,
            "reason": reason,
        }

    def get_all(self) -> Dict[str, Dict[str, object]]:
        """Снимок всех доменов."""
        return {d: self.get(d) for d in DOMAINS}

    def require(
        self, domain: str, *allowed: ConsistencyState
    ) -> Tuple[bool, ConsistencyState]:
        """Guard: разрешено ли состояние домена для операции.

        Используется enrichment'ом и диагностикой: если домен НЕ в allowed —
        операция должна либо отложиться, либо пропустить зависимый шаг.

        Returns:
            (ok, current_state)
        """
        entry = self.get(domain)
        current = ConsistencyState(entry["state"])  # type: ignore[arg-type]
        return current in allowed, current

    def is_consistent(self, domain: str) -> bool:
        ok, _ = self.require(domain, ConsistencyState.CONSISTENT)
        return ok

    def invalidate(self) -> None:
        """Полный сброс в UNKNOWN (перезапуск сессии)."""
        with self._lock:
            self._states.clear()


_tracker: Optional[ConsistencyTracker] = None
_tracker_lock = threading.Lock()


def get_consistency_tracker() -> ConsistencyTracker:
    """Глобальный трекер (ленивый синглтон, thread-safe)."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = ConsistencyTracker()
    return _tracker
