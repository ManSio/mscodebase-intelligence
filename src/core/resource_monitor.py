"""
Resource Monitor — отслеживание RAM/CPU без внешних зависимостей.

Использует ТОЛЬКО stdlib:
  - resource.getrusage() для RSS (Windows + Unix).
  - os.cpu_count() для нормирования CPU.
  - threading + time для семплинга.

Не использует psutil — лишняя зависимость для простого мониторинга.

Интеграция:
  - ProjectIndexerRegistry получает monitor в конструктор.
  - Перед созданием нового Indexer-а registry вызывает
    monitor.is_under_pressure(). Если True — LRU evict.
  - Embedder / Searcher могут звать suggest_throttle_delay()
    для замедления batch-обработки при высокой нагрузке.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

try:
    import resource  # POSIX-only
    _HAS_RESOURCE = True
except ImportError:
    _HAS_RESOURCE = False

logger = logging.getLogger("mscodebase_server.resource_monitor")


@dataclass
class ResourceSnapshot:
    """Снимок ресурсов на момент измерения."""
    rss_mb: float           # Resident Set Size (MB)
    cpu_percent: float      # Текущая загрузка CPU (0-100)
    num_threads: int        # Количество thread-ов
    timestamp: float        # Unix timestamp

    def to_dict(self) -> dict:
        return {
            "rss_mb": round(self.rss_mb, 1),
            "cpu_percent": round(self.cpu_percent, 1),
            "num_threads": self.num_threads,
            "timestamp": self.timestamp,
        }


class ResourceMonitor:
    """Монитор ресурсов процесса MCP/LSP.

    Дизайн:
      - Singleton (один на процесс).
      - Sampling rate — не чаще раза в секунду (защита от overhead).
      - Pressure detection по двум порогам: RAM (hard) и CPU (soft).

    Пороги по умолчанию:
      - RAM: 1024 MB (1 GB) — агрессивно для multi-window.
        Каждый Indexer ~200-500MB, плюс embedder-кэш.
      - CPU: 85% — soft throttling индексации.
    """

    def __init__(
        self,
        ram_soft_mb: float = 768.0,
        ram_hard_mb: float = 1024.0,
        cpu_soft_percent: float = 75.0,
        cpu_hard_percent: float = 85.0,
        min_sample_interval_sec: float = 1.0,
    ):
        self._ram_soft = ram_soft_mb
        self._ram_hard = ram_hard_mb
        self._cpu_soft = cpu_soft_percent
        self._cpu_hard = cpu_hard_percent
        self._min_sample_interval = min_sample_interval_sec

        self._lock = threading.Lock()
        self._last_snapshot: Optional[ResourceSnapshot] = None
        self._last_sample_time: float = 0.0
        self._last_cpu_times: Optional[tuple] = None
        self._num_cpus = max(1, os.cpu_count() or 1)

        logger.info(
            f"ResourceMonitor: RAM soft={ram_soft_mb}MB hard={ram_hard_mb}MB, "
            f"CPU soft={cpu_soft_percent}% hard={cpu_hard_percent}%, "
            f"cores={self._num_cpus}"
        )

    def sample(self, force: bool = False) -> ResourceSnapshot:
        """Возвращает текущий снимок ресурсов (с throttling семплов).

        Args:
            force: пропустить throttling и сэмплировать немедленно.

        Returns:
            ResourceSnapshot с актуальными метриками.
        """
        now = time.monotonic()
        with self._lock:
            if (
                not force
                and self._last_snapshot is not None
                and (now - self._last_sample_time) < self._min_sample_interval
            ):
                return self._last_snapshot
            self._last_sample_time = now

        # RSS
        rss_mb = self._get_rss_mb()

        # CPU
        cpu_pct, new_cpu_times = self._get_cpu_percent()

        snapshot = ResourceSnapshot(
            rss_mb=rss_mb,
            cpu_percent=cpu_pct,
            num_threads=len(threading.enumerate()),
            timestamp=time.time(),
        )
        with self._lock:
            self._last_snapshot = snapshot
            self._last_cpu_times = new_cpu_times
        return snapshot

    def is_under_pressure(self, hard: bool = False) -> bool:
        """Проверяет, есть ли давление на ресурсы.

        Args:
            hard: если True, пороги жёсткие (вытеснение Indexer-а).
                  если False, мягкие (throttling).

        Returns:
            True если RAM или CPU превышают порог.
        """
        snap = self.sample()
        ram_threshold = self._ram_hard if hard else self._ram_soft
        cpu_threshold = self._cpu_hard if hard else self._cpu_soft
        return snap.rss_mb > ram_threshold or snap.cpu_percent > cpu_threshold

    def suggest_throttle_delay_sec(self) -> float:
        """Подсказывает задержку (в секундах) для throttling.

        Возвращает 0.0 если нагрузка нормальная.
        Возвращает 0.05-0.5s при soft pressure (между batch-операциями).
        Возвращает 1.0+ при hard pressure (между файлами).
        """
        snap = self.sample()
        if snap.rss_mb > self._ram_hard or snap.cpu_percent > self._cpu_hard:
            return min(2.0, (snap.rss_mb - self._ram_hard) / 256.0 + 0.5)
        if snap.rss_mb > self._ram_soft or snap.cpu_percent > self._cpu_soft:
            return 0.1
        return 0.0

    def get_summary(self) -> dict:
        """Возвращает summary для HealthReport."""
        snap = self.sample(force=True)
        return {
            **snap.to_dict(),
            "ram_soft_mb": self._ram_soft,
            "ram_hard_mb": self._ram_hard,
            "cpu_soft_percent": self._cpu_soft,
            "cpu_hard_percent": self._cpu_hard,
            "num_cpus": self._num_cpus,
            "under_soft_pressure": self.is_under_pressure(hard=False),
            "under_hard_pressure": self.is_under_pressure(hard=True),
            "suggested_throttle_sec": self.suggest_throttle_delay_sec(),
        }

    # ─── Внутренние методы ──────────────────────────────

    def _get_rss_mb(self) -> float:
        """RSS процесса в MB (без psutil)."""
        if _HAS_RESOURCE:
            try:
                # resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                # На Linux: KB. На macOS: bytes. На Windows: getrusage
                # недоступен, fallback ниже.
                usage = resource.getrusage(resource.RUSAGE_SELF)
                rss = usage.ru_maxrss
                if sys.platform == "darwin":
                    rss_mb = rss / (1024 * 1024)
                else:
                    # Linux: ru_maxrss в KB.
                    rss_mb = rss / 1024.0
                if rss_mb > 0:
                    return rss_mb
            except Exception:
                pass
        # Windows / fallback: читаем через /proc/self/status (если есть)
        # или OpenProcess + GetProcessMemoryInfo.
        return self._get_rss_windows() if os.name == "nt" else self._get_rss_proc()

    @staticmethod
    def _get_rss_proc() -> float:
        """Linux /proc/self/status fallback."""
        try:
            with open("/proc/self/status", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        # VmRSS:    12345 kB
                        kb = float(line.split()[1])
                        return kb / 1024.0
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _get_rss_windows() -> float:
        """Windows: GetProcessMemoryInfo через psapi.dll.

        Python 3.14 / Windows 11: kernel32.GetProcessMemoryInfo отсутствует
        (deprecated в пользу psapi.dll). Пробуем psapi, fallback — kernel32.
        """
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()

            # Путь 1: psapi.dll (рекомендуемый на Win10+/Python 3.14)
            try:
                psapi = ctypes.WinDLL("psapi.dll", use_last_error=True)
                GetProcessMemoryInfo = psapi.GetProcessMemoryInfo
                GetProcessMemoryInfo.argtypes = [
                    wintypes.HANDLE,
                    ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                    wintypes.DWORD,
                ]
                GetProcessMemoryInfo.restype = wintypes.BOOL
                if GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                    return counters.WorkingSetSize / (1024 * 1024)
            except Exception:
                pass

            # Путь 2: kernel32 (legacy)
            try:
                if ctypes.windll.kernel32.GetProcessMemoryInfo(
                    handle, ctypes.byref(counters), counters.cb,
                ):
                    return counters.WorkingSetSize / (1024 * 1024)
            except Exception:
                pass
        except Exception:
            pass
        return 0.0

    def _get_cpu_percent(self) -> tuple[float, Optional[tuple]]:
        """CPU% процесса (0-100), нормированный на количество ядер.

        Returns:
            (cpu_percent, current_cpu_times) — times нужен для следующего
            измерения (для delta).
        """
        if not _HAS_RESOURCE:
            return 0.0, None
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            current = (usage.ru_utime, usage.ru_stime)
            with self._lock:
                last = self._last_cpu_times
            if last is None:
                # Первое измерение — не можем посчитать delta.
                return 0.0, current
            delta = (current[0] - last[0]) + (current[1] - last[1])
            # Нормируем на wall-clock между измерениями.
            with self._lock:
                interval = max(0.001, time.monotonic() - self._last_sample_time)
            # ru_*time в секундах. На 1 ядро 1.0 = 100%. На N ядер 1.0/N = 100%/N.
            cpu_fraction = delta / (interval * self._num_cpus)
            return min(100.0, max(0.0, cpu_fraction * 100.0)), current
        except Exception:
            return 0.0, None


# Импорт sys в конце чтобы не сломать type hints выше.
import sys  # noqa: E402

# Singleton instance (один на процесс).
_global_monitor: Optional[ResourceMonitor] = None
_global_lock = threading.Lock()


def get_global_resource_monitor() -> ResourceMonitor:
    """Возвращает singleton ResourceMonitor."""
    global _global_monitor
    with _global_lock:
        if _global_monitor is None:
            _global_monitor = ResourceMonitor()
        return _global_monitor


def reset_global_resource_monitor() -> None:
    """Сбрасывает singleton (для тестов)."""
    global _global_monitor
    with _global_lock:
        _global_monitor = None
