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
from pathlib import Path
from typing import Optional

try:
    import resource  # POSIX-only
    _HAS_RESOURCE = True
except ImportError:
    _HAS_RESOURCE = False

# Windows CPU measurement через kernel32 (надежнее psutil)
if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.windll.kernel32
    _GetProcessTimes = _kernel32.GetProcessTimes
    _GetSystemTimes = _kernel32.GetSystemTimes
    _GetCurrentProcess = _kernel32.GetCurrentProcess

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD)]

    def _filetime_to_sec(ft: _FILETIME) -> float:
        """100-ns intervals → seconds."""
        return (ft.dwHighDateTime << 32 | ft.dwLowDateTime) / 1e7

    def _get_process_times() -> tuple:
        """Возвращает (user_time, kernel_time) процесса в секундах."""
        creation = _FILETIME()
        exit_t = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        _GetProcessTimes(_GetCurrentProcess(),
                         ctypes.byref(creation),
                         ctypes.byref(exit_t),
                         ctypes.byref(kernel),
                         ctypes.byref(user))
        return _filetime_to_sec(user), _filetime_to_sec(kernel)

    def _get_system_times() -> tuple:
        """Возвращает (idle_time, kernel_time, user_time) системы в секундах."""
        idle = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        _GetSystemTimes(ctypes.byref(idle),
                        ctypes.byref(kernel),
                        ctypes.byref(user))
        return (_filetime_to_sec(idle),
                _filetime_to_sec(kernel),
                _filetime_to_sec(user))

    _HAS_CPU_WINDOWS = True
