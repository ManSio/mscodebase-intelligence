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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Импортируем модули ядра и глобальные настройки
from src.config.settings import settings
from src.core.indexer import Indexer
from src.core.indexing.parser import CodeParser
from src.core.search.engine import Searcher
from src.core.indexing.symbol_index import SymbolIndex

logger = logging.getLogger("MSCodeBase.Intelligence")
from src.core.error_handler import error_boundary, record_tool_result
from src.utils.i18n import _

from dataclasses import asdict

# Импорты из декомпозированных модулей
from src.core.intelligence.store import IntelligenceStore, JobHistoryStore
from src.core.intelligence.jobs import BackgroundJob, JobManager, job_manager


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
        self._write_lock = asyncio.Lock()  # защита от race при записи JSON
        self._sync_write_lock = threading.Lock()  # для sync-методов (intel_auto_collect_adrs)

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
                from src.mcp.tools.base import _is_self_index_path

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
                with registry._meta_lock:
                    for p, idx in registry._indexers.items():
                        if not _is_self_index_path(p):
                            return idx
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
                        result["call_graph"]["outgoing_callees"].append(
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
                    result["call_graph"]["incoming_callers"] = [
                        {
                            "symbol": c.get("name", ""),
                            "file": c.get("file", ""),
                            "line": c.get("line", 0),
                            "kind": "caller",
                        }
                        for c in callers
                    ]

                callees = call_graph.get("callees", [])
                if callees:
                    result["call_graph"]["outgoing_callees"] = [
                        {
                            "symbol": c.get("name", ""),
                            "file": c.get("file", ""),
                            "line": c.get("line", 0),
                            "kind": "callee",
                        }
                        for c in callees
                    ]

            result["references_count"] = len(result["call_graph"]["incoming_callers"])

            # Статический анализ
            if result["references_count"] == 0 and result["definitions_count"] > 0:
                result["static_analysis"] = {
                    "potential_dead_code": True,
                    "has_definition": True,
                    "suggestion": "Символ определён но не используется",
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
        try:
            out = subprocess.check_output(
                ["wmic", "process", "where", f"processid={pid}",
                 "get", "WorkingSetSize", "/format:value"],
                timeout=3
            ).decode("utf-8", errors="replace")
            return int(out.split('=')[1].strip()) // (1024*1024)
        except (OSError, subprocess.TimeoutExpired,
                subprocess.CalledProcessError, ValueError, IndexError):
            return 0

    @staticmethod
    def _get_process_cpu(pid: int) -> float:
        try:
            import psutil
            return psutil.Process(pid).cpu_percent(interval=0.1)
        except (ImportError, Exception):
            return 0.0

    @staticmethod
    def _find_pid(name: str, port: str) -> int:
        """Ищет PID процесса по порту (через netstat, без shell)."""
        try:
            port_int = int(port)
            out = subprocess.check_output(
                ["netstat", "-ano"], timeout=3
            ).decode("utf-8", errors="replace")
            for line in out.splitlines():
                if f":{port_int}" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        return int(parts[4])
        except (OSError, subprocess.TimeoutExpired,
                subprocess.CalledProcessError, ValueError, IndexError):
            pass
        return 0

    @staticmethod
    def _get_ram_by_port(port: str) -> int:
        pid = ProjectIntelligenceLayer._find_pid('', port)
        if pid:
            return ProjectIntelligenceLayer._get_process_ram(pid)
        return 0

    @staticmethod
    def _get_total_ram() -> int:
        total = ProjectIntelligenceLayer._get_process_ram(os.getpid())
        for port in ['8080', '8081']:
            total += ProjectIntelligenceLayer._get_ram_by_port(port)
        return total

    async def intel_get_runtime_status(self) -> Dict[str, Any]:
        """Агрегированный статус здоровья рантайма, провайдеров и индексов.

        Заменяет 3 отдельных вызова: get_index_status + watcher_status + health проверка.

        INC-6BCB-v3.1: late-resolve active indexer. Если self.indexer = self-indexing
        (LSP не успел записать bridge), ищет non-self-indexing в реестре.
        """
        try:
            from src.core.indexing.file_guard import FileGuard
            from src.providers.embedder.remote_embedder import RemoteEmbedder

            # INC-6BCB-v3.1: late-resolve.
            active_indexer = self._resolve_active_indexer()
            status = (
                active_indexer.get_status()
                if hasattr(active_indexer, "get_status")
                else {}
            )
            total_chunks = (
                status.get("total_chunks", 0) if isinstance(status, dict) else 0
            )
            total_files = (
                status.get("total_files", 0) if isinstance(status, dict) else 0
            )

            # Project path (может быть != self.project_path если был fallback).
            active_path = (
                str(active_indexer.project_path)
                if hasattr(active_indexer, "project_path")
                else "unknown"
            )

            # Реальный опрос провайдеров вместо хардкода
            _lm_online = False
            _llama_online = False
            # Динамическое сканирование ONNX модели (как в _detect_model_dir RemoteEmbedder)
            _search_paths = [
                self.project_path / ".codebase_models" / "onnx",
                Path(__file__).resolve().parent.parent.parent / ".codebase_models" / "onnx",
                Path.home() / ".cache" / "mscodebase" / "models" / ".codebase_models" / "onnx",
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
                if _s.connect_ex(("127.0.0.1", 1234)) == 0:
                    _lm_online = True
                _s.close()
                # Проверяем llama.cpp (Qwen3 на порту 8080)
                _s2 = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
                _s2.settimeout(0.5)
                _llama_port = int(os.getenv("LLAMA_CPP_PORT", "8080"))
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
                    "status": "active" if total_chunks > 0 else "empty",
                },
                "resource_usage": {
                    "process_pid": os.getpid(),
                    "async_loop_tasks": len(asyncio.all_tasks()),
                    "process_ram_mb": ProjectIntelligenceLayer._get_process_ram(os.getpid()),
                    "llama_qwen_pid": ProjectIntelligenceLayer._find_pid("llama-server.exe", "8080"),
                    "llama_qwen_ram": ProjectIntelligenceLayer._get_ram_by_port("8080"),
                    "llama_rerank_ram": ProjectIntelligenceLayer._get_ram_by_port("8081"),
                    "total_ram_mb": ProjectIntelligenceLayer._get_total_ram(),
                },
                "model_info": {
                    "provider": _active_provider,
                    "model": "e5-base-v2",
                    "dimension": 768,
                },
                "_debug": str(type(active_indexer)),
            }
        except Exception as e:
            logger.error(f"Ошибка получения статуса: {e}")
            return {"status": "error", "detail": str(e)}

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

        async def _run_reindex_job():
            job = job_manager.get_job(job_id)
            if not job:
                return

            job.status = "running"
            job.progress = 0.0

            try:
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

                    # Also index symbols via Tree-sitter
                    if hasattr(self.symbol_index, "index_project"):
                        future_symbols = loop.run_in_executor(
                            None,
                            self.symbol_index.index_project,
                            self.project_path,
                            CodeParser(),
                        )
                        job.progress = 0.8
                        job.result = {
                            "phase": "finalizing_symbols",
                            "files_processed": indexed_count,
                        }
                        try:
                            # Таймаут на символьную индексацию, чтобы job не
                            # зависал на 80% Finalizing при зависании Tree-sitter.
                            await asyncio.wait_for(future_symbols, timeout=120)
                        except asyncio.TimeoutError:
                                logger.warning(
                                "⚠️ Символьная индексация превысила 120с — "
                                "завершаем job без неё (векторный индекс готов)."
                            )
                    else:
                        job.progress = 0.8

                job.progress = 1.0
                job.status = "completed"
                job.ended_at = time.time()
                job.result = {"files_processed": "Индексация завершена", "status": "ok"}

                # Сохраняем в историю для адаптивного ETA (только если есть размер)
                if job.project_size:
                    duration = (job.ended_at or time.time()) - job.started_at
                    self.job_history.append_record(job.project_size, duration)

            except Exception as e:
                logger.warning(f"Exception suppressed at layer.py: {e}")
                job.status = "failed"
                job.error = str(e)
                job.ended_at = time.time()
                logger.error(f"Ошибка фоновой индексации: {e}")
            finally:
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
        async with self._write_lock:
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
        """Находит аналогичные инциденты по тексту ошибки."""
        incidents = self.store.load_incidents()
        matches = []
        for inc in incidents:
            symptom = inc.get("symptom", "")
            root_cause = inc.get("root_cause", "")
            fix = inc.get("fix", "")
            # Простой поиск по ключевым словам
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
                    }
                )
        matches.sort(key=lambda x: x["match_score"], reverse=True)
        return {
            "error_message": error_message,
            "matches_found": len(matches),
            "similar_incidents": matches[:3],
        }

    # -----------------------------------------------------------------
    # БЛОК 4. Project Memory (Архитектурная память)
    # -----------------------------------------------------------------

    async def intel_get_project_memory(self) -> Dict[str, List[Dict]]:
        """Получить полную карту памяти проекта."""
        return self.store.load_memory()

    async def intel_add_memory_node(self, section: str, data_json: str) -> str:
        """Добавить запись в проектную память.

        Секции: 'adrs', 'known_issues', 'tech_debt', 'failed_attempts'
        """
        if section not in ("adrs", "known_issues", "tech_debt", "failed_attempts"):
            return _(
                "Неизвестная секция: {section}. Допустимые: adrs, known_issues, tech_debt, failed_attempts",
                section=section,
            )

        try:
            data = json.loads(data_json)
        except json.JSONDecodeError as e:
            return _("JSON parse error: {error}", error=e)

        async with self._write_lock:
            nodes = self.store._load_json("project_memory.json")
        # Миграция старого формата (dict) в плоский список
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
                        }
                    )
            nodes = flat

        new_node = {
            "node_id": f"NODE-{uuid.uuid4().hex[:6]}",
            "section": section,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data": data,
        }
        nodes.append(new_node)
        self.store._save_json("project_memory.json", nodes)
        logger.info(f"Запись {new_node['node_id']} добавлена в {section}")
        return _(
            "Запись {node_id} добавлена в раздел '{section}'.",
            node_id=new_node["node_id"],
            section=section,
        )

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

            # Читаем объект коммита из .git/objects/
            obj_path = git_dir / 'objects' / new_hash[:2] / new_hash[2:]
            if not obj_path.exists():
                continue
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
                    continue
                msg_raw = content[header_end + 2:].decode('utf-8', errors='replace')
                msg_lines = msg_raw.strip().split('\n')
                subject = msg_lines[0] if msg_lines else ''
                body = '\n'.join(msg_lines[1:]) if len(msg_lines) > 1 else ''
                if subject:
                    commits.append((new_hash[:12], subject, body[:500]))
            except Exception as _e:
                logger.warning(f"Exception suppressed at layer.py: {_e}")
                continue

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

        # Загружаем существующие ADR (чтобы не дублировать)
        memory = self.store.load_memory()
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
                'data': {
                    'commit_hash': commit_hash,
                    'title': subject,
                    'body': body[:500] if body else '',
                    'decision_type': decision_type,
                    'source': 'auto-collect',
                },
            }
            new_adrs.append(adr_node)

        if not new_adrs:
            return f"За последние {max_commits} коммитов новых ADR не найдено."

        # Сохраняем новые ADR (sync lock — функция def, не async def)
        with self._sync_write_lock:
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
        embedder = RemoteEmbedder()
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

        # 2. Проверяем показатели здоровья
        try:
            health_report = (
                health.run_full_diagnostic()
                if hasattr(health, "run_full_diagnostic")
                else {}
            )
            if health_report:
                if health_report.get("overall_health") == "warning":
                    candidates.append(
                        {
                            "component": component_context or "system",
                            "probability": 0.45,
                            "reason": "Общее состояние системы: warning",
                            "source": "health_report",
                        }
                    )
        except Exception as _e:
            logger.warning(f"Exception suppressed at layer.py: {_e}")

    # 3. Проверяем Hotspots
        try:
            hotspots = await self.intel_get_code_hotspots()
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
        except Exception as _e:
            logger.warning(f"Exception suppressed at layer.py: {_e}")
            pass

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
            from src.providers.embedder.remote_embedder import RemoteEmbedder

            _emb = RemoteEmbedder()
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

        # Сохраняем снэпшот на диск при каждом вызове
        try:
            _telemetry_dir = self.project_path / ".mscodebase" / "telemetry"
            _telemetry_dir.mkdir(parents=True, exist_ok=True)
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
            }
            _entries.append(_snapshot)
            _filepath.write_text(
                json.dumps(_entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as _e:
            logger.debug(f"Сохранение снэпшота телеметрии: {_e}")

        # История телеметрии за N дней (из .mscodebase/telemetry/)}
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


def register_intelligence_tools(mcp_app, intel_layer: ProjectIntelligenceLayer):
    """
    Регистрирует все инструменты Intelligence Layer в MCP сервере.

    Вызывайте эту функцию при инициализации MCP-сервера в src/mcp/server.py.
    Инструменты агрегируют функциональность для уменьшения количества вызовов.
    """

    @mcp_app.tool("intel_get_runtime_status")
    async def get_runtime_status() -> str:
        """Получить агрегированный статус здоровья рантайма, ИИ-провайдеров и индексов за 1 вызов."""
        status = await intel_layer.intel_get_runtime_status()
        from src.utils.ui_formatter import format_runtime_status

        return format_runtime_status(status)

    # -------------------------------------------------------------
    # ХЕЛПЕР: Обогащение ответа job'а служебными полями
    # -------------------------------------------------------------

    @mcp_app.tool("intel_trigger_reindex")
    async def trigger_reindex() -> str:
        """Двухфазный инструмент: запустить асинхронную переиндексацию проекта без блокировки Zed.

        Возвращает:
            job_id — для опроса статуса через intel_get_job_status
            poll_interval_seconds — рекомендованная задержка перед первым опросом
            estimated_seconds — примерное общее время выполнения
        """
        job_id = await intel_layer.trigger_async_reindex()

        # Ждём 2 секунды, чтобы индексация дала первый прогресс
        await asyncio.sleep(2)

        # Проверяем статус задачи
        job = job_manager.get_job(job_id) if hasattr(job_manager, "get_job") else None
        progress = round(job.progress * 100) if job else 0
        p_label = job.status if job else "starting"

        # Берём real-time ETA из job'а, если хватило прогресса
        enriched = intel_layer._enrich_job_response(job) if job else {}
        estimated_sec = enriched.get("estimated_seconds", 120)

        from datetime import datetime, timedelta

        _started = (
            datetime.fromtimestamp(job.started_at)
            if job and job.started_at
            else datetime.now()
        )
        _eta_dt = _started + timedelta(seconds=estimated_sec)
        _eta_time = _eta_dt.strftime("%H:%M:%S")

        # Форматируем ETA человекочитаемо
        if estimated_sec >= 120:
            eta_str = f"~{estimated_sec // 60}м"
        elif estimated_sec >= 60:
            eta_str = f"~{estimated_sec // 60}м {estimated_sec % 60}с"
        else:
            eta_str = f"~{estimated_sec}с"

        _now = datetime.now().strftime("%H:%M:%S")
        _bar = "[" + "█" * (progress // 7) + "░" * (15 - progress // 7) + "]"

        _poll_interval = enriched.get("poll_interval_seconds", 30)
        _next_poll = (_now if _poll_interval == 0
                      else (datetime.now() + timedelta(seconds=_poll_interval)).strftime("%H:%M:%S"))

        dashboard = (
            f"📦 **MSCodeBase: Indexing Started**\n"
            f"{'━' * 30}\n"
            f"🏗️ **Progress:** {_bar} `{progress}%`\n"
            f"⏱️ Старт: `{_now}` | Статус: `{p_label}`\n"
            f"⏱️ **ETA:** {eta_str} (готовность к `{_eta_time}`)\n"
            f"📌 Job ID: `{job_id}`\n"
            f"{'━' * 30}\n"
            f"💡 *Следующая проверка: не ранее `{_next_poll}`.*\n"
        )
        return dashboard

    @mcp_app.tool("intel_get_job_status")
    async def get_job_status(job_id: str) -> str:
        """Получить текущий прогресс и статус фоновой задачи по ее ID.

        Возвращает:
            progress — 0.0..1.0
            poll_interval_seconds — оптимальная задержка перед следующим опросом
            estimated_seconds — примерное оставшееся время
            progress_label — человекочитаемый статус
        """
        job = job_manager.get_job(job_id)
        if not job:
            return _("ℹ️ **Job {job_id}** not found\n", job_id=job_id)
        enriched = intel_layer._enrich_job_response(job)
        status_icon = (
            "✅"
            if job.status == "completed"
            else (
                "🔄"
                if job.status == "running"
                else ("❌" if job.status == "failed" else "⏳")
            )
        )
        bar = (
            "["
            + "█" * max(0, min(15, int(job.progress * 15)))
            + "░" * max(0, 15 - max(0, min(15, int(job.progress * 15))))
            + "]"
        )
        label = enriched.get("progress_label", job.status)
        result = (
            f"{status_icon} **Job {job_id}** — {label}\n"
            f"   {bar} `{job.progress:.0%}`\n"
            f"   Статус: `{job.status}`\n"
            f"   Прогресс: {enriched.get('progress_label', 'N/A')}\n"
        )
        if job.error:
            result += f"❌ Ошибка: {job.error}\n"
        return result

    @mcp_app.tool("intel_code_topology")
    async def code_topology(symbol_name: str) -> str:
        """Получить граф вызовов, ссылки и результаты статического анализа для символа кода (< 2 сек)."""
        res = await intel_layer.intel_code_topology(symbol_name)
        from src.utils.ui_formatter import format_analysis_result

        return format_analysis_result(f"Call Graph: {symbol_name}", res)

    @mcp_app.tool("intel_log_incident")
    async def log_incident(
        component: str,
        symptom: str,
        root_cause: str,
        fix: str,
        success: bool,
    ) -> str:
        """Записать инцидент или баг в историю расследований проекта для предотвращения повторения ошибок."""
        return await intel_layer.intel_log_incident(
            component, symptom, root_cause, fix, success
        )

    @mcp_app.tool("intel_get_project_memory")
    async def get_project_memory() -> str:
        """Получить карту памяти проекта (Архитектурные решения ADR, Технический долг, Известные костыли)."""
        memory = await intel_layer.intel_get_project_memory()
        from src.utils.ui_formatter import format_project_memory

        return format_project_memory(memory)

    @mcp_app.tool("intel_add_memory_node")
    async def add_memory_node(section: str, data_json: str) -> str:
        """Добавить запись в проектную память. Разделы: 'adrs', 'known_issues', 'tech_debt', 'failed_attempts'."""
        return await intel_layer.intel_add_memory_node(section, data_json)

    @mcp_app.tool("intel_auto_collect_adrs")
    def auto_collect_adrs(max_commits: int = 50) -> str:
        """Автоматический сбор ADR из git-лога.

        Сканирует последние N коммитов, находит архитектурные решения
        (feat/refactor/arch/adr) и сохраняет их в проектную память.

        Args:
            max_commits: Сколько последних коммитов проверить (по умолч. 50)

        Returns:
            Отчёт: сколько ADR найдено и сохранено
        """
        try:
            return intel_layer.intel_auto_collect_adrs(max_commits)
        except Exception as e:
            logger.warning(f"Exception suppressed at layer.py: {e}")
            import traceback
            return f"Ошибка: {type(e).__name__}: {e}\n{traceback.format_exc()}"

    @mcp_app.tool("intel_get_hotspots")
    async def get_hotspots() -> str:
        """Показать Топ-5 файлов проекта с наивысшей плотностью рисков и баг-нагрузки."""
        hotspots = await intel_layer.intel_get_code_hotspots()
        from src.utils.ui_formatter import format_hotspots

        return format_hotspots(hotspots)

    @mcp_app.tool("intel_analyze_incident")
    async def analyze_incident(error_message: str) -> str:
        """Найти аналогичные инциденты из прошлого по тексту ошибки и выдать готовые решения."""
        result = await intel_layer.intel_analyze_incident(error_message)
        from src.utils.ui_formatter import format_analysis_result

        return format_analysis_result(
            f"Incident Analysis: {error_message[:50]}", result
        )

    @mcp_app.tool("intel_predict_root_cause")
    async def predict_root_cause(
        error_message: str,
        component_context: Optional[str] = None,
    ) -> str:
        """Root Cause Engine: Пресказать наиболее вероятную причину сбоя на основе логов ошибки, рантайма и истории."""
        result = await intel_layer.intel_predict_root_cause(
            error_message, component_context
        )
        from src.utils.ui_formatter import format_analysis_result

        return format_analysis_result(f"Root Cause: {error_message[:50]}", result)

    @mcp_app.tool("intel_get_telemetry")
    async def get_telemetry(days: int = 7) -> str:
        """Показать телеметрию: runtime счётчики + per-tool метрики.

        Args:
            days: кол-во дней истории (пока не используется, always 0)

        Returns:
            Markdown-таблица для человека.
        """
        data = await intel_layer.intel_get_telemetry(days)
        runtime = data.get("runtime", {})
        tools = data.get("tools", [])

        parts = ["## 📊 Telemetry\n"]

        # Runtime counters (человеческие названия)
        _ct = runtime
        parts.append("### Runtime State")
        _rstatus = "✅ Ready" if _ct.get("verdict_ready", 0) > 0 else "⏳ Pending"
        parts.append(
            f"| State: {_rstatus} | Warnings: {sum(_ct.get(k, 0) for k in ['warnings_bridge_not_synced', 'warnings_indexing_in_progress', 'warnings_just_started'])} | Total wait: {_ct.get('total_wait_time_sec', 0):.1f}s |"
        )
        parts.append("")

        # Per-tool metrics with min/avg/max
        if tools:
            parts.append("### Per-Tool Calls")
            parts.append(
                "| Tool | Calls | Errors | Min ms | Avg ms | Max ms | Last call |"
            )
            parts.append(
                "|------|-------|--------|--------|--------|--------|-----------|"
            )
            for t in tools:
                parts.append(
                    f"| {t['tool']} | {t['calls']} | {t['errors']} | "
                    f"{t.get('min_ms', 0)} | {t['avg_ms']} | {t.get('max_ms', 0)} | {t['last']} |"
                )
        else:
            parts.append("*No tools called yet in this session.*")

        # Resources (RAM/CPU)
        res = data.get("resources", {})
        if res and "error" not in res:
            parts.append("### 💻 Resources")
            parts.append(
                f"| RAM: {res.get('rss_mb', '?'):>5} MB | CPU: {res.get('cpu_percent', '?'):>4}% | Threads: {res.get('num_threads', '?')} |"
            )
            parts.append("")

        # LLM ping + model + throughput
        llm = data.get("llm", {})
        if llm and "error" not in llm:
            parts.append("### ⚡ LLM Provider")
            parts.append(
                f"| Model: {llm.get('model', '?')} | Ping: {llm.get('ping_ms', '?'):>6}ms | Batch10: {llm.get('batch_10_ms', '?'):>6}ms |"
            )
            parts.append(
                f"| Throughput: {llm.get('tokens_per_sec', '?'):>5} tok/s | Provider: {llm.get('provider', '?')} |"
            )
            parts.append("")

        # ETA stats
        eta = data.get("eta_stats", {})
        if eta and "error" not in eta:
            parts.append("### ⏱ ETA Predictor")
            opers = eta.get("operations", [])
            learned = eta.get("learned_operations", [])
            total = eta.get("total_measurements", 0)
            parts.append(
                f"| Total measurements: {total} | Learned: {len(learned)}/{len(opers)} ops |"
            )
            if learned:
                parts.append(f"| Operations with data: {', '.join(learned[:5])} |")
            parts.append("")

        # History (дни/недели)
        history = data.get("history", [])
        if history:
            parts.append("### 📅 History (last {} snapshots)".format(len(history)))
            parts.append("| Date | Chunks | Files | RAM | LLM ping |")
            parts.append("|------|--------|-------|-----|----------|")
            for e in history[-14:]:
                d = e.get("date", "?")
                proj = e.get("project", {})
                ch = proj.get("index_chunks", "-")
                fi = proj.get("index_files", "-")
                res = e.get("resources", {})
                ram = res.get("rss_mb", "-")
                if isinstance(ram, (int, float)):
                    ram = f"{ram:.0f} MB"
                llm = e.get("llm", {}).get("ping_ms", "-")
                if isinstance(llm, (int, float)):
                    llm = f"{llm:.0f}ms"
                parts.append(f"| {d} | {ch} | {fi} | {ram} | {llm} |")
            parts.append("")

        return "\n".join(parts)
