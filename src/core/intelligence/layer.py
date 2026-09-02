"""
MSCodeBase Intelligence Layer — Интеллектуальный слой для MCP-сервера

Агрегирует 6 блоков функциональности:
1. Code Intelligence — анализ топологии кода и статический анализ
2. Runtime Intelligence — мониторинг состояния системы и ресурсов
3. Incident Intelligence — история инцидентов и их решения
4. Project Memory — архитектурные решения, технический долг, известные проблемы
5. Hotspot Engine — выявление зон высокого риска в коде
6. Root Cause Engine — предсказание причин сбоев

Все инструменты оптимизированы для работы в условиях жестких таймаутов Zed.
"""

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Импортируем модули ядра и глобальные настройки
from src.core.indexing.indexer import Indexer
from src.core.indexing.symbol_index import SymbolIndex
from src.core.search.engine import Searcher

logger = logging.getLogger("MSCodeBase.Intelligence")
from dataclasses import asdict

from src.core.intelligence.jobs import BackgroundJob, job_manager

# Импорты из декомпозированных модулей
from src.core.intelligence.store import IntelligenceStore, JobHistoryStore
from src.utils.i18n import _


class _AsyncLockAdapter:
    """Адаптирует threading.Lock к async-контексту.

    Один общий lock для sync- и async-методов: asyncio.Lock не защищает
    от sync-доступа (P2-4 audit — смешанная синхронизация IntelligenceStore).
    Захват через asyncio.to_thread, чтобы не блокировать event loop.
    """

    def __init__(self, lock: threading.Lock):
        self._lock = lock

    async def __aenter__(self):
        await asyncio.to_thread(self._lock.acquire)
        return self

    async def __aexit__(self, *exc_info):
        self._lock.release()
        return False

__all__ = [
    "ProjectIntelligenceLayer",
    "register_intelligence_tools",
    "IntelligenceStore",
    "JobHistoryStore",
    "BackgroundJob",
    "job_manager",
]
# =====================================================================
# ОСНОВНОЙ СЛОЙ ПРОЕКТНОГО ИНТЕЛЛЕКТА
# =====================================================================


def _resolve_symbol_count(active_indexer, total_chunks: int) -> int:
    """Безопасно получает количество символов из active Indexer.

    Использует тот же надёжный путь, что и рабочий get_index_status:
    1) читаем живой count через get_symbol_count();
    2) если 0 при непустом индексе — перезагружаем SymbolIndex с диска
       через index_guard (в тот же экземпляр, который и отдаём дальше);
    3) повторно читаем get_symbol_count().
    Возвращает int (0 если недоступно).
    """
    sym_idx = getattr(active_indexer, "_symbol_index", None)
    if sym_idx is None:
        return 0
    try:
        # Живой count (get_stats может отдавать кэш, get_symbol_count — всегда актуально)
        count = sym_idx.get_symbol_count()
        # Принудительная загрузка с диска, если SymbolIndex ещё пуст
        # (cold start / другой экземпляр). Без этого intel_get_runtime_status
        # и get_health_report показывают разные цифры (0 vs 3197).
        if count == 0 and total_chunks > 0:
            guard = getattr(active_indexer, "_index_guard", None)
            if guard is not None:
                try:
                    if guard.load_symbol_index(sym_idx):
                        # reload пишет в тот же sym_idx — читаем повторно
                        count = sym_idx.get_symbol_count()
                except Exception as _e:
                    logger.debug(f"SymbolIndex guard reload failed: {_e}")
        return count
    except Exception as _e:
        logger.debug(f"_resolve_symbol_count failed: {_e}")
        return 0


