"""
Alert Store — однократные системные оповещения для агента.

Закмыкает цепь «файл изменён → STALE → VOR → alert агента» (doc 10
24-continuous-verification), которой не существовало ни в одном звене
(Exhibit #23, 2026-09-09).

Отличие от ConsistencyTracker: тот хранит СОСТОЯНИЕ доменов (STALE/CONSISTENT,
событийная модель), а здесь — ДОСТАВЛЯЕМЫЕ оповещения для агента, одноразовые:
после доставки (collect_and_clear) alerts удаляются (Red Team doc 10 §0:4 —
не копить токены в ответах, clear после delivery).

Источники alerts:
    memory_stale — память отмечена STALE после изменения файлов
                   (notify_change → mark_stale("memory")); следующий VOR-проход
                   перепроверит узлы, агент должен знать, что результат мог
                   устареть до этого момента.
    memory_starved — узлы памяти видны >=2 циклов VOR, но ни разу не проверены
                   (MATCHED>0, DELIVERED=0) — систематическое голодание по
                   бюджету, не разовый вылет (Том, 2026-08-16).

Хранилище: <data_root>/projects/<hash>/intelligence/system_alerts.json
(вне проекта, Задача 4/5) — тот же каталог, что project_memory.json.

Thread-safety: threading.Lock (НЕ asyncio.Lock) — alerts читаются из нескольких
event-loop'ов (LSP + MCP), asyncio.Lock привязывается к loop-у (см. consistency.py).
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "AlertStore",
    "get_alert_store",
]

logger = logging.getLogger("MSCodeBase.Intelligence.Alerts")

_ALERTS_FILE = "system_alerts.json"

# Канонические kind'ы.
ALERT_KINDS = ("memory_stale", "memory_starved")


class AlertStore:
    """Хранилище однократных оповещений (thread-safe, per-project).

    Per-project: store_dir выводится из project_path (multi-window, R3TF) —
    alerts не смешиваются между окнами.
    """

    def __init__(self, project_path: Path):
        from src.core.artifact_paths import get_intelligence_dir

        self.store_dir = get_intelligence_dir(project_path)
        self._path = self.store_dir / _ALERTS_FILE
        self._lock = threading.Lock()

    # ── запись ────────────────────────────────────────────────────────────

    def push(self, kind: str, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """Добавляет alert (дедупликация по kind+payload, без limit-а не спамим)."""
        if kind not in ALERT_KINDS:
            logger.debug(f"alerts: неизвестный kind '{kind}' (игнор)")
            return
        with self._lock:
            alerts = self._load()
            # Дедуп: не плодим одинаковые alerts подряд (одно событие — один alert).
            if any(a.get("kind") == kind and a.get("payload") == (payload or {}) for a in alerts):
                return
            alerts.append(
                {
                    "alert_id": f"ALERT-{uuid.uuid4().hex[:6]}",
                    "kind": kind,
                    "message": message,
                    "payload": payload or {},
                    "created_ts": time.time(),
                }
            )
            self._save(alerts)

    # ── чтение + доставка ─────────────────────────────────────────────────

    def collect_and_clear(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Атомарно забирает непрочитанные alerts и удаляет их.

        Одноразовость (Red Team doc 10 §0:4): после доставки alert больше
        не существует — следующий вызов его не увидит, токены не копятся.
        limit: максимум алертов за одну доставку (защита от токен-оверхеда).

        Thread-safe: вся операция под одним lock — два параллельных
        MCP-вызова (memory + explain) не получат один alert дважды:
        первый забрал и удалил, второй увидит уже пустой список.
        """
        with self._lock:
            alerts = self._load()
            if not alerts:
                return []
            taken = alerts[:limit]
            remaining = alerts[limit:]
            self._save(remaining)
        return taken

    def peek(self) -> List[Dict[str, Any]]:
        """Недеструктивный просмотр (для диагностики/health)."""
        with self._lock:
            return self._load()

    # ── внутреннее ────────────────────────────────────────────────────────

    def _load(self) -> List[Dict[str, Any]]:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except (json.JSONDecodeError, OSError):
                logger.warning("alerts: битый system_alerts.json, сброс", exc_info=True)
        return []

    def _save(self, alerts: List[Dict[str, Any]]) -> None:
        try:
            self.store_dir.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(alerts, f, ensure_ascii=False, indent=2)
        except OSError:
            logger.warning("alerts: не удалось записать system_alerts.json", exc_info=True)


_locks: Dict[str, threading.Lock] = {}
_lock_guard = threading.Lock()


def get_alert_store(project_path: Path) -> AlertStore:
    """Per-project синглтон (thread-safe, multi-window R3TF).

    Кэш по resolved project_path — один store на проект, чтобы lock был
    общим между вызовами (иначе два AlertStore держат свои locks и гонка
    read-clear возвращается).
    """
    resolved = str(Path(project_path).resolve())
    global _lock_guard
    with _lock_guard:
        store = _locks.get(resolved)
        if store is None:
            store = AlertStore(Path(resolved))
            _locks[resolved] = store
    return store