else:
    _HAS_CPU_WINDOWS = False

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
      - RAM: 2048 MB (2 GB) — ONNX in-process (~400MB) + reranker (~500MB)
        + MCP (~400MB) = ~1.3 GB baseline. 2GB даёт запас.
      - CPU: 90% — soft throttling индексации.
    """

    def __init__(
        self,
        ram_soft_mb: float = 1536.0,
        ram_hard_mb: float = 2048.0,
        cpu_soft_percent: float = 80.0,
        cpu_hard_percent: float = 90.0,
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
        # Rolling window RAM-тренда (последние 30 сэмплов с timestamp)
        self._ram_history: list = []  # [(timestamp, rss_mb), ...]
        self._max_history = 30

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

        timestamp = time.time()
        snapshot = ResourceSnapshot(
            rss_mb=rss_mb,
            cpu_percent=cpu_pct,
            num_threads=len(threading.enumerate()),
            timestamp=timestamp,
        )
        with self._lock:
            self._last_snapshot = snapshot
            self._last_cpu_times = new_cpu_times
            # Rolling window
            self._ram_history.append((timestamp, rss_mb))
            if len(self._ram_history) > self._max_history:
                self._ram_history.pop(0)
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
        gpu = self._sample_gpu()
        disk = self._sample_disk_io()
        self._start_auto_logger()
        crash = self.check_crash_log()
        if crash:
            logger.warning(
                f"🚨 Краш предыдущей сессии: {crash['crash_type']} "
                f"при RAM={crash['last_ram_mb']:.0f}MB "
                f"({crash['seconds_ago']}с назад)"
            )
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
            "ram_trend": self.get_ram_trend(),
            "gpu": gpu,
            "disk_io": disk,
            "crash_history": crash,
        }

    def get_ram_trend(self) -> dict:
        """Анализ тренда RAM за последние N сэмплов.

        Returns:
            dict с полями:
              - rate_mb_per_min: скорость роста/падения (MB/мин)
              - peak_mb: пиковое значение за окно
              - is_growing: True если RAM стабильно растёт
              - samples: количество сэмплов в окне
        """
        with self._lock:
            hist = list(self._ram_history)
        if len(hist) < 3:
            return {"rate_mb_per_min": 0, "peak_mb": 0, "is_growing": False, "samples": len(hist)}
        peak = max(h[1] for h in hist)
        # Линейная регрессия: RAM от времени
        t0 = hist[0][0]
        x = [h[0] - t0 for h in hist]
        y = [h[1] for h in hist]
        n = len(x)
        # Наклон = (n*sum(xy) - sum(x)*sum(y)) / (n*sum(x2) - sum(x)^2)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_x2 = sum(xi * xi for xi in x)
        denom = n * sum_x2 - sum_x * sum_x
        if abs(denom) < 1e-9:
            return {"rate_mb_per_min": 0, "peak_mb": peak, "is_growing": False, "samples": n}
        slope = (n * sum_xy - sum_x * sum_y) / denom  # MB/sec
        rate_per_min = slope * 60  # MB/min
        is_growing = rate_per_min > 10  # >10 MB/мин = растёт
        return {
            "rate_mb_per_min": round(rate_per_min, 1),
            "peak_mb": round(peak, 0),
            "is_growing": is_growing,
            "samples": n,
        }

    def get_subprocesses_info(self) -> list:
        """Возвращает информацию о подпроцессах (llama-server и др.).

        На Windows: читает список дочерних процессов через WMI.
        На Linux: через /proc.
        """
        result = []
        if os.name == "nt":
            try:
                import subprocess as _sp
                _pid = os.getpid()
                out = _sp.check_output(
                    ["powershell", "-NoProfile", "-Command",
                     f"Get-CimInstance Win32_Process | Where-Object {{ $_.ParentProcessId -eq {_pid} }} | Select-Object ProcessId,Name,WorkingSet64,ProcessId | ConvertTo-Csv -NoHeader"],
                    timeout=5, text=True
                )
                for line in out.strip().splitlines():
                    parts = line.split(",")
                    if len(parts) >= 3:
                        _name = parts[0].strip('"')
                        _pid_s = parts[1].strip('"')
                        _ram = parts[2].strip('"')
                        try:
                            _ram_mb = int(_ram) // (1024 * 1024)
                        except Exception:
                            _ram_mb = 0
                        result.append({
                            "name": _name,
                            "pid": int(_pid_s) if _pid_s.isdigit() else 0,
                            "ram_mb": _ram_mb,
                        })
            except Exception as ex:
                logger.debug(f"get_subprocesses_info failed: {ex}")
        return result

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
            except Exception as _e:
                logger.warning("exception", exc_info=True)
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
        except Exception as _e:
            logger.warning("exception", exc_info=True)
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
            except Exception as _e:
                logger.warning("exception", exc_info=True)
                pass
            # Путь 2: kernel32 (legacy)
            try:
                if ctypes.windll.kernel32.GetProcessMemoryInfo(
                    handle, ctypes.byref(counters), counters.cb,
                ):
                    return counters.WorkingSetSize / (1024 * 1024)
            except Exception as _e:
                logger.warning("exception", exc_info=True)
                pass
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        return 0.0

    def _get_cpu_percent(self) -> tuple[float, Optional[tuple]]:
        """CPU% процесса (0-100), нормированный на количество ядер.

        Windows: через GetProcessTimes/GetSystemTimes (kernel32).
        POSIX: через resource.getrusage + wall-clock.

        Returns:
            (cpu_percent, current_cpu_times) — times нужен для следующего
            измерения (для delta).
        """
        # ── Windows ────────────────────────────────────────────────
        if _HAS_CPU_WINDOWS:
            try:
                proc_user, proc_kernel = _get_process_times()
                current = (proc_user, proc_kernel)
                with self._lock:
                    last = self._last_cpu_times
                if last is None:
                    return 0.0, current
                proc_delta = (current[0] - last[0]) + (current[1] - last[1])
                with self._lock:
                    interval = max(0.001, time.monotonic() - self._last_sample_time)
                # На systems with N cores, 100% = N * wall_clock
                cpu_fraction = proc_delta / (interval * self._num_cpus)
                return min(100.0, max(0.0, cpu_fraction * 100.0)), current
            except Exception as ex:
                logger.debug(f"Windows CPU measurement failed: {ex}")
                return 0.0, None

        # ── POSIX ──────────────────────────────────────────────────
        if _HAS_RESOURCE:
            try:
                usage = resource.getrusage(resource.RUSAGE_SELF)
                current = (usage.ru_utime, usage.ru_stime)
                with self._lock:
                    last = self._last_cpu_times
                if last is None:
                    return 0.0, current
                delta = (current[0] - last[0]) + (current[1] - last[1])
                with self._lock:
                    interval = max(0.001, time.monotonic() - self._last_sample_time)
                cpu_fraction = delta / (interval * self._num_cpus)
                return min(100.0, max(0.0, cpu_fraction * 100.0)), current
            except Exception:
                return 0.0, None

        return 0.0, None

    # ─── GPU мониторинг (nvidia-smi или WMI) ─────────────
    _gpu_cache = {"util_pct": None, "ram_mb": None, "temp_c": None, "timestamp": 0.0}

    def _sample_gpu(self) -> dict:
        """Опрашивает GPU (nvidia-smi или WMI).

        Кэшируется на 10 секунд — nvidia-smi дорогой.
        """
        now = time.time()
        if now - self._gpu_cache["timestamp"] < 10:
            return self._gpu_cache

        result = {"util_pct": None, "ram_mb": None, "temp_c": None}
        # nvidia-smi
        try:
            import subprocess as _sp
            out = _sp.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                timeout=5, text=True,
            )
            parts = out.strip().split(", ")
            if len(parts) >= 3:
                result["util_pct"] = float(parts[0]) if parts[0] != "[N/A]" else None
                result["ram_mb"] = float(parts[1]) if parts[1] != "[N/A]" else None
                result["temp_c"] = float(parts[2]) if parts[2] != "[N/A]" else None
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        self._gpu_cache = {**result, "timestamp": now}
        return result

    # ─── Disk I/O (только Windows WMI) ────────────────────
    _disk_io_cache = {"read_mb": 0, "write_mb": 0, "timestamp": 0.0}

    def _sample_disk_io(self) -> dict:
        """Чтение/запись процесса через WMI."""
        if os.name != "nt":
            return {"read_mb": 0, "write_mb": 0}
        now = time.time()
        if now - self._disk_io_cache["timestamp"] < 10:
            return self._disk_io_cache

        result = {"read_mb": 0, "write_mb": 0}
        try:
            import subprocess as _sp
            pid = os.getpid()
            out = _sp.check_output(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-Process -Id {pid} | Select-Object -Property ReadOperationCount,WriteOperationCount) | ConvertTo-Csv -NoHeader"],
                timeout=5, text=True,
            )
            parts = out.strip().split(",")
            if len(parts) >= 2:
                reads = int(parts[0]) if parts[0].isdigit() else 0
                writes = int(parts[1]) if parts[1].isdigit() else 0
                # Оцениваем MB примерно (обычно 4KB на операцию)
                result["read_mb"] = round(reads * 4 / 1024, 1)
                result["write_mb"] = round(writes * 4 / 1024, 1)
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        self._disk_io_cache = {**result, "timestamp": now}
        return result

    # ─── Crash detection через файловый heartbeat ────────
    _CRASH_LOG = Path.home() / ".mscodebase_crash_log.json"

    def _write_crash_log(self):
        """Пишет текущий RAM в crash-лог каждые 5 секунд.

        Если процесс упадёт (OOM / kill), на старте следующей сессии
        увидим последнее значение RAM.
        """
        try:
            snap = self.sample(force=True)
            data = {
                "timestamp": time.time(),
                "rss_mb": round(snap.rss_mb, 0),
                "cpu_pct": round(snap.cpu_percent, 1),
                "pid": os.getpid(),
            }
            self._CRASH_LOG.write_text(
                __import__('json').dumps(data), encoding='utf-8'
            )
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
    @staticmethod
    def check_crash_log() -> Optional[dict]:
        """Проверяет crash-лог на старте.

        Если последняя сессия закончилась с RAM >1500MB → краш.
        Если лог свежий (<60 сек) и другой PID → был перезапуск.
        """
        log_path = Path.home() / ".mscodebase_crash_log.json"
        if not log_path.exists():
            return None
        try:
            data = __import__('json').loads(log_path.read_text(encoding='utf-8'))
            if time.time() - data["timestamp"] > 120:
                return None  # старый лог, не интересен
            current_pid = os.getpid()
            prev_pid = data["pid"]
            ram = data["rss_mb"]
            if prev_pid != current_pid and ram > 1200:
                return {
                    "crash_type": "OOM" if ram > 1500 else "restart",
                    "last_ram_mb": ram,
                    "last_cpu_pct": data.get("cpu_pct", 0),
                    "seconds_ago": round(time.time() - data["timestamp"], 0),
                }
        except Exception as _e:
            logger.warning("exception", exc_info=True)
            pass
        return None

    # ─── Авто-логирование метрик и crash-log ────────────
    _auto_logger_started = False

    def _start_auto_logger(self):
        """Фоновый поток: раз в 30с пишет сводку в лог + crash-лог каждые 5с."""
        if self._auto_logger_started:
            return
        self._auto_logger_started = True

        def _loop():
            _log_counter = 0
            while True:
                try:
                    # Crash-лог каждые 5 секунд (для детекции OOM)
                    self._write_crash_log()

                    _log_counter += 1
                    if _log_counter % 6 == 0:  # раз в 30 секунд
                        snap = self.sample(force=True)
                        gpu = self._sample_gpu()
                        disk = self._sample_disk_io()
                        trend = self.get_ram_trend()

                        gpu_str = f"GPU {gpu.get('util_pct', '?')}%" if gpu.get('util_pct') is not None else "GPU N/A"
                        disk_str = f"Disk R:{disk['read_mb']}MB W:{disk['write_mb']}MB"
                        ram_str = f"RAM {snap.rss_mb:.0f}MB"
                        cpu_str = f"CPU {snap.cpu_percent:.0f}%"
                        if trend.get("is_growing"):
                            ram_str += f" (📈 +{trend['rate_mb_per_min']}MB/мин)"
                        logger.info(
                            f"📊 {ram_str} | {cpu_str} | {gpu_str} | {disk_str} | "
                            f"threads={snap.num_threads}"
                        )
                except Exception as _e:
                    logger.warning("exception", exc_info=True)
                    pass
                time.sleep(5)

        t = threading.Thread(target=_loop, daemon=True, name="resmon-auto")
        t.start()

    def ensure_auto_logger(self):
        self._start_auto_logger()


# Импорт sys в конце чтобы не сломать type hints выше.
import sys  # noqa: E402

__all__ = [
    "ResourceSnapshot",
    "ResourceMonitor",
    "get_global_resource_monitor",
    "reset_global_resource_monitor",
]
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
