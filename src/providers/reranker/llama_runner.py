"""
llama.cpp runner — автоматический lifecycle.

Управляет llama-server.exe как подпроцессом:
- Скачивает бинарник при первом запуске
- Скачивает GGUF модели (bge-m3 + reranker)
- Запускает/останавливает сервер
- Health-чеки через /health
- Graceful shutdown

Архитектура:
  MCP process
    ├── LlamaRunner (менеджер подпроцесса)
    │   ├── llama-server --embedding (bge-m3 GGUF)
    │   └── llama-server --reranking (bge-reranker-v2-m3 GGUF)
    └── Fallback: ONNX server (если llama не запустился)
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, Optional

import ctypes
from ctypes import wintypes
import httpx

from src.providers.reranker.llama_install import *  # type: ignore  # noqa: F401, F403, F811
from src.providers.reranker.llama_install import (  # noqa: F401 — explicit compat
    LLAMA_VERSION,
    GGUF_MODELS,
    is_model_downloaded,
    download_llama_binary,
    download_gguf_model,
    is_installed,
    _get_llama_dir,
    _get_models_dir,
    _IS_INSIDER,
)

logger = logging.getLogger("mscodebase_server.llama_runner")

# ─── Планировщик модели ────────────────────────────────────────
# Пока llama-server умеет загружать только 1 модель за раз.
# Запускаем embedder, при необходимости реранкинга — рестарт с --reranking.
# (В будущем релизах llama.cpp обещают поддержку нескольких моделей в одном процессе)


# ─── Runtime ────────────────────────────────────────────────────

def _popen_with_job(popen_args, **kwargs):
    proc = subprocess.Popen(popen_args, **kwargs)
    if sys.platform == 'win32':
        try:
            kernel32 = ctypes.windll.kernel32
            h_job = kernel32.CreateJobObjectW(None, None)
            if h_job:
                class _BLI(ctypes.Structure):
                    _fields_ = [
                        ('PerProcessUserTimeLimit', wintypes.LARGE_INTEGER),
                        ('PerJobUserTimeLimit', wintypes.LARGE_INTEGER),
                        ('LimitFlags', wintypes.DWORD),
                        ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t),
                        ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t),
                        ('PriorityClass', wintypes.DWORD),
                        ('SchedulingClass', wintypes.DWORD),
                    ]
                limits = _BLI()
                limits.LimitFlags = 0x2000
                kernel32.SetInformationJobObject(h_job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                h_process = kernel32.OpenProcess(0x00100001, False, proc.pid)
                if h_process:
                    kernel32.AssignProcessToJobObject(h_job, h_process)
                    kernel32.CloseHandle(h_process)
        except Exception as _e:
            logger.warning(f"JobObject error: {_e}")
            pass
    return proc


class LlamaRunner:
    """Управляет жизненным циклом llama.cpp сервера.

    Использование:
        runner = LlamaRunner()
        await runner.start()
        health = await runner.health()
        await runner.stop()
    """

    RERANK_PORT = int(os.getenv("LLAMA_CPP_RERANK_PORT", "8081"))
    MAX_RAM_MB = int(os.getenv("LLAMA_MAX_RAM_MB", "1024"))  # авто-рестарт при превышении
    # Idle timeout для реранкера: выгружаем через N секунд бездействия
    # Решает OOM-краш (issue OOM-20260711): 2× llama-server ~2.7 GB
    # Реранкер используется реже эмбеддера — держать постоянно нет смысла.
    RERANKER_IDLE_TIMEOUT = int(os.getenv("RERANKER_IDLE_TIMEOUT", "300"))

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._model_key: Optional[str] = None
        self._reranker_process: Optional[subprocess.Popen] = None
        self._embedder_log_fh: Optional[Any] = None  # файл-объект лога embedder
        self._reranker_log_fh: Optional[Any] = None  # файл-объект лога reranker
        self._host = LLAMA_HOST
        self._port = LLAMA_PORT
        self._startup_timeout = 30
        self._last_reranker_use: float = 0.0  # timestamp последнего использования
        # ─── Crash loop detection ───
        self._reranker_restart_attempts: list[float] = []  # timestamps попыток
        self._reranker_last_error: str = ""  # последняя ошибка
        self._reranker_restart_blocked_until: float = 0.0  # блокировка при crash loop
        self._reranker_lock = threading.Lock()  # thread-safe для полей реранкера
        # Watchdog — авто-рестарт при утечке памяти
        self._watchdog_stop = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None

    def _start_watchdog(self):
        """Фоновый мониторинг RAM llama-server. Перезапуск/выгрузка при превышении лимита."""
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="llama-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()
        logger.debug(f"🔍 Watchdog запущен (лимит {self.MAX_RAM_MB} MB, idle {self.RERANKER_IDLE_TIMEOUT}s)")

    def _watchdog_loop(self):
        while not self._watchdog_stop.wait(30):
            # Проверка idle-таймаута реранкера (выгружаем если простаивает)
            if self._reranker_process is not None and self._last_reranker_use > 0:
                idle = time.time() - self._last_reranker_use
                if idle > self.RERANKER_IDLE_TIMEOUT:
                    logger.info(f"🧹 Реренкер простаивает {idle:.0f}s > {self.RERANKER_IDLE_TIMEOUT}s — выгружаю")
                    self._unload_reranker()
            # Проверка RAM per-process
            for proc, name in [(self._process, "embedder"), (self._reranker_process, "reranker")]:
                if proc is None:
                    continue
                try:
                    pid = proc.pid
                    import subprocess as _sp
                    out = _sp.check_output(
                        ['powershell', '-NoProfile', '-Command',
                         f'Get-Process -Id {pid} | Select-Object -ExpandProperty WorkingSet64'],
                        timeout=5
                    ).decode().strip()
                    ram_mb = int(out) // (1024*1024)
                    if ram_mb > self.MAX_RAM_MB:
                        logger.warning(f"🚨 {name} RAM {ram_mb}MB > лимит {self.MAX_RAM_MB}MB. Перезапуск...")
                        if name == "embedder":
                            self._restart_embedder()
                        else:
                            self._restart_reranker()
                except Exception as _wtf:
                    logger.error(f"Watchdog error ({name} PID={pid}): {_wtf}")

    def _restart_embedder(self):
        model_key = self._model_key or DEFAULT_EMBEDDING_MODEL
        # Асинхронный рестарт в синхронном потоке
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.stop())
        loop.run_until_complete(self.start(model_key))
        loop.close()

    def _restart_reranker(self):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.stop_reranker())
        loop.run_until_complete(self.start_reranker())
        loop.close()

    def _unload_reranker(self):
        """Выгружает реранкер без авто-рестарта (idle timeout)."""
        if self._reranker_process is None:
            return
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.stop_reranker())
        loop.close()
        self._last_reranker_use = 0.0

    def touch_reranker(self):
        """Отмечает использование реранкера (сбрасывает idle-таймер)."""
        self._last_reranker_use = time.time()

    # ─── Reranker Lifecycle: On-Demand Start + Crash Loop Detection ───

    def is_reranker_alive(self) -> bool:
        """Проверяет, жив ли процесс реранкера.

        Проверяет в порядке приоритета:
        1. Если есть сохранённый Popen и его poll() == None → жив
        2. Если процесс неизвестен (None), но порт отвечает → жив
           (другой экземпляр LlamaRunner или MCP пережил процесс)
        Возвращает False если процесс точно мёртв."""
        # Проверка через сохранённый процесс
        if self._reranker_process is not None:
            ret = self._reranker_process.poll()
            if ret is None:
                return True
            # Процесс завершился
            return False
        # Процесс не сохранён — проверяем порт (возможно запущен другим экземпляром)
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            result = s.connect_ex((self._host, self.RERANK_PORT))
            s.close()
            return result == 0
        except Exception:
            return False

    def get_reranker_feedback(self) -> dict:
        """Возвращает структурированный статус реранкера для health report.

        Returns:
            {
                "alive": bool,
                "process_pid": int|None,
                "last_error": str,
                "restart_attempts": int,
                "restart_blocked_until": float,
                "idle_sec": float,
            }
        """
        alive = self.is_reranker_alive()
        now = time.time()
        return {
            "alive": alive,
                "process_pid": self._reranker_process.pid if (alive and self._reranker_process is not None) else None,
                "last_error": self._reranker_last_error,
                "restart_attempts": len(self._reranker_restart_attempts),
                "restart_blocked_until": max(0.0, self._reranker_restart_blocked_until - now),
                "idle_sec": (now - self._last_reranker_use) if self._last_reranker_use > 0 else 0.0,
            }

    async def ensure_reranker_started(self, timeout: int = 30) -> dict:
        """Гарантирует, что реранкер запущен. Стартует если нужно.

        Args:
            timeout: максимальное время ожидания старта (сек)

        Returns:
            {
                "success": bool,
                "error": str,  # пустая строка если ok
                "startup_time_ms": float,
                "attempts": int,
            }
        """
        now = time.time()

        # Crash loop detection: >3 попыток за 5 мин → блокируем
        self._reranker_restart_attempts = [
            t for t in self._reranker_restart_attempts
            if now - t < 300
        ]
        if len(self._reranker_restart_attempts) >= 3:
            self._reranker_restart_blocked_until = now + 600  # 10 мин
            msg = (f"Реренкер заблокирован: {len(self._reranker_restart_attempts)} "
                   f"попыток за 5 мин. Следующая попытка через 10 мин.")
            logger.error(msg)
            self._reranker_last_error = msg
            return {
                "success": False,
                "error": msg,
                "startup_time_ms": 0,
                "attempts": len(self._reranker_restart_attempts),
                "crash_loop_blocked": True,
            }

        if self.is_reranker_alive():
            self.touch_reranker()
            return {
                "success": True,
                "error": "",
                "startup_time_ms": 0,
                "attempts": 0,
                "crash_loop_blocked": False,
            }

        # Пробуем запустить
        self._reranker_restart_attempts.append(now)
        t0 = time.time()
        try:
            started = await self.start_reranker()
            dt = (time.time() - t0) * 1000
            if started:
                self.touch_reranker()
                logger.info(f"Реренкер запущен по требованию за {dt:.0f}ms")
                self._reranker_last_error = ""
                return {
                    "success": True,
                    "error": "",
                    "startup_time_ms": dt,
                    "attempts": len(self._reranker_restart_attempts),
                    "crash_loop_blocked": False,
                }
            else:
                msg = "Не удалось запустить реранкер (start_reranker вернул False)"
                self._reranker_last_error = msg
                logger.warning(msg)
                return {
                    "success": False,
                    "error": msg,
                    "startup_time_ms": dt,
                    "attempts": len(self._reranker_restart_attempts),
                    "crash_loop_blocked": False,
                }
        except Exception as e:
            dt = (time.time() - t0) * 1000
            msg = f"Критическая ошибка запуска реранкера: {e}"
            self._reranker_last_error = msg
            logger.error(msg)
            return {
                "success": False,
                "error": msg,
                "startup_time_ms": dt,
                "attempts": len(self._reranker_restart_attempts),
                "crash_loop_blocked": False,
            }

    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def reranker_url(self) -> str:
        return f"http://{self._host}:{self.RERANK_PORT}"

    async def start(self, model_key: str = DEFAULT_EMBEDDING_MODEL) -> bool:
        """Запускает llama-server или подключается к уже запущенному на self._port.
        
        Сначала проверяет, отвечает ли порт /health — если да, используем
        существующий процесс. Иначе запускаем новый.
        """
        if self.is_alive() and self._model_key == model_key:
            return True

        # Проверяем, не запущен ли уже llama-server на этом порту (другим процессом)
        if await self._probe_port(self._port):
            logger.info(f"🔌 llama-server уже запущен на порту {self._port}, подключаюсь")
            self._model_key = model_key
            return True

        gguf_path = _gguf_path(model_key)
        if not gguf_path.exists():
            logger.error(f"GGUF модель не найдена: {gguf_path}")
            return False

        flags = ["--embedding"] if model_key in ("bge-m3", "qwen3-embedding") else ["--reranking"]
        
        try:
            self._process = _popen_with_job(
                [
                    str(_llama_bin_vulkan()) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else str(_llama_bin()),
                    "--host", self._host,
                    "--port", str(self._port),
                    "-m", str(gguf_path),
                    "-c", str(LLAMA_CTX_SIZE),
                    "--batch-size", "512",
                    "--ubatch-size", "512",
                    "--cache-type-k", str(LLAMA_CACHE_TYPE),
                    "--cache-type-v", str(LLAMA_CACHE_TYPE),
                    "--no-webui",
                    "-ngl", str(int(os.getenv("LLAMA_NGL","99"))) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else "0",
                    *flags,
                ],
                stdout=subprocess.DEVNULL,
                stderr=(_embedder_log_fh := open(self._log_path(), 'a')),
                cwd=str(_llama_bin_vulkan().parent) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else str(_llama_bin().parent),
            )
            self._embedder_log_fh = _embedder_log_fh
            self._model_key = model_key
            logger.info(f"🚀 llama-server ({model_key}) синхронно запущен, PID={self._process.pid}")
            return True

        except Exception as e:
            logger.error(f"Ошибка запуска llama.cpp: {e}")
            return False

    def _start_sync(self, model_key: str = DEFAULT_EMBEDDING_MODEL) -> bool:
        """Синхронная версия start() — без asyncio, для вызова из run_server().
        
        На Insider: если CPU DLL пропали (Zed сбросил расширение) —
        автоматически качает и патчит бинарник.
        """
        if self.is_alive() and self._model_key == model_key:
            return True

        # Проверяем, не запущен ли уже llama-server на этом порту
        if self._probe_port_sync(self._port):
            logger.info(f"🔌 llama-server уже запущен на порту {self._port}, подключаюсь")
            self._model_key = model_key
            return True

        # На Insider: проверяем наличие CPU DLL и восстанавливаем если надо
        if _IS_INSIDER and sys.platform == 'win32':
            cpu_dll = _llama_bin().parent / 'ggml-cpu-haswell.dll'
            if not cpu_dll.exists():
                logger.warning('⚠️ CPU DLL не найдены — запускаю download_llama_binary()')
                if download_llama_binary():
                    logger.info('✅ llama.cpp восстановлен после авто-загрузки')
                else:
                    logger.error('❌ Не удалось восстановить llama.cpp')
                    return False

        gguf_path = _gguf_path(model_key)
        if not gguf_path.exists():
            logger.error(f"GGUF модель не найдена: {gguf_path}")
            return False

        flags = ["--embedding"] if model_key in ("bge-m3", "qwen3-embedding") else ["--reranking"]

        try:
            self._process = _popen_with_job(
                [
                    str(_llama_bin_vulkan()) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else str(_llama_bin()),
                    "--host", self._host,
                    "--port", str(self._port),
                    "-m", str(gguf_path),
                    "-c", str(LLAMA_CTX_SIZE),
                    "--batch-size", "512",
                    "--ubatch-size", "512",
                    "--cache-type-k", str(LLAMA_CACHE_TYPE),
                    "--cache-type-v", str(LLAMA_CACHE_TYPE),
                    "--no-webui",
                    "-ngl", str(int(os.getenv("LLAMA_NGL","99"))) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else "0",
                                        *flags,
                                    ],
                                    stdout=subprocess.DEVNULL,
                                    stderr=(_embedder_log_fh := open(self._log_path(), 'a')),
                                    cwd=str(_llama_bin_vulkan().parent) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else str(_llama_bin().parent),
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                if sys.platform == "win32" else 0,
            )
            self._embedder_log_fh = _embedder_log_fh
            self._model_key = model_key
            logger.info(f"🚀 llama-server ({model_key}) синхронно запущен, PID={self._process.pid}")
            return True

        except Exception as e:
            logger.error(f"Ошибка синхронного запуска llama.cpp: {e}")
            return False

    async def start_reranker(self) -> bool:
        """Запускает llama-server с --reranking (BGE-M3 на порту RERANK_PORT).
        
        Сначала проверяет, отвечает ли порт /health — если да, используем
        существующий процесс. Иначе запускаем новый.
        """
        if self._reranker_process is not None:
            poll = self._reranker_process.poll()
            if poll is None:
                return True  # уже работает

        # Проверяем, не запущен ли уже reranker на этом порту
        if await self._probe_port(self.RERANK_PORT):
            logger.info(f"🔌 Реренкер уже запущен на порту {self.RERANK_PORT}, подключаюсь")
            return True

        gguf_path = _gguf_path(DEFAULT_RERANKER_MODEL)
        if not gguf_path.exists():
            logger.error(f"Reranker GGUF не найден: {gguf_path}")
            return False

        self._ensure_port_free(self.RERANK_PORT)

        try:
            self._reranker_process = _popen_with_job(
                [
                    str(_llama_bin_vulkan()) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else str(_llama_bin()),
                    "--host", self._host,
                    "--port", str(self.RERANK_PORT),
                    "-m", str(gguf_path),
                    "-c", str(LLAMA_CTX_SIZE),     # 🔒 1024 = 573 MB для BGE-M3
                    "--batch-size", "512",
                    "--ubatch-size", "512",
                    "--cache-type-k", str(LLAMA_CACHE_TYPE), # 🧹 сжатие KV кэша
                    "--cache-type-v", str(LLAMA_CACHE_TYPE), # 🧹 сжатие KV кэша
                    "--no-webui",
                    "-ngl", str(int(os.getenv("LLAMA_NGL","99"))) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else "0",
                    "--reranking",
                ],
                stdout=subprocess.DEVNULL,
                stderr=(_reranker_log_fh := open(self._reranker_log_path(), 'a')),
                cwd=str(_llama_bin_vulkan().parent) if os.getenv("LLAMA_BACKEND","msvc").lower()=="vulkan" else str(_llama_bin().parent),
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                if sys.platform == "win32" else 0,
            )
            self._reranker_log_fh = _reranker_log_fh



            # Ждём /health
            t0 = time.time()
            async with httpx.AsyncClient(timeout=2.0) as client:
                for i in range(self._startup_timeout):
                    await asyncio.sleep(1)
                    try:
                        r = await client.get(f"http://{self._host}:{self.RERANK_PORT}/health")
                        if r.status_code == 200:
                            dt = time.time() - t0
                            logger.info(f"🚀 Reranker (BGE-M3) готов за {dt:.1f}s")
                            return True
                    except Exception as _e:
                        logger.debug(f"Reranker health check: {_e}")
                        pass
            logger.error(f"Reranker не стартовал за {self._startup_timeout}s")
            await self.stop_reranker()
            return False

        except Exception as e:
            logger.error(f"Ошибка запуска reranker: {e}")
            return False

    async def stop_reranker(self):
        """Останавливает reranker."""
        if self._reranker_process:
            try:
                self._reranker_process.terminate()
                self._reranker_process.wait(timeout=5)
            except Exception:
                try:
                    self._reranker_process.kill()
                    self._reranker_process.wait(timeout=2)
                except Exception as _e:
                    logger.warning(f"stop_reranker kill: {_e}")
                    pass
            try:
                if self._reranker_process.stderr:
                    self._reranker_process.stderr.close()
            except Exception as _e:
                logger.warning(f"stop_reranker stderr close: {_e}")
                pass
            # Закрываем файл-объект, созданный при запуске (защита от утечки хэндлов)
            try:
                if self._reranker_log_fh is not None:
                    self._reranker_log_fh.close()
            except Exception as _e:
                logger.warning(f"stop_reranker log_fh close: {_e}")
                pass
            self._reranker_process = None
            logger.info("🛑 Reranker остановлен")

    async def stop(self):
        """Останавливает embedder (reranker не трогаем)."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                    self._process.wait(timeout=2)
                except Exception as _e:
                    logger.warning(f"stop kill: {_e}")
                    pass
            # Закрываем stderr-файл, сохранённый Popen-ом (issue #9: утечка fd)
            try:
                if self._process.stderr:
                    self._process.stderr.close()
            except Exception as _e:
                logger.warning(f"stop stderr close: {_e}")
                pass
            # Закрываем файл-объект, созданный при запуске (защита от утечки хэндлов)
            try:
                if self._embedder_log_fh is not None:
                    self._embedder_log_fh.close()
            except Exception as _e:
                logger.warning(f"stop log_fh close: {_e}")
                pass
            self._process = None
            self._model_key = None
            logger.info("🛑 llama.cpp остановлен")

    def _log_path(self) -> str:
        """Путь к лог-файлу для stderr llama-server."""
        return str(_get_ext_dir() / 'llama_server_stderr.log')

    def _reranker_log_path(self) -> str:
        return str(_get_ext_dir() / 'llama_reranker_stderr.log')

    def _ensure_port_free(self, port: int):
        """Освобождает порт, убивая только процесс llama-server (по команде)."""
        import subprocess as _sp
        # Проверяем, что порт в ожидаемом диапазоне (8080-8090 для llama.cpp)
        if not (8080 <= port <= 8090):
            logger.warning(f"⚠️ Порт {port} вне диапазона llama.cpp (8080-8090), пропускаем")
            return
        try:
            # Шаг 1: находим PID процесса на порту
            try:
                out = _sp.check_output(
                    ['powershell', '-NoProfile', '-Command',
                     f'Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess'],
                    timeout=5, stderr=_sp.DEVNULL
                ).decode().strip()
            except _sp.CalledProcessError:
                out = ""  # порт свободен, это нормально
            for line in out.split('\n'):
                pid = line.strip()
                if not (pid and pid.isdigit() and int(pid) > 0):
                    continue
                # Шаг 2: проверяем CommandLine процесса — убиваем только llama-server
                try:
                    cmd = _sp.check_output(
                        ['powershell', '-NoProfile', '-Command',
                         f'Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = {pid}" | Select-Object -ExpandProperty CommandLine'],
                        timeout=3
                    ).decode().strip().lower()
                    if 'llama-server' not in cmd and 'ggml-rpc-server' not in cmd:
                        logger.warning(f'⏭️ Порт {port} занят процессом PID {pid} (не llama-server), пропускаем')
                        continue
                except Exception:
                    # Не смогли проверить — не убиваем
                    logger.warning(f'⚠️ Не удалось проверить PID {pid} на порту {port}, пропускаем')
                    continue
                # Шаг 3: убиваем
                _sp.run(['taskkill', '/F', '/PID', pid], capture_output=True, timeout=3)
                logger.warning(f'🧹 Убит процесс llama-server PID {pid} (порт {port})')
        except Exception as e:
            logger.warning(f'⚠️ Ошибка при освобождении порта {port}: {e}')

    async def _probe_port(self, port: int) -> bool:
        """Проверяет, отвечает ли порт HTTP (живой ли llama-server)."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(f'http://{self._host}:{port}/health')
                return r.status_code == 200
        except Exception:
            return False

    def _probe_port_sync(self, port: int) -> bool:
        """Синхронная версия _probe_port — для вызова из _start_sync."""
        try:
            r = httpx.get(f'http://{self._host}:{port}/health', timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    def is_alive(self) -> bool:
        """Проверяет, жив ли процесс."""
        if self._process is None:
            return False
        ret = self._process.poll()
        return ret is None

    async def health(self) -> dict:
        """Проверяет здоровье сервера."""
        if not self.is_alive():
            return {"status": "dead", "model": None}
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.base_url}/health")
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "status": "ok",
                        "model": self._model_key,
                        "uptime": data.get("uptime_sec", 0),
                    }
                return {"status": "error", "model": self._model_key}
        except Exception:
            return {"status": "unreachable", "model": self._model_key}

    async def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """Отправляет запрос на эмбеддинги."""
        if self._model_key != "bge-m3":
            # Автоматический рестарт с embedder
            if not await self.start("bge-m3"):
                return None
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{self.base_url}/v1/embeddings",
                    json={"input": texts},
                )
                if r.status_code == 200:
                    data = r.json()
                    return [item["embedding"] for item in data.get("data", [])]
                return None
        except Exception as e:
            logger.debug(f"llama.cpp embed error: {e}")
            return None

    async def rerank(self, query: str, passages: list[str]) -> Optional[list[float]]:
        """Отправляет запрос на реранкинг. Авто-рестарт при idle-выгрузке."""
        if self._reranker_process is None:
            if not await self.start_reranker():
                return None
        self.touch_reranker()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{self.base_url}/v1/rerank",
                    json={"query": query, "documents": passages, "top_n": len(passages)},
                )
                if r.status_code == 200:
                    results = r.json().get("results", [])
                    scores = [0.0] * len(passages)
                    for res in results:
                        idx = res.get("index", 0)
                        # Sigmoid нормализация (llama.cpp возвращает logits)
                        logit = res.get("relevance_score", 0.0)
                        scores[idx] = 1.0 / (1.0 + (2.71828 ** (-logit)))
                    return scores
                return None
        except Exception as e:
            logger.debug(f"llama.cpp rerank error: {e}")
            return None


# ─── Singleton ───────────────────────────────────────────────────

_global_runner: Optional[LlamaRunner] = None
_global_lock = threading.Lock()


def get_global_runner() -> LlamaRunner:
    """Возвращает глобальный LlamaRunner (singleton)."""
    global _global_runner
    with _global_lock:
        if _global_runner is None:
            _global_runner = LlamaRunner()
        return _global_runner


def reset_global_runner():
    """Сброс singleton (для тестов)."""
    global _global_runner
    with _global_lock:
        _global_runner = None


__all__ = [
    # re-exports from llama_install (for backward compat)
    "LLAMA_VERSION",
    "GGUF_MODELS",
    "is_model_downloaded",
    "download_llama_binary",
    "download_gguf_model",
    "is_installed",
    "_get_llama_dir",
    "_get_models_dir",
    "_IS_INSIDER",
    # own symbols
    "LlamaRunner",
    "get_global_runner",
    "reset_global_runner",
]