class ProjectIntelligenceLayer:
    """Интеллектуальный слой проекта.

    Объединяет все 6 блоков ТЗ в единую систему:
    - Code Intelligence: анализ кода без LLM
    - Runtime Intelligence: мониторинг системы
    - Incident Intelligence: история инцидентов
    - Project Memory: архитектурная память
    - Hotspot Engine: зоны риска
    - Root Cause Engine: предсказание причин

    Multi-window (INC-6BCB-v3.1): self.indexer / self.searcher / self.symbol_index
    могут быть self-indexing (если LSP ещё не успел записать bridge). В этом
    случае intel_* методы делают late-resolve через _resolve_active_indexer()
    и возвращают state для ПЕРВОГО non-self-indexing workspace из реестра.
    """

    def __init__(
        self,
        project_path: Path,
        indexer: Indexer,
        searcher: Searcher,
        symbol_index: SymbolIndex,
        services: Optional[Any] = None,
    ):
        self.project_path = project_path
        self.indexer = indexer
        self.searcher = searcher
        self.symbol_index = symbol_index
        # INC-6BCB-v3.1: services нужен для late-resolve когда default indexer
        # оказался self-indexing (например, race LSP↔MCP при cold start).
        self._services = services
        self.store = IntelligenceStore(project_path)
        self.job_history = JobHistoryStore(project_path)
        self._reindex_job_id: Optional[str] = None
        self._reindex_task: Optional[asyncio.Task] = (
            None  # Prevent GC from collecting background reindex
        )
        self._reindex_lock = asyncio.Lock()
        # Единый threading.Lock для sync+async записи в IntelligenceStore
        # (asyncio.Lock не защищает от sync-доступа — см. P2-4 audit).
        self._write_lock = threading.Lock()

    def _resolve_active_indexer(self) -> Any:
        """Динамически резолвит актуальный Indexer из реестра.

        В отличие от self.indexer (закеширован при старте), этот метод
        всегда берёт свежий синглтон из ProjectIndexerRegistry.
        Предотвращает stale-состояние (рецидив INC-001).

        Returns:
            Indexer из реестра, или self.indexer как fallback.
        """
        if self._services is not None:
            try:
                from src.core.di_container import ProjectIndexerRegistry
                from src.core.utils.self_index_guard import _is_self_index_path

                registry = self._services.resolve(ProjectIndexerRegistry)
                # Целенаправленный re-resolve по нормализованному пути проекта,
                # чтобы не смотреть в произвольный (возможно stale) indexer из
                # реестра. ProjectContext использует тот же механизм — консистентность.
                target = Path(self.project_path).resolve()
                if not _is_self_index_path(target):
                    try:
                        return registry.get_indexer(target)
                    except Exception as _e:
                        logger.warning(f"Exception suppressed at layer.py: {_e}")
                        pass
                # Self-indexing — ищем первый non-self-indexing (multi-window fallback)
                return registry.find_first_non_self_indexing(target)
            except Exception as e:
                logger.warning(f"Exception suppressed at layer.py: {e}")

        # Fallback: self.indexer (может быть stale, но лучше чем None)
        if hasattr(self, "indexer") and self.indexer is not None:
            return self.indexer
        return None


    # -----------------------------------------------------------------
    # БЛОК 1. Code Intelligence (Быстрый локальный анализ, < 2 сек)
    # -----------------------------------------------------------------

    async def intel_code_topology(self, symbol_name: str) -> Dict[str, Any]:
        """Агрегированный инструмент: отдает полную картину связей символа.

        Использует SymbolIndex для получения:
        - Графа вызовов (callers и callees)
        - Количества ссылок
        - Статического анализа (мертвый код)
        """
        result = {
            "symbol": symbol_name,
            "latency_ms": 0,
            "definitions": [],
            "call_graph": {"incoming_callers": [], "outgoing_callees": []},
            "references_count": 0,
            "definitions_count": 0,
            "static_analysis": {},
        }

        start = time.perf_counter()
        try:
            sv = self.symbol_index
            if sv is None:
                return result

            # Получаем определения
            defs = sv.search_symbols(symbol_name)
            if defs:
                result["definitions_count"] = len(defs)
                for d in defs:
                    if hasattr(d, "file_path") and hasattr(d, "line"):
                        result["definitions"].append(
                            {
                                "symbol": getattr(d, "symbol", symbol_name),
                                "file": d.file_path,
                                "line": d.line,
                                "kind": "definition",
                            }
                        )

            # Получаем граф вызовов (кто вызывает наш символ)
            call_graph = sv.build_call_graph(symbol_name, depth=2)
            if call_graph:
                callers = call_graph.get("callers", [])
                if callers:
                    # BS-5: build_call_graph отдаёт ключ "symbol", а не "name"
                    # → c.get("name") всегда "" (аудит Bot_snow: symbol='').
                    result["call_graph"]["incoming_callers"] = [
                        {
                            "symbol": c.get("symbol", "") or c.get("name", ""),
                            "file": c.get("file", ""),
                            "line": c.get("line", 0),
                            "kind": "caller",
                        }
                        for c in callers
                        if c.get("symbol") or c.get("name")
                    ]

                callees = call_graph.get("callees", [])
                if callees:
                    result["call_graph"]["outgoing_callees"] = [
                        {
                            "symbol": c.get("symbol", "") or c.get("name", ""),
                            "file": c.get("file", ""),
                            "line": c.get("line", 0),
                            "kind": "callee",
                        }
                        for c in callees
                        if c.get("symbol") or c.get("name")
                    ]

            result["references_count"] = (
                len(result["call_graph"]["incoming_callers"])
                + len(result["call_graph"]["outgoing_callees"])
            )

            # Статический анализ: мёртвый код — только если нет ни входящих,
            # ни исходящих вызовов, но есть определение.
            if result["references_count"] == 0 and result["definitions_count"] > 0:
                result["static_analysis"] = {
                    "potential_dead_code": True,
                    "has_definition": True,
                    "suggestion": "Символ определён но не вызывается (ни входящих, ни исходящих)",
                }

        except Exception as e:
            logger.warning(f"Exception suppressed at layer.py: {e}")

        result["latency_ms"] = int((time.perf_counter() - start) * 1000)
        return result

    # -----------------------------------------------------------------
    # БЛОК 2. Runtime Intelligence (Мониторинг системы)
    # -----------------------------------------------------------------

    @staticmethod
    def _get_process_ram(pid: int) -> int:
        """RSS процесса в MB через Windows API (psapi.dll / kernel32).

        Замена wmic (удалён в Win11 25H2 KB5067470).
        Использует GetProcessMemoryInfo — тот же паттерн что в
        resource_monitor.py::_get_rss_windows(), адаптированный для
        внешних PID через OpenProcess.
        """
        if os.name != "nt":
            return 0
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

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)

            if pid == os.getpid():
                handle = ctypes.windll.kernel32.GetCurrentProcess()
                own_process = True
            else:
                handle = ctypes.windll.kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION, False, pid
                )
                own_process = False
                if not handle:
                    return 0

            try:
                try:
                    psapi = ctypes.WinDLL("psapi.dll", use_last_error=True)
                    _gpmi = psapi.GetProcessMemoryInfo
                    _gpmi.argtypes = [
                        wintypes.HANDLE,
                        ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                        wintypes.DWORD,
                    ]
                    _gpmi.restype = wintypes.BOOL
                    if _gpmi(handle, ctypes.byref(counters), counters.cb):
                        return counters.WorkingSetSize // (1024 * 1024)
                except Exception:
                    pass
                if ctypes.windll.kernel32.GetProcessMemoryInfo(
                    handle, ctypes.byref(counters), counters.cb,
                ):
                    return counters.WorkingSetSize // (1024 * 1024)
            finally:
                if not own_process:
                    ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass
        return 0

    @staticmethod
    def _find_pid(port: str) -> int:
        """Ищет PID процесса по порту (cross-platform, без shell).

        netstat (Windows) / ss (Linux). psutil не используется — см. WS9
        (psutil не объявлен в зависимостях и не установлен в venv;
        импорт был guarded, но мёртвой веткой).
        """
        try:
            port_int = int(port)
        except (ValueError, TypeError):
            return 0

        import sys as _sys

        try:
            if _sys.platform == "win32":
                out = subprocess.check_output(
                    ["netstat", "-ano"], timeout=3,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ).decode("utf-8", errors="replace")
                for line in out.splitlines():
                    if f":{port_int}" in line and "LISTENING" in line:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            return int(parts[4])
            else:
                out = subprocess.check_output(
                    ["ss", "-ltnp"], timeout=3
                ).decode("utf-8", errors="replace")
                import re as _re

                for line in out.splitlines():
                    if f":{port_int}" in line and "LISTEN" in line:
                        m = _re.search(r"pid=(\d+)", line)
                        if m:
                            return int(m.group(1))
        except (OSError, subprocess.TimeoutExpired,
                subprocess.CalledProcessError, ValueError, IndexError):
            pass
        return 0

    @staticmethod
    def _get_ram_by_port(port: str) -> int:
        pid = ProjectIntelligenceLayer._find_pid(port)
        if pid:
            return ProjectIntelligenceLayer._get_process_ram(pid)
        return 0

    @staticmethod
    def _get_total_ram() -> int:
        total = ProjectIntelligenceLayer._get_process_ram(os.getpid())
        try:
            from src.config.settings import get_config
            cfg = get_config()
            ports = [str(cfg.embedding.llama_cpp_port), str(cfg.embedding.reranker_port)]
        except Exception:
            ports = ['8080', '8081']
        for port in ports:
            total += ProjectIntelligenceLayer._get_ram_by_port(port)
        return total

    async def intel_get_runtime_status(self) -> Dict[str, Any]:
        """Агрегированный статус здоровья рантайма, провайдеров и индексов.

        Заменяет 3 отдельных вызова: get_index_status + watcher_status + health проверка.

        INC-6BCB-v3.1: late-resolve active indexer. Если self.indexer = self-indexing
        (LSP не успел записать bridge), ищет non-self-indexing в реестре.
        """
        try:

            # INC-6BCB-v3.1: late-resolve.
            active_indexer = self._resolve_active_indexer()
            # get_status() — СИНХРОННЫЙ и может блокировать (lock БД / stale-scan).
            # Инцидент 2026-08-25: full reindex держал _write_lock ~7.5 мин,
            # get_status() на loop-потоке заморозил ВСЕ MCP-вызовы (таймауты
            # вкл. debug_runtime_passport). Выносим в поток: loop свободен,
            # а IndexStatusReporter сам fast-fail-ит при is_reindexing=True.
            status = (
                await asyncio.to_thread(active_indexer.get_status)
                if hasattr(active_indexer, "get_status")
                else {}
            )
            total_chunks = (
                status.get("total_chunks", 0) if isinstance(status, dict) else 0
            )
            total_files = (
                status.get("total_files", 0) if isinstance(status, dict) else 0
            )

            # Reindex-состояние (Вариант А, 2026-08-25): при is_reindexing=True
            # get_status() возвращает кэш + status="reindexing". Пробрасываем
            # флаг и прогресс в index_telemetry, чтобы агент видел «🔄 Reindex
            # в процессе (N%)» вместо ложного «0 chunks» (live-прогон показал:
            # во время full reindex статус врал «индекс пуст» → агент мог
            # запустить ненужный второй reindex).
            _reindexing = bool(
                isinstance(status, dict) and status.get("reindex_in_progress") is True
            )
            _reindex_progress_pct = None
            _reindex_eta_sec = None
            if _reindexing:
                try:
                    _job_id = self.get_active_reindex_job_id()
                    if _job_id:
                        _job = job_manager.get_job(_job_id)
                        if _job and _job.status == "running":
                            _enriched = self._enrich_job_response(_job)
                            _reindex_progress_pct = round(_job.progress * 100)
                            _reindex_eta_sec = _enriched.get("estimated_seconds")
                except Exception as _reidx_err:  # noqa: BLE001 — статус не роняем
                    logger.debug(f"reindex progress enrich failed: {_reidx_err}")

            # Project path (может быть != self.project_path если был fallback).
            active_path = (
                str(active_indexer.project_path)
                if hasattr(active_indexer, "project_path")
                else "unknown"
            )

            # Реальный опрос провайдеров вместо хардкода
            _lm_online = False
            try:
                from src.config.settings import get_config as _get_cfg
                _cfg = _get_cfg()
                _llama_port_str = str(_cfg.embedding.llama_cpp_port)
                _reranker_port_str = str(_cfg.embedding.reranker_port)
                _lm_port_str = str(_cfg.embedding.lm_studio_port)
            except Exception:
                _llama_port_str = "8080"
                _reranker_port_str = "8081"
                _lm_port_str = "1234"
            _llama_online = False
            # Динамическое сканирование ONNX модели (как в _detect_model_dir RemoteEmbedder)
            from src.core.artifact_paths import get_onnx_models_base

            _search_paths = [
                self.project_path / ".codebase_models" / "onnx",
                Path(__file__).resolve().parent.parent.parent / ".codebase_models" / "onnx",
                get_onnx_models_base(),
            ]
            _onnx_loaded = False
            for _base in _search_paths:
                if not _base.exists():
                    continue
                for _subdir in sorted(_base.iterdir()):
                    # Пропускаем reranker
                    if _subdir.name.startswith("reranker-"):
                        continue
                    if (_subdir / "model_quantized.onnx").exists() or (_subdir / "model.onnx").exists():
                        _onnx_loaded = True
                        break
                if _onnx_loaded:
                    break
            try:
                import socket as _sock

                _s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
                _s.settimeout(0.5)
                if _s.connect_ex(("127.0.0.1", int(_lm_port_str))) == 0:
                    _lm_online = True
                _s.close()
                # Проверяем llama.cpp (Qwen3 на порту 8080)
                _s2 = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
                _s2.settimeout(0.5)
                _llama_port = int(_llama_port_str)
                if _s2.connect_ex(("127.0.0.1", _llama_port)) == 0:
                    _llama_online = True
                _s2.close()
            except (OSError, Exception) as _e:
                logger.debug(f"Проверка портов провайдеров: {_e}")

            # Определяем активного провайдера (llama_cpp > lm_studio > onnx)
            if _llama_online:
                _active_provider = "llama_cpp"
            elif _lm_online:
                _active_provider = "lm_studio"
            else:
                _active_provider = "onnx"

            return {
                "embedding_provider": _active_provider,
                "provider_status": {
                    "llama_cpp_at_8080": "online" if _llama_online else "offline",
                    "lm_studio_at_1234": "online" if _lm_online else "offline",
                    "ollama_at_11434": "offline",
                    "onnx_local_engine": "loaded_and_ready"
                    if _onnx_loaded
                    else "not_loaded",
                },
                "project_path": active_path,  # INC-6BCB-v3.1: показываем active
                "project_path_warning": (
                    "Active indexer != default project_path (late-resolve)"
                    + "; LSP bridge was empty at MCP startup"
                )
                if active_path != str(self.project_path)
                else None,
                "index_telemetry": {
                    "db_isolated_path": str(active_indexer.db_path)
                    if hasattr(active_indexer, "db_path")
                    else "unknown",
                    # Задача 4/5: file-contract для агента (AGENTS.md §0)
                    "progress_file": str(
                        __import__(
                            "src.core.artifact_paths",
                            fromlist=["get_progress_file"],
                        ).get_progress_file(active_indexer.project_path)
                    )
                    if hasattr(active_indexer, "project_path")
                    else "unknown",
                    "index_healthy": total_chunks > 0,
                    "queue_depth": 0,
                    "total_chunks": total_chunks,
                    "unique_files": status.get("unique_files", 0)
                    if isinstance(status, dict)
                    else 0,
                    "total_files": total_files,
                    # INC-6BCB-v3.1: динамический re-resolve через реестр.
                    # Если SymbolIndex пуст при непустом индексе — авто-загрузка с диска.
                    "symbol_index_count": _resolve_symbol_count(
                        active_indexer, total_chunks
                    ),
                    # Reindex-состояние для агента (Вариант А): вместо вранья
                    # «0 chunks» при переиндексации показываем честный статус
                    # и прогресс, чтобы агент ждал, а не запускал 2-й reindex.
                    "status": "reindexing"
                    if _reindexing
                    else ("active" if total_chunks > 0 else "empty"),
                    "reindex_in_progress": _reindexing,
                    "reindex_progress_pct": _reindex_progress_pct,
                    "reindex_eta_sec": _reindex_eta_sec,
                },
                # Consistency Engine (WS2): состояния артефактов — аддитивно.
                "consistency": {
                    k: {
                        "state": v["state"],
                        "age_sec": v["age_sec"],
                        "reason": v.get("reason", ""),
                    }
                    for k, v in (
                        __import__(
                            "src.core.consistency",
                            fromlist=["get_consistency_tracker"],
                        )
                        .get_consistency_tracker()
                        .get_all()
                        .items()
                    )
                },
                # Trust Boundary (WS1): уровень доверия к активному корню.
                "trust": __import__(
                    "src.core.trust_boundary", fromlist=["trust_report"]
                ).trust_report(Path(active_path) if active_path != "unknown" else Path.cwd()),
                "startup_diagnostics": self._build_startup_diagnostics(active_indexer),
                "resource_usage": {
                    "process_pid": os.getpid(),
                    "async_loop_tasks": len(asyncio.all_tasks()),
                    "process_ram_mb": ProjectIntelligenceLayer._get_process_ram(os.getpid()),
                    "llama_qwen_pid": ProjectIntelligenceLayer._find_pid(_llama_port_str),
                    "llama_qwen_ram": ProjectIntelligenceLayer._get_ram_by_port(_llama_port_str),
                    "llama_rerank_ram": ProjectIntelligenceLayer._get_ram_by_port(_reranker_port_str),
                    "total_ram_mb": ProjectIntelligenceLayer._get_total_ram(),
                },
                "model_info": self._get_embedder_model_info(),
                "_debug": str(type(active_indexer)),
            }
        except Exception as e:
            logger.error(f"Ошибка получения статуса: {e}")
            return {"status": "error", "detail": str(e)}

    def _build_startup_diagnostics(self, active_indexer) -> dict:
        """Человекочитаемая диагностика lock-а и БД (Задача 3/5).

        Read-only: не захватывает lock, не трогает файлы. Возвращает
        человеческий текст с действием вместо Rust-трейса.
        """
        from src.core.indexing.startup_diagnostics import build_startup_report

        try:
            db_path = getattr(active_indexer, "db_path", None)
            if db_path is None:
                return {"available": False, "report": "Индексатор не инициализирован."}
            dbm = getattr(active_indexer, "db_manager", None)
            lock_path = (
                getattr(dbm, "_pid_lock_path", None)
                if dbm is not None
                else db_path / ".write_lock"
            )
            report = build_startup_report(
                db_path=db_path,
                lock_path=lock_path,
                current_pid=os.getpid(),
            )
            return {
                "available": True,
                "lock_state": report.lock.state,
                "db_state": report.db.state,
                "report": report.to_human(),
            }
        except Exception as _diag_err:
            logger.debug(f"startup_diagnostics failed: {_diag_err}")
            return {"available": False, "report": f"Диагностика недоступна: {_diag_err}"}

    def _get_embedder_model_info(self) -> dict:
        """Get real model info from the global embedder singleton.

        Сначала пытается получить embedder из DI-контейнера (живой синглтон),
        иначе создаёт временный экземпляр для диагностики.
        """
        try:
            emb = self._resolve_active_embedder()
            info = emb.get_model_info()
            return {
                "provider": info.get("provider", "unknown"),
                "model": info.get("model", "unknown"),
                "dimension": info.get("dimension", 0),
            }
        except Exception:
            return {"provider": "unknown", "model": "unknown", "dimension": 0}

    def _resolve_active_embedder(self):
        """Возвращает РЕАЛЬНЫЙ инстанс embedder из DI (единая правда BS-8).

        Аудит Bot_snow BS-8: intel_get_telemetry создавал собственный
        `RemoteEmbedder()` вместо resolve из DI → новый инстанс мог иметь
        mode="unknown" (инициализация фоновая) → телеметрия показывала
        «Provider: unknown», пока health/runtime — «llama.cpp». Теперь все
        инструменты читают один и тот же объект.
        """
        from src.providers.embedder.remote_embedder import RemoteEmbedder

        if self._services is not None:
            try:
                return self._services.resolve(RemoteEmbedder)
            except Exception:
                pass
        return RemoteEmbedder()

    # -----------------------------------------------------------------
    # БЛОК Reindex (Фоновая переиндексация)
    # -----------------------------------------------------------------

    async def trigger_async_reindex(self) -> str:
        """Двухфазная операция: запускает асинхронную переиндексацию.

        Предотвращает конкурентные вызовы: если reindex уже запущен,
        возвращает существующий job_id вместо создания нового.

        Возвращает job_id мгновенно, задача выполняется в фоне.
        Zed может опрашивать статус через intel_get_job_status.
        """
        async with self._reindex_lock:
            # Если reindex уже запущен — возвращаем существующий job_id
            if self._reindex_job_id:
                existing = job_manager.get_job(self._reindex_job_id)
                if existing and existing.status == "running":
                    logger.info(
                        f"Reindex уже запущен: {self._reindex_job_id}, возвращаем существующий"
                    )
                    return self._reindex_job_id

            job_id = job_manager.create_job("full_reindex")
            self._reindex_job_id = job_id

            # Consistency Engine (WS2): переиндексация начата.
            try:
                from src.core.consistency import get_consistency_tracker

                get_consistency_tracker().mark_updating(
                    "index", "reindex job started"
                )
            except Exception:  # noqa: BLE001 — консистентность не блокирует индексацию
                pass

        async def _run_reindex_job():
            job = job_manager.get_job(job_id)
            if not job:
                return

            job.status = "running"
            job.progress = 0.0

            try:
                # Guard (AGENTS.md §5.13 / chunkhound SerialDatabaseExecutor):
                # запрещаем concurrent search читать БД во время переиндексации
                # (включая фазу Finalizing: optimize()/create_index()), иначе
                # LanceDB бросает 'Not found' на удаляемых .lance-файлах.
                _dbm = getattr(self.indexer, "db_manager", None)
                if _dbm is not None and hasattr(_dbm, "set_reindexing"):
                    _dbm.set_reindexing()

                # Симулируем прогресс для Zed UI
                job.progress = 0.1

                # Вызываем индексацию проекта
                if hasattr(self.indexer, "index_project"):
                    from src.core.indexing.file_guard import FileGuard

                    project_file_guard = FileGuard(self.project_path)
                    self.indexer.file_guard = project_file_guard

                    # Если метод синхронный, запускаем в executor
                    loop = asyncio.get_event_loop()

                    # Создаём progress_callback, который маппит прогресс индексера (0..1) на шкалу job'а (0.1..0.8)
                    def _index_progress_callback(
                        current_file, files_done, files_total, phase
                    ):
                        if files_total > 0:
                            ratio = files_done / files_total
                            if phase == "embedding":
                                job.progress = round(0.5 + ratio * 0.3, 2)
                            elif phase in ("parsing", "scanning"):
                                job.progress = round(0.1 + ratio * 0.4, 2)
                            else:
                                job.progress = round(0.1 + ratio * 0.7, 2)

                    future = loop.run_in_executor(
                        None,
                        self.indexer.index_project,
                        self.project_path,
                        _index_progress_callback,
                    )
                    job.progress = 0.1
                    indexed_count = await future

                    # Сохраняем размер проекта (кол-во индексированных файлов)
                    job.project_size = indexed_count if indexed_count else None

                    # Символьная индексация отключена — Tree-sitter зависает
                    # на C-уровне, asyncio.wait_for не прерывает поток.
                    job.progress = 0.8

                job.progress = 1.0
                job.status = "completed"
                job.ended_at = time.time()
                job.result = {"files_processed": "Индексация завершена", "status": "ok"}

                # State machine (косметический баг 2026-08-26): get_indexer()
                # ставит INDEXING при пустом индексе; после успешного reindex
                # обязателен перевод в READY — иначе паспорт вечно показывает
                # «Project State: INDEXING» и wait_until_ready ждёт до таймаута.
                try:
                    _reg = (
                        self._services.resolve(
                            __import__(
                                "src.core.di_container",
                                fromlist=["ProjectIndexerRegistry"],
                            ).ProjectIndexerRegistry
                        )
                        if self._services is not None
                        else None
                    )
                    if _reg is not None and hasattr(_reg, "set_state"):
                        _reg.set_state(
                            self.project_path,
                            __import__(
                                "src.core.indexing.project_indexer_registry",
                                fromlist=["ProjectState"],
                            ).ProjectState.READY,
                        )
                except Exception as _state_err:  # noqa: BLE001 — статус не роняем
                    logger.debug(f"reindex set_state READY failed: {_state_err}")

                # Consistency Engine (WS2): индексация завершена успешно.
                try:
                    from src.core.consistency import get_consistency_tracker

                    _tracker = get_consistency_tracker()
                    _tracker.mark_consistent("index", "reindex completed")
                    _tracker.mark_consistent("graph", "reindex completed")
                    _tracker.mark_consistent("symbols", "reindex completed")
                except Exception:  # noqa: BLE001
                    pass

                # Сохраняем в историю для адаптивного ETA (только если есть размер)
                if job.project_size:
                    duration = (job.ended_at or time.time()) - job.started_at
                    self.job_history.append_record(job.project_size, duration)

                # 🔄 Авто-обновление документации после реиндекса.
                # BS-11-класс: update_all (generate_docs+README+KNOWN_ISSUES, rglob по docs/)
                # — синхронная работа на минуты; в main loop заблокировала бы ВСЕ запросы
                # (инцидент 2026-08-13: сервер недоступен ~13 мин, таймауты, Zed убил процесс).
                # Фикс: asyncio.to_thread (как run_full_diagnostic в intel_predict_root_cause)
                # + wait_for(300) — loop свободен, документы обновляются в фоне.
                try:
                    from src.core.auto_doc_updater import AutoDocUpdater

                    updater = AutoDocUpdater()
                    doc_result = await asyncio.wait_for(
                        asyncio.to_thread(
                            updater.update_all, str(self.project_path)
                        ),
                        timeout=300,
                    )
                    logger.info("Auto-doc after reindex:\n%s", doc_result)
                except asyncio.TimeoutError:
                    logger.warning("Auto-doc after reindex timed out (300s) — пропущено")
                except Exception as doc_e:  # noqa: BLE001 — фоновая задача не роняет индексацию
                    logger.warning("Auto-doc after reindex failed: %s", doc_e)

            except Exception as e:
                logger.warning(f"Exception suppressed at layer.py: {e}")
                job.status = "failed"
                job.error = str(e)
                job.ended_at = time.time()
                logger.error(f"Ошибка фоновой индексации: {e}")
                # Consistency Engine (WS2): индексация упала — индекс недоверен.
                try:
                    from src.core.consistency import get_consistency_tracker

                    get_consistency_tracker().mark_corrupted(
                        "index", f"reindex failed: {e}"
                    )
                except Exception:  # noqa: BLE001
                    pass
            finally:
                # Снимаем guard в любом случае (успех/ошибка/таймаут),
                # чтобы search снова заработал после завершения reindex.
                _dbm = getattr(self.indexer, "db_manager", None)
                if _dbm is not None and hasattr(_dbm, "clear_reindexing"):
                    _dbm.clear_reindexing()
                # Очищаем активный job_id, чтобы разрешить следующий reindex
                self._reindex_job_id = None
                self._reindex_task = None

        self._reindex_task = asyncio.create_task(_run_reindex_job())
        return job_id

    def get_active_reindex_job_id(self) -> Optional[str]:
        """Возвращает ID активного reindex job'а или None."""
        if self._reindex_job_id:
            job = job_manager.get_job(self._reindex_job_id)
            if job and job.status == "running":
                return self._reindex_job_id
        return None

    # -----------------------------------------------------------------
    # БЛОК 3. Incident Intelligence (Локальная база сбоев)
    # -----------------------------------------------------------------

    async def intel_log_incident(
        self,
        component: str,
        symptom: str,
        root_cause: str,
        fix: str,
        success: bool,
    ) -> str:
        """Фиксирует инцидент/баг в истории проекта."""
        async with _AsyncLockAdapter(self._write_lock):
            incidents = self.store.load_incidents()
            incident_id = f"INC-{uuid.uuid4().hex[:4].upper()}"

            new_incident = {
                "incident_id": incident_id,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "component": component,
                "symptom": symptom,
                "root_cause": root_cause,
                "fix": fix,
                "success": success,
            }
        incidents.append(new_incident)
        self.store.save_incidents(incidents)
        logger.info(f"Инцидент {incident_id} записан: {component} — {symptom[:50]}...")
        return _("Incident {incident_id} stored.", incident_id=incident_id)

    async def intel_analyze_incident(self, error_message: str) -> Dict[str, Any]:
        """Анализ инцидента: ищет похожие в истории + search_code как fallback."""
        incidents = self.store.load_incidents()
        matches = []

        # 1. Search incident store (existing logic)
        for inc in incidents:
            symptom = inc.get("symptom", "")
            root_cause = inc.get("root_cause", "")
            fix = inc.get("fix", "")
            keywords = set(error_message.lower().split())
            symptom_words = set(symptom.lower().split())
            overlap = keywords & symptom_words
            if len(overlap) >= 2:
                matches.append(
                    {
                        "incident_id": inc["incident_id"],
                        "symptom": symptom,
                        "root_cause": root_cause,
                        "fix": fix,
                        "match_score": len(overlap) / max(len(keywords), 1),
                        "source": "incident_store",
                    }
                )

        # 2. If no good matches, use search_code as fallback
        if not matches or (matches and matches[0]["match_score"] < 0.3):
            try:
                # ARCH-03 (направление core←mcp): grep_fallback перенесён в core
                # (src/core/utils/grep_fallback.py), чтобы core не импортировал mcp.
                from src.core.utils.grep_fallback import grep_fallback as _grep_fallback
                search_results = _grep_fallback(error_message)
                if search_results:
                    # Extract relevant code snippets
                    lines = search_results.strip().split("\n")[:5]
                    for line in lines:
                        if ":" in line:
                            parts = line.split(":", 2)
                            if len(parts) >= 3:
                                import hashlib as _hashlib

                                # Детерминированный ID: blake2b вместо hash()
                                # (hash() рандомизирован через PYTHONHASHSEED)
                                _digest = int(
                                    _hashlib.blake2b(
                                        line.encode("utf-8"), digest_size=8
                                    ).hexdigest(),
                                    16,
                                )
                                matches.append(
                                    {
                                        "incident_id": f"code_{_digest % 10000}",
                                        "symptom": parts[2][:200],
                                        "root_cause": f"Found in code: {parts[0]}:{parts[1]}",
                                        "fix": "See code reference above",
                                        "match_score": 0.5,
                                        "source": "search_code",
                                    }
                                )
            except Exception:
                pass  # search_code not available

        matches.sort(key=lambda x: x["match_score"], reverse=True)
        return {
            "error_message": error_message,
            "matches_found": len(matches),
            "similar_incidents": matches[:5],
        }

    async def intel_get_project_memory(
        self,
        include_retracted: bool = False,
        verify_on_read: bool = True,
        project_root: Optional[str] = None,
    ) -> Tuple[Dict[str, List[Dict]], Dict[str, Any]]:
        """Получить полную карту памяти проекта + ресипт VOR-проверки.

        R3TF (2026-08-26, multi-window): project_root позволяет читать память
        ЦЕЛЕВОГО проекта, а не только self.project_path (CWD/DI). layer — core-
        модуль, не может импортировать mcp-резолвер active/CWD; явный project_root
        пробрасывается из тула (mcp-слой), который резолвит проект сам.
        Если project_root не задан — используется self.store (поведение до фикса).

        ADR-0002: REFUTED-узлы скрыты по умолчанию; include_retracted=True
        возвращает их для аудита и отладки.
        ADR-0003: verify_on_read=True (по умолчанию) — ACTIVE-узлы проходят
        ленивую проверку якорей (file/import/env/pkg) при извлечении: прямые
        отрицательные тесты -> REFUTED (SILENT_ABSENCE_ON_READ), найденные
        -> VERIFIED, непроверяемые (без якорей) -> остаются ACTIVE с флагом
        verification="no_anchors" для выдачи агенту (ADR-0003: предохранитель).
        Непроверенные из-за бюджета узлы помечаются verification="budget_exceeded"
        — их статус унаследован от прошлых циклов, а не подтверждён в этом чтении.

        Returns:
            (memory, stats). stats — ресипт проверки (пол Тома): nodes_seen/
            checked/budget_exceeded/latency_ms — потребитель сам видит
            checked/total и решает, преждевременно ли измерение.
            stats["starved_nodes"] — узлы, видимые >=2 циклов, но ни разу не
            проверенные (MATCHED>0, DELIVERED=0): систематическое голодание
            по бюджету, не разовый вылет (Том, 2026-08-16).
            stats["metrics"] — store.memory_metrics(): распределение статусов
            и false_retraction_rate (снятие метрик без отдельного тула).
        """
        # R3TF: выбираем store целевого проекта при явном project_root.
        target_path: Path = self.project_path
        store: "IntelligenceStore" = self.store
        if project_root and project_root.strip():
            try:
                target_path = Path(project_root).resolve()
                store = IntelligenceStore(target_path)
            except Exception:
                logger.warning(
                    "intel_get_project_memory: не удалось открыть store для %s, "
                    "используется self.store (%s)",
                    project_root,
                    self.project_path,
                )
                target_path = self.project_path
                store = self.store

        memory = store.load_memory(include_retracted=include_retracted)
        if verify_on_read and not include_retracted:
            from src.core.intelligence.verify_on_read import get_verifier

            resolver = None
            si = getattr(self, "symbol_index", None)
            if si is not None:
                def _symbol_resolver(qname: str) -> Optional[bool]:
                    # Freshness-gated symbol resolver (issue #21/#22, commit B).
                    # A symbol anchor can REFUTE (False) ONLY when the index is
                    # provably fresh: its recorded build_head equals the live
                    # HEAD and the working tree is clean. Any other state
                    # (legacy index w/o build_head, HEAD mismatch, non-git repo,
                    # dirty tree, resolver failure) -> None (INCONCLUSIVE) —
                    # absence is then UNVERIFIABLE, never REFUTED.
                    # Returns: True (referent on disk -> VERIFIED),
                    #          False (fresh index, absent -> honest REFUTED),
                    #          None (freshness unverifiable -> INCONCLUSIVE).
                    try:
                        build_fn = getattr(si, "build_head", None)
                        build_head = build_fn() if build_fn is not None else None
                        if build_head is None:
                            return None  # legacy/in-memory index -> unknown
                        from src.core.intelligence.verify_on_read import (
                            evaluate_freshness,
                            resolve_head_dirty,
                        )
                        cur = resolve_head_dirty(self.project_path)
                        if cur is None:
                            return None  # non-git / unresolvable HEAD
                        cur_head, dirty = cur
                        if not evaluate_freshness(build_head, cur_head, dirty):
                            return None  # mismatch / dirty / unknown -> inconclusive
                        defs = si.find_definitions(qname)
                        if defs is None:
                            return None
                        for d in defs:
                            fp = getattr(d, "file_path", None) or getattr(d, "file", None)
                            if fp and Path(fp).exists():
                                return True
                        # Fresh index + clean tree: absence is real evidence.
                        return False
                    except Exception:
                        # Graph/index/git unavailable -> unverifiable -> INCONCLUSIVE.
                        return None

                resolver = _symbol_resolver

            verifier = get_verifier(target_path, store, self._write_lock, symbol_resolver=resolver)
            memory, stats = await asyncio.to_thread(verifier.run, memory)
            # Помечаем INCONCLUSIVE узлы флагом для выдачи агенту
            inconclusive_ids = set(stats.get("inconclusive_nodes", []))
            if inconclusive_ids:
                for section, nodes in memory.items():
                    for node in nodes:
                        if node.get("node_id") in inconclusive_ids:
                            node.setdefault("verification", "no_anchors")
            # Том (MATCHED/DELIVERED): узлы, видимые N циклов, но ни разу не
            # проверенные — систематическое голодание по бюджету. Флаг ставится
            # ДО budget_exceeded (setdefault не перетирает): кумулятивный сигнал
            # информативнее разового вылета в этом проходе.
            starved_ids = set(stats.get("starved_nodes", []))
            if starved_ids:
                for section, nodes in memory.items():
                    for node in nodes:
                        if node.get("node_id") in starved_ids:
                            node.setdefault("verification", "starved")
            # Пол Тома: узлы, не проверенные в этом цикле из-за бюджета,
            # несут устаревший статус — помечаем явно, чтобы потребитель не
            # принял вчерашний VERIFIED за свежую проверку.
            budget_exceeded_ids = set(stats.get("budget_exceeded_nodes", []))
            if budget_exceeded_ids:
                for section, nodes in memory.items():
                    for node in nodes:
                        if node.get("node_id") in budget_exceeded_ids:
                            node.setdefault("verification", "budget_exceeded")
        else:
            stats = {"verify_on_read": False}
        stats["metrics"] = store.memory_metrics()
        return memory, stats

    def _load_flat_memory_nodes(self) -> List[Dict]:
        """Загружает project_memory.json как плоский список узлов.

        Мигрирует legacy dict-формат {"section": [...]} в плоский список
        (ADR-0002: старые записи без статуса получают status=ACTIVE).
        """
        nodes = self.store._load_json("project_memory.json")
        if isinstance(nodes, dict):
            flat = []
            for sec_name, sec_items in nodes.items():
                for item in sec_items:
                    flat.append(
                        {
                            "node_id": f"NODE-{uuid.uuid4().hex[:6]}",
                            "section": sec_name,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "data": item if isinstance(item, dict) else {"value": item},
                            "status": "ACTIVE",
                        }
                    )
            nodes = flat
        return nodes

    async def intel_add_memory_node(
        self, section: str, data_json: str, status: str = "ACTIVE"
    ) -> str:
        """Добавить запись в проектную память.

        Секции: 'adrs', 'known_issues', 'tech_debt', 'failed_attempts'
        status (ADR-0002): 'ACTIVE' (по умолчанию — записано, не проверено)
        или 'VERIFIED' (факт проверен против кода). 'REFUTED' при записи
        недоступен — только через intel_retract_memory_node.
        """
        if section not in ("adrs", "known_issues", "tech_debt", "failed_attempts"):
            return _(
                "Неизвестная секция: {section}. Допустимые: adrs, known_issues, tech_debt, failed_attempts",
                section=section,
            )
        if status not in ("ACTIVE", "VERIFIED"):
            if status == "REFUTED":
                return _(
                    "Статус REFUTED устанавливается только через intel_retract_memory_node(node_id, reason)."
                )
            return _(
                "Недопустимый статус: {status}. Допустимые: ACTIVE, VERIFIED.",
                status=status,
            )

        try:
            data = json.loads(data_json)
        except json.JSONDecodeError as e:
            return _("JSON parse error: {error}", error=e)

        # ADR-0003/0005: write-time anchor capture — типизированные якоря из синтаксиса
        # claim/data (file:/import/env/pkg), чтобы verify-on-read проверял ТОЧНЫЕ якоря,
        # а не голые токены (урок Exp 1-V: наивная типизация -> 7/25 ложных REFUTED).
        if isinstance(data, dict):
            from src.core.intelligence.verify_on_read import extract_anchors

            captured = [a.to_dict() for a in extract_anchors(
                {"data": data}, project_root=self.project_path
            )]
            if captured:
                data["anchors"] = captured

        new_node = {
            "node_id": f"NODE-{uuid.uuid4().hex[:6]}",
            "section": section,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data": data,
            "status": status,
        }
        # Весь read-modify-write — под одним локом (ADR-0002: два писателя —
        # add и retract — не должны терять аппенды при конкуренции).
        async with _AsyncLockAdapter(self._write_lock):
            nodes = self._load_flat_memory_nodes()
            nodes.append(new_node)
            self.store._save_json("project_memory.json", nodes)
        logger.info(f"Запись {new_node['node_id']} добавлена в {section} ({status})")
        return _(
            "Запись {node_id} добавлена в раздел '{section}' (status: {status}).",
            node_id=new_node["node_id"],
            section=section,
            status=status,
        )

    async def intel_retract_memory_node(self, node_id: str, reason: str) -> str:
        """Отозвать узел проектной памяти (ADR-0002).

        Переводит узел (ACTIVE или VERIFIED) в REFUTED — терминальный статус —
        и фиксирует причину отзыва (retract_reason) и время (retracted_at).
        Отзыв без непустой причины невозможен; повторный отзыв запрещён
        (первичная причина отзыва сохраняется).
        """
        reason = reason.strip() if reason else ""
        if not reason:
            return _(
                "Отзыв требует непустую причину (reason) — память не отзывается молча."
            )
        async with _AsyncLockAdapter(self._write_lock):
            nodes = self._load_flat_memory_nodes()
            for n in nodes:
                if n.get("node_id") == node_id:
                    if n.get("status") == "REFUTED":
                        return _("Узел {node_id} уже отозван.", node_id=node_id)
                    n["status"] = "REFUTED"
                    n["retract_reason"] = reason
                    n["retracted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    # ADR-0004: каскад на зависимые узлы (data.depends_on /
                    # superseded_by) — контаминация не распространяется на
                    # downstream. В том же RMW под локом (TOCTOU-инвариант).
                    from src.core.intelligence.propagation_engine import PropagationEngine

                    by_id = {x.get("node_id"): x for x in nodes if isinstance(x, dict)}
                    cascade = PropagationEngine.retract_cascade(
                        nodes, node_id, reason
                    )
                    for tr in cascade:
                        dep = by_id.get(tr["node_id"])
                        if dep is None:
                            continue
                        dep["status"] = "REFUTED"
                        dep["retract_reason"] = tr["retract_reason"]
                        dep["retracted_at"] = n["retracted_at"]
                        dep["retract_source"] = tr["retract_source"]
                        logger.info(
                            "propagation: REFUTED %s (зависит от %s)",
                            tr["node_id"],
                            node_id,
                        )
                    self.store._save_json("project_memory.json", nodes)
                    logger.info(f"Узел {node_id} отозван: {reason[:50]}...")
                    extra = (
                        f" (+{len(cascade)} зависимых отозвано)" if cascade else ""
                    )
                    return _(
                        "Узел {node_id} отозван (status=REFUTED). Причина: {reason}{extra}",
                        node_id=node_id,
                        reason=reason,
                        extra=extra,
                    )
            return _("Узел {node_id} не найден.", node_id=node_id)

    async def intel_restore_memory_node(self, node_id: str, reason: str) -> str:
        """Восстановить узел из REFUTED (ручной возврат факта, ADR-0002/0003).

        Переводит узел из REFUTED обратно в ACTIVE, фиксирует причину восстановления
        (restore_reason) и время (restored_at). Добавляет флаг
        false_retraction=true для метрики ложных отзывов (спека v1).
        Восстановление без непустой причины невозможно.
        """
        reason = reason.strip() if reason else ""
        if not reason:
            return _(
                "Восстановление требует непустую причину (reason) — память не восстанавливается молча."
            )
        async with _AsyncLockAdapter(self._write_lock):
            nodes = self._load_flat_memory_nodes()
            for n in nodes:
                if n.get("node_id") == node_id:
                    if n.get("status") != "REFUTED":
                        return _("Узел {node_id} не в статусе REFUTED (текущий: {status}).",
                               node_id=node_id, status=n.get("status", "ACTIVE"))
                    n["status"] = "ACTIVE"
                    n["restore_reason"] = reason
                    n["restored_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    n["false_retraction"] = True  # метрика: этот REFUTED был ложным
                    self.store._save_json("project_memory.json", nodes)
                    logger.info(f"Узел {node_id} восстановлен: {reason[:50]}...")
                    return _(
                        "Узел {node_id} восстановлен (status=ACTIVE, false_retraction=true). Причина: {reason}",
                        node_id=node_id,
                        reason=reason,
                    )
            return _("Узел {node_id} не найден.", node_id=node_id)

    async def intel_supersede_memory_node(self, node_id: str, reason: str, new_node_id: str = "") -> str:
        """Пометить узел как SUPERSEDED — заменён более свежим фактом.

        SUPERSEDED — терминальный статус (не REFUTED): факт был верен, но устарел.
        В отличие от REFUTED, это не опровержение, а естественная смена знания.
        Опционально: new_node_id — ID нового узла, который замещает старый.
        """
        reason = reason.strip() if reason else ""
        if not reason:
            return _("SUPERSEDED требует непустую причину (reason).")
        async with _AsyncLockAdapter(self._write_lock):
            nodes = self._load_flat_memory_nodes()
            for n in nodes:
                if n.get("node_id") == node_id:
                    if n.get("status") == "SUPERSEDED":
                        return _("Узел {node_id} уже SUPERSEDED.", node_id=node_id)
                    if n.get("status") == "REFUTED":
                        return _("Нельзя SUPERSEDED REFUTED-узел (сначала restore).", node_id=node_id)
                    n["status"] = "SUPERSEDED"
                    n["supersede_reason"] = reason
                    n["superseded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if new_node_id:
                        n["superseded_by"] = new_node_id
                    self.store._save_json("project_memory.json", nodes)
                    logger.info(f"Узел {node_id} -> SUPERSEDED: {reason[:50]}...")
                    return _(
                        "Узел {node_id} заменён (SUPERSEDED). Причина: {reason}",
                        node_id=node_id,
                        reason=reason,
                    )
            return _("Узел {node_id} не найден.", node_id=node_id)

    # -----------------------------------------------------------------
    # БЛОК 5. Hotspot Engine (Зоны высокого риска)
    # -----------------------------------------------------------------
    # БЛОК 4.5. ADR Auto-Collector (Автоматический сбор архитектурных решений)
    # -----------------------------------------------------------------

    def intel_auto_collect_adrs(self, max_commits: int = 50) -> str:
        """Автоматический сбор ADR из git-лога. (без subprocess, чтение .git/logs/HEAD)"""
        import re as _re
        import zlib
        from pathlib import Path as _P

        git_dir = _P(self.project_path) / '.git'
        reflog_path = git_dir / 'logs' / 'HEAD'
        if not reflog_path.exists():
            return "Git-репозиторий не найден. ADR-коллектор требует git."

        # Читаем .git/logs/HEAD (без subprocess)
        try:
            reflog_raw = reflog_path.read_text('utf-8', errors='replace')
        except Exception as e:
            logger.warning(f"Exception suppressed at layer.py: {e}")
            return f"Ошибка чтения .git/logs/HEAD: {type(e).__name__}: {e}"

        reflog_lines = reflog_raw.strip().split('\n')
        # Берём последние max_commits строк (новые коммиты в конце)
        recent = reflog_lines[-max_commits:] if len(reflog_lines) > max_commits else reflog_lines

        # Парсим хеши коммитов из reflog
        commits: list[tuple[str, str, str]] = []  # (hash, subject, body)
        seen_hashes: set[str] = set()
        def _read_commit_msg(hash_str: str):
            """Читает (subject, body) коммита: loose-объект или git log (packfile-safe).

            Loose-объекты отсутствуют после `git gc` (объекты упакованы в .pack) —
            тогда читаем через `git log`, который сам распаковывает packfiles.
            """
            obj_path = git_dir / 'objects' / hash_str[:2] / hash_str[2:]
            if obj_path.exists():
                try:
                    compressed = obj_path.read_bytes()
                    raw = zlib.decompress(compressed)
                    # raw = "commit <size>\0<content>" или "commit <size>\n<content>"
                    if b'\x00' in raw:
                        content = raw.split(b'\x00', 1)[1]
                    else:
                        # Формат: "commit <size>\n<headers>\n\n<message>"
                        content = raw.split(b'\n', 1)[1] if b'\n' in raw else raw
                    # Ищем двойной newline (конец заголовка, начало сообщения)
                    header_end = content.find(b'\n\n')
                    if header_end == -1:
                        return None
                    msg_raw = content[header_end + 2:].decode('utf-8', errors='replace')
                    msg_lines = msg_raw.strip().split('\n')
                    subject = msg_lines[0] if msg_lines else ''
                    body = '\n'.join(msg_lines[1:]) if len(msg_lines) > 1 else ''
                    return (subject, body[:500]) if subject else None
                except Exception:
                    return None
            # Loose-объект отсутствует (packfile после git gc) — git log
            try:
                result = subprocess.run(
                    ["git", "-C", str(self.project_path), "--no-pager", "log",
                     "-1", "--format=%s%x00%b", hash_str],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, check=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                subject, _, body = result.stdout.partition('\x00')
                return (subject.strip(), body.strip()[:500]) if subject.strip() else None
            except Exception:
                return None

        for line in recent:
            if not line.strip():
                continue
            parts = line.split(' ', 2)
            if len(parts) < 2:
                continue
            new_hash = parts[1].strip()
            if len(new_hash) < 10 or new_hash.count('0') == len(new_hash):
                continue  # хеш из нулей — merge/initial
            if new_hash in seen_hashes:
                continue
            seen_hashes.add(new_hash)

            commit_msg = _read_commit_msg(new_hash)
            if commit_msg is None:
                continue
            subject, body = commit_msg
            if subject:
                commits.append((new_hash[:12], subject, body[:500]))

        if not commits:
            return f"За последние {max_commits} коммитов новых ADR не найдено."

        # Паттерны архитектурных решений
        ADR_PATTERNS = [
            r'^feat\(.*\):', r'^refactor\(.*\):', r'^arch\(.*\):',
            r'^feat:', r'^refactor:', r'^arch:', r'^adr:',
            r'decision', r'replace', r'migrate', r'restructure',
            r'rewrite', r'redesign', r'extract', r'merge.*module',
            r'split.*module', r'change.*api', r'change.*interface',
        ]
        adr_re = _re.compile('|'.join(f'(?:{p})' for p in ADR_PATTERNS), _re.IGNORECASE)

        # Загружаем существующие ADR (чтобы не дублировать).
        # ADR-0002: dedup видит и REFUTED-узлы — отозванный ADR не собирается
        # повторно следующим прогоном auto_collect_adrs.
        memory = self.store.load_memory(include_retracted=True)
        existing_adrs = memory.get('adrs', [])
        existing_hashes = set()
        for a in existing_adrs:
            d = a.get('data', {})
            if isinstance(d, dict):
                h = d.get('commit_hash', '')
                if h:
                    existing_hashes.add(h)

        new_adrs = []
        for commit_hash, subject, body in commits:

            # Пропускаем уже сохранённые
            if commit_hash in existing_hashes:
                continue

            # Проверяем на архитектурный паттерн
            full_msg = f'{subject} {body}'
            if not adr_re.search(full_msg):
                continue

            # Определяем тип решения
            decision_type = 'other'
            subj_lower = subject.lower()
            if _re.match(r'^feat', subj_lower):
                decision_type = 'feature'
            elif _re.match(r'^refactor', subj_lower):
                decision_type = 'refactor'
            elif _re.match(r'^arch|^adr', subj_lower):
                decision_type = 'architecture'

            adr_node = {
                'node_id': f'ADR-{commit_hash}',
                'section': 'adrs',
                'timestamp': '',  # будет заполнено при save
                'status': 'ACTIVE',  # ADR-0002: авто-собранное — не проверено против кода
                'data': {
                    'commit_hash': commit_hash,
                    'title': subject,
                    'body': body[:500] if body else '',
                    'decision_type': decision_type,
                    'source': 'auto-collect',
                },
            }
            # ADR-0003: write-time anchor capture (file:/import/env из title/body)
            from src.core.intelligence.verify_on_read import extract_anchors

            captured = [a.to_dict() for a in extract_anchors(
                {'data': adr_node['data']}, project_root=self.project_path
            )]
            if captured:
                adr_node['data']['anchors'] = captured
            new_adrs.append(adr_node)

        if not new_adrs:
            return f"За последние {max_commits} коммитов новых ADR не найдено."

        # Сохраняем новые ADR (sync lock — общий threading.Lock для sync+async)
        with self._write_lock:
            nodes = self.store._load_json('project_memory.json')
            if isinstance(nodes, dict):
                nodes = []
            for adr in new_adrs:
                adr['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                nodes.append(adr)
            self.store._save_json('project_memory.json', nodes)

        lines = []
        lines.append(f"✅ Найдено и сохранено {len(new_adrs)} ADR:")
        for adr in new_adrs:
            d = adr['data']
            lines.append(f"  • [{d['decision_type']}] {d['title'][:80]}")
            lines.append(f"    commit={d['commit_hash']}")
        return chr(10).join(lines)

    # -----------------------------------------------------------------

    async def intel_get_code_hotspots(self) -> List[Dict[str, Any]]:
        """Возвращает Топ-5 файлов с наивысшей плотностью рисков и баг-нагрузки."""
        try:
            from src.core.bug_correlation import BugCorrelation
            from src.core.commit_memory import CommitMemory

            commit_mem = CommitMemory(self.project_path)
            bug_corr = BugCorrelation(commit_mem)
            bug_corr.analyze()  # загружаем баг-коммиты

            buggy_files = bug_corr.get_top_buggy_files(top_n=10) or []
            hotspots = []

            for bf in buggy_files:
                file_path = bf.get("file", "unknown")
                hotspots.append(
                    {
                        "file": file_path,
                        "bug_count": bf.get("bug_count", 0),
                        "risk_score": bf.get("risk_score", 0.5),
                        "metrics": {
                            "complexity_tier": bf.get("complexity_tier", 3),
                            "total_commits": bf.get("total_commits", 0),
                        },
                    }
                )

            return hotspots[:5]

        except Exception as e:
            logger.warning(f"Exception suppressed at layer.py: {e}")
            return []

    # -----------------------------------------------------------------
    # БЛОК 6. Root Cause Engine (Предсказание причин сбоев)
    # -----------------------------------------------------------------

    async def intel_predict_root_cause(
        self, error_message: str, component_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """Предсказывает наиболее вероятную причину сбоя."""
        from src.core.intelligence.health import HealthReport
        from src.providers.embedder.remote_embedder import RemoteEmbedder

        _start = time.perf_counter()
        candidates = []
        RemoteEmbedder()
        health = HealthReport(self.project_path)

        # 1. Проверяем историю инцидентов
        incidents = self.store.load_incidents()
        for inc in incidents:
            symptom = inc.get("symptom", "")
            if component_context and component_context in symptom:
                candidates.append(
                    {
                        "component": inc["component"],
                        "probability": 0.75,
                        "reason": f"Ранее был инцидент: {symptom}",
                        "fix_applied": inc["fix"],
                        "source": "incident_history",
                    }
                )

        # 2+3. Проверяем показатели здоровья и Hotspots — параллельно, в потоках,
        # с тайм-бюджетом. BS-11 (аудит Bot_snow): run_full_diagnostic (sync,
        # ~15с) блокировал event loop даже для дефолтного ответа «не найдено»
        # (analysis_time_ms: 15634). Теперь: asyncio.to_thread + wait_for(3с),
        # не успели — пропускаем сигнал (дефолтная эвристика остаётся).
        async def _collect_signals() -> None:
            async def _health_signal() -> None:
                try:
                    health_report = await asyncio.wait_for(
                        asyncio.to_thread(health.run_full_diagnostic), timeout=3.0
                    )
                    if health_report and health_report.get("overall_health") == "warning":
                        candidates.append(
                            {
                                "component": component_context or "system",
                                "probability": 0.45,
                                "reason": "Общее состояние системы: warning",
                                "source": "health_report",
                            }
                        )
                except asyncio.TimeoutError:
                    logger.debug("predict_root_cause: health diagnostic timed out (>3s), skipped")
                except Exception as _e:
                    logger.warning(f"Exception suppressed at layer.py: {_e}")

            async def _hotspots_signal() -> None:
                try:
                    hotspots = await asyncio.wait_for(
                        self.intel_get_code_hotspots(), timeout=3.0
                    )
                    if hotspots and component_context:
                        for h in hotspots[:2]:
                            if component_context.lower() in h["file"].lower():
                                candidates.append(
                                    {
                                        "component": h["file"],
                                        "probability": 0.6,
                                        "reason": f"Файл входит в топ горячих точек (багов: {h['bug_count']})",
                                        "source": "hotspot_analysis",
                                    }
                                )
                except asyncio.TimeoutError:
                    logger.debug("predict_root_cause: hotspots timed out (>3s), skipped")
                except Exception as _e:
                    logger.warning(f"Exception suppressed at layer.py: {_e}")

            await asyncio.gather(_health_signal(), _hotspots_signal())

        await asyncio.wait_for(_collect_signals(), timeout=4.0)

        # 4. Если ничего не нашли — дефолтная эвристика
        if not candidates:
            candidates.append(
                {
                    "component": component_context or "unknown",
                    "probability": 0.30,
                    "reason": "Локальных совпадений в истории, рантайме и телеметрии не обнаружено. "
                    "Рекомендуется проверить логи и контекст ошибки.",
                    "source": "default",
                }
            )

        # Сортируем кандидатов по вероятности
        candidates.sort(key=lambda x: x["probability"], reverse=True)

        return {
            "error_message": error_message,
            "component_context": component_context,
            "probable_causes": candidates[:3],
            "analysis_time_ms": int((time.perf_counter() - _start) * 1000),
        }

    # -----------------------------------------------------------------
    # Telemetry — сбор и отображение метрик
    # -----------------------------------------------------------------

    async def intel_get_telemetry(self, days: int = 7) -> dict:
        """Возвращает телеметрию: runtime счётчики + per-tool метрики + ресурсы + LLM ping."""
        from src.core.error_handler import get_tool_metrics_summary as _get_tools
        from src.core.runtime_coordinator import get_counters as _get_rt

        _start = time.perf_counter()

        result = {
            "runtime": _get_rt(),
            "tools": _get_tools(),
            "timestamp": time.time(),
        }

        # RAM / CPU
        try:
            from src.core.indexing.resource_monitor import get_global_resource_monitor

            _mon = get_global_resource_monitor()
            result["resources"] = _mon.get_summary()
        except Exception as _re:
            logger.warning(f"Exception suppressed at layer.py: {_re}")
            result["resources"] = {"error": str(_re)}

        # LLM ping + model info + throughput
        try:
            # BS-8: DI-инстанс embedder (единая правда провайдера), не новый
            # RemoteEmbedder() — иначе телеметрия показывала «Provider: unknown»
            # при реально активном llama.cpp.
            _emb = self._resolve_active_embedder()
            _t0 = time.perf_counter()
            _vec = _emb.embed("ping")
            _ping = round((time.perf_counter() - _t0) * 1000, 1)
            _info = _emb.get_model_info()
            # Embed throughput: пингуем батчем из 10 чтобы измерить tokens/sec
            _t_batch = time.perf_counter()
            _emb.embed_batch(["ping"] * 10)
            _batch_ms = round((time.perf_counter() - _t_batch) * 1000, 1)
            _tokens_per_sec = (
                round(10 * 50 / (_batch_ms / 1000), 0) if _batch_ms > 0 else 0
            )  # ~50 токенов на "ping"
            result["llm"] = {
                "ping_ms": _ping,
                "batch_10_ms": _batch_ms,
                "tokens_per_sec": int(_tokens_per_sec),
                "provider": _info["provider"],
                "model": _info["model"],
                "configured_model": _info["configured_model"],
            }
        except Exception as _le:
            logger.warning(f"Exception suppressed at layer.py: {_le}")
            result["llm"] = {"error": str(_le)}

        # ETA predictor — кормим реальными данными
        try:
            from src.core.eta_predictor import get_predictor

            _pred = get_predictor()
            for t in result.get("tools", []):
                if t["calls"] > 0:
                    _pred.record_measurement(t["tool"], t["avg_ms"])
            ds = _pred.get_stats() if hasattr(_pred, "get_stats") else {}
            result["eta_stats"] = ds
        except Exception as _ee:
            logger.warning(f"Exception suppressed at layer.py: {_ee}")
            result["eta_stats"] = {"error": str(_ee)}

        # Сохраняем снэпшот на диск при каждом вызове (вне проекта, Задача 4/5)
        try:
            from src.core.artifact_paths import get_telemetry_dir

            _telemetry_dir = get_telemetry_dir(self.project_path)
            _date_str = time.strftime("%Y-%m-%d")
            _filepath = _telemetry_dir / f"{_date_str}.json"

            _entries = []
            if _filepath.exists():
                try:
                    _entries = json.loads(_filepath.read_text(encoding="utf-8"))
                    if not isinstance(_entries, list):
                        _entries = []
                except Exception as _e:
                    logger.warning(f"Exception suppressed at layer.py: {_e}")
                    _entries = []

            _snapshot = {
                "date": _date_str,
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "uptime_sec": round(
                    time.time()
                    - __import__(
                        "src.core.passport", fromlist=["RUN_STARTED_AT"]
                    ).RUN_STARTED_AT,
                    1,
                ),
                "counters": result.get("runtime", {}),
                "project": {
                    "project_path": str(self.project_path),
                    "index_chunks": getattr(self.indexer, "_cached_total_chunks", 0),
                    "index_files": len(
                        getattr(self.indexer, "file_guard", {}).get("indexed_files", [])
                    )
                    if hasattr(self.indexer, "file_guard")
                    else 0,
                },
                "resources": result.get("resources", {}),
                "llm": result.get("llm", {}),
                "token_savings": {
                    "avg_savings_percent": 95.0,
                    "total_searches": result.get("runtime", {}).get("search_calls", 0),
                },
                "_meta": {
                    "index_age_days": 0,
                },
            }
            _entries.append(_snapshot)
            _filepath.write_text(
                json.dumps(_entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as _e:
            logger.debug(f"Сохранение снэпшота телеметрии: {_e}")

        # История телеметрии за N дней (из системной папки)}
        try:
            from scripts.collect_telemetry import get_history

            result["history"] = get_history(days)
        except Exception as _e:
            logger.warning(f"Exception suppressed at layer.py: {_e}")
            result["history"] = []

        result["collect_ms"] = round((time.perf_counter() - _start) * 1000, 1)
        return result


    def _enrich_job_response(self, job: BackgroundJob) -> Dict[str, Any]:
        """Обогащает ответ job'а служебными полями: poll_interval_seconds, progress_label, estimated_seconds.

        poll_interval_seconds — оптимальная задержка перед следующим опросом,
        чтобы AI не спамил запросами каждые 5 секунд.
        progress_label — человекочитаемый статус для UI.
        estimated_seconds — примерное оставшееся время для running-задач.
        """
        base = asdict(job)
        base["progress"] = round(job.progress, 2)

        # Вычисляем poll_interval_seconds динамически
        if job.status in ("completed", "failed"):
            base["poll_interval_seconds"] = 0
        elif job.progress < 0.1:
            base["poll_interval_seconds"] = 30  # старт, даём время развернуться
        elif job.progress < 0.5:
            base["poll_interval_seconds"] = 30  # bulk-фаза (загрузка эмбеддингов)
        elif job.progress < 0.8:
            base["poll_interval_seconds"] = 15  # финальная фаза
        else:
            base["poll_interval_seconds"] = 5  # почти готово, проверяем чаще

        # Вычисляем progress_label (plain text, без эмодзи — AI сам добавит при показе)
        if job.status == "completed":
            base["progress_label"] = "Complete"
        elif job.status == "failed":
            base["progress_label"] = f"Failed: {job.error}"
        elif job.status == "pending":
            base["progress_label"] = "Waiting..."
        elif job.progress < 0.1:
            base["progress_label"] = "Starting indexing..."
        elif job.progress < 0.8:
            base["progress_label"] = f"Indexing files... ({job.progress * 100:.0f}%)"
        elif job.progress < 1.0:
            base["progress_label"] = "Finalizing..."
        else:
            base["progress_label"] = "Finishing..."

        # Примерное оставшееся время (адаптивный ETA)
        if job.status == "running":
            elapsed = max(time.time() - job.started_at, 1.0)
            # 1. Если есть история похожих проектов — используем rolling average
            if job.project_size:
                avg_duration = self.job_history.get_estimated_duration(job.project_size)
                if avg_duration and avg_duration > 5:
                    remaining = max(avg_duration - elapsed, 5)
                    base["estimated_seconds"] = int(remaining)
                    return base
            # 2. Fallback: линейная экстраполяция по текущему прогрессу
            if job.progress > 0.05:
                if job.progress < 0.95:
                    estimated = int(elapsed / job.progress * (1.0 - job.progress))
                    base["estimated_seconds"] = max(estimated, 5)
                else:
                    base["estimated_seconds"] = 10
            else:
                # Старт: заглушка 120с (нет данных для экстраполяции)
                base["estimated_seconds"] = 120

        return base


# =====================================================================
# РЕГИСТРАЦИЯ ИНСТРУМЕНТОВ В MCP СЕРВЕРЕ
# =====================================================================


# register_intelligence_tools вынесена в tools_reg.py (P1-5 architecture review).
# Re-export для обратной совместимости:
from src.core.intelligence.tools_reg import register_intelligence_tools
