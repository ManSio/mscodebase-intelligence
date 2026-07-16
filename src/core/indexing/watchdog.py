"""Watchdog — мониторинг активности индексатора для HealthReport."""
from __future__ import annotations

import threading
import time


class Watchdog:
    """Отслеживает активность индексатора через heartbeat."""

    def __init__(self):
        self._heartbeat = time.time()
        self._ever_beat = False
        self._label = "idle"
        self._lock = threading.Lock()

    def heartbeat(self, label: str = ""):
        with self._lock:
            self._heartbeat = time.time()
            self._ever_beat = True
            if label:
                self._label = label

    def status(self) -> dict:
        with self._lock:
            if not self._ever_beat:
                return {"alive": True, "idle_sec": 0.0, "label": self._label}
            age = time.time() - self._heartbeat
            return {"alive": age < 60.0, "idle_sec": round(age, 1), "label": self._label}
