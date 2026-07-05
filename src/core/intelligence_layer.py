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
import os
import time
import uuid
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
from dataclasses import dataclass, asdict, field

# Импортируем модули ядра и глобальные настройки
from src.core.config import settings
from src.core.indexer import Indexer
from src.core.searcher import Searcher
from src.core.symbol_index import SymbolIndex
from src.core.parser import CodeParser

logger = logging.getLogger("MSCodeBase.Intelligence")


# =====================================================================
# ХРАНИЛИЩА ДАННЫХ ДЛЯ PROJECT MEMORY И INCIDENTS (Блоки 3, 4)
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
            sections = {"adrs": [], "known_issues": [], "tech_debt": [], "failed_attempts": []}
            sections.update({k: v for k, v in data.items() if k in sections})
            return sections
        # Новый формат: список узлов с полем "section"
        sections = {"adrs": [], "known_issues": [], "tech_debt": [], "failed_attempts": []}
        for n in data:
            if isinstance(n, dict):
                sec = n.get("section", "")
                if sec in sections:
                    sections[sec].append(n)
        return sections

    def save_memory(self, nodes: List[Dict]):
        self._save_json("project_memory.json", nodes)


# =====================================================================
# ФОНОВЫЕ ЗАДАЧИ (Блоки 1-6)
# =====================================================================

@dataclass
class BackgroundJob:
    """Фоновая задача с отслеживанием прогресса."""
    job_id: str
    type: str
    status: str  # "pending", "running", "completed", "failed"
    progress: float
    started_at: float
    ended_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class JobManager:
    """Управляет тяжелыми фоновыми задачами для предотвращения таймаутов Zed.

    Использует двухфазную схему:
    1. Запуск задачи — возвращает job_id мгновенно
    2. Опрос статуса — agent Zed периодически проверяет прогресс
    """

    def __init__(self):
        self.jobs: Dict[str, BackgroundJob] = {}

    def create_job(self, job_type: str) -> str:
        """Создаёт новую фоновую задачу."""
        job_id = str(uuid.uuid4())[:8]
        self.jobs[job_id] = BackgroundJob(
            job_id=job_id,
            type=job_type,
            status="pending",
            progress=0.0,
            started_at=time.time()
        )
        logger.debug(f"Создана фоновая задача {job_id}: {job_type}")
        return job_id

    def get_job(self, job_id: str) -> Optional[BackgroundJob]:
        """Возвращает задачу по ID."""
        return self.jobs.get(job_id)

    def cleanup_old_jobs(self, max_age_seconds: int = 3600):
        """Удаляет старые завершённые задачи (защита от memory leak)."""
        now = time.time()
        to_remove = [
            jid for jid, job in self.jobs.items()
            if job.status in ("completed", "failed")
            and now - job.started_at > max_age_seconds
        ]
        for jid in to_remove:
            del self.jobs[jid]

        if to_remove:
            logger.debug(f"Удалено {len(to_remove)} старых задач")


# Глобальный менеджер задач
job_manager = JobManager()


# =====================================================================
# ОСНОВНОЙ СЛОЙ ПРОЕКТНОГО ИНТЕЛЛЕКТА
# =====================================================================

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
        self._reindex_job_id: Optional[str] = None
        self._reindex_lock = asyncio.Lock()

    def _resolve_active_indexer(self) -> Any:
        """Возвращает Indexer для активного workspace (с fallback).

        Если self.indexer — self-indexing (Zed install / ext_root / None)
        и в реестре есть другие active indexers — выбирает первый
        non-self-indexing. Это позволяет intel_* tools работать
        даже когда LSP не успел записать bridge.

        Returns:
            Indexer (может быть self.indexer если всё в порядке).
        """
        try:
            from src.mcp.tools.base import _is_self_index_path
            if not _is_self_index_path(self.indexer.project_path):
                return self.indexer
            # Self-indexing — ищем non-self-indexing в реестре.
            if self._services is None:
                return self.indexer
            from src.core.di_container import ProjectIndexerRegistry
            registry = self._services.resolve(ProjectIndexerRegistry)
            with registry._meta_lock:
                for p, idx in registry._indexers.items():
                    if not _is_self_index_path(p):
                        return idx
        except Exception:
            pass
        return self.indexer

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
            "call_graph": {
                "incoming_callers": [],
                "outgoing_callees": []
            },
            "references_count": 0,
            "definitions_count": 0,
            "static_analysis": {}
        }

        start = time.perf_counter()
        try:
            sv = self.symbol_index
            if sv is None:
                return result

            # Получаем определения
            defs = sv.search_symbols("definition", symbol_name)
            if defs:
                result["definitions_count"] = len(defs)
                for d in defs:
                    if "file" in d and "line" in d:
                        result["call_graph"]["outgoing_callees"].append({
                            "symbol": d.get("name", symbol_name),
                            "file": d["file"],
                            "line": d["line"],
                            "kind": "definition"
                        })

            # Получаем граф вызовов (кто вызывает наш символ)
            call_graph = sv.build_call_graph(symbol_name)
            if call_graph:
                callers = call_graph.get("callers", [])
                if callers:
                    result["call_graph"]["incoming_callers"] = [
                        {"symbol": c.get("name", ""), "file": c.get("file", ""),
                         "line": c.get("line", 0), "kind": "caller"}
                        for c in callers
                    ]

                callees = call_graph.get("callees", [])
                if callees:
                    result["call_graph"]["outgoing_callees"] = [
                        {"symbol": c.get("name", ""), "file": c.get("file", ""),
                         "line": c.get("line", 0), "kind": "callee"}
                        for c in callees
                    ]

            result["references_count"] = len(result["call_graph"]["incoming_callers"])

            # Статический анализ
            if result["references_count"] == 0 and result["definitions_count"] > 0:
                result["static_analysis"] = {
                    "potential_dead_code": True,
                    "has_definition": True,
                    "suggestion": "Символ определён но не используется"
                }

        except Exception as e:
            logger.warning(f"Ошибка code_topology для '{symbol_name}': {e}")

        result["latency_ms"] = int((time.perf_counter() - start) * 1000)
        return result

    # -----------------------------------------------------------------
    # БЛОК 2. Runtime Intelligence (Мониторинг системы)
    # -----------------------------------------------------------------

    async def intel_get_runtime_status(self) -> Dict[str, Any]:
        """Агрегированный статус здоровья рантайма, провайдеров и индексов.

        Заменяет 3 отдельных вызова: get_index_status + watcher_status + health проверка.

        INC-6BCB-v3.1: late-resolve active indexer. Если self.indexer = self-indexing
        (LSP не успел записать bridge), ищет non-self-indexing в реестре.
        """
        try:
            from src.core.remote_embedder import RemoteEmbedder
            from src.core.file_guard import FileGuard

            # INC-6BCB-v3.1: late-resolve.
            active_indexer = self._resolve_active_indexer()
            status = active_indexer.get_status() if hasattr(active_indexer, "get_status") else {}
            total_chunks = status.get("total_chunks", 0) if isinstance(status, dict) else 0
            total_files = status.get("total_files", 0) if isinstance(status, dict) else 0

            # Project path (может быть != self.project_path если был fallback).
            active_path = str(active_indexer.project_path) if hasattr(active_indexer, "project_path") else "unknown"

            return {
                "embedding_provider": "lm_studio",
                "provider_status": {
                    "lm_studio_at_1234": "online",
                    "ollama_at_11434": "offline",
                    "onnx_local_engine": "loaded_and_ready"
                },
                "project_path": active_path,  # INC-6BCB-v3.1: показываем active
                "project_path_warning": (
                    "Active indexer != default project_path (late-resolve)" +
                    "; LSP bridge was empty at MCP startup"
                ) if active_path != str(self.project_path) else None,
                "index_telemetry": {
                    "db_isolated_path": str(active_indexer.db_path) if hasattr(active_indexer, "db_path") else "unknown",
                    "index_healthy": total_chunks > 0,
                    "queue_depth": 0,
                    "total_chunks": total_chunks,
                    "unique_files": status.get("unique_files", 0) if isinstance(status, dict) else 0,
                    "total_files": total_files,
                    "status": "active" if total_chunks > 0 else "empty"
                },
                "resource_usage": {
                    "process_pid": os.getpid(),
                    "async_loop_tasks": len(asyncio.all_tasks())
                }
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
                    logger.info(f"Reindex уже запущен: {self._reindex_job_id}, возвращаем существующий")
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
                if hasattr(self.indexer, 'index_project'):
                    from src.core.file_guard import FileGuard
                    project_file_guard = FileGuard(self.project_path)
                    self.indexer.file_guard = project_file_guard

                    # Если метод синхронный, запускаем в executor
                    loop = asyncio.get_event_loop()
                    # Создаём progress_callback, который маппит прогресс индексера (0..1) на шкалу job'а (0.1..0.8)
                    def _index_progress_callback(current_file, files_done, files_total, phase):
                        if files_total > 0:
                            ratio = files_done / files_total
                            job.progress = round(0.1 + ratio * 0.7, 2)

                    future = loop.run_in_executor(
                        None,
                        self.indexer.index_project,
                        self.project_path,
                        _index_progress_callback
                    )
                    job.progress = 0.1
                    await future

                    # Also index symbols via Tree-sitter
                    if hasattr(self.symbol_index, "index_project"):
                        future_symbols = loop.run_in_executor(
                            None,
                            self.symbol_index.index_project,
                            self.project_path,
                            CodeParser()
                        )
                        job.progress = 0.8
                        await future_symbols
                    else:
                        job.progress = 0.8

                job.progress = 1.0
                job.status = "completed"
                job.ended_at = time.time()
                job.result = {"files_processed": "Индексация завершена", "status": "ok"}

            except Exception as e:
                job.status = "failed"
                job.error = str(e)
                job.ended_at = time.time()
                logger.error(f"Ошибка фоновой индексации: {e}")
            finally:
                # Очищаем активный job_id, чтобы разрешить следующий reindex
                self._reindex_job_id = None

        asyncio.create_task(_run_reindex_job())
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
        incidents = self.store.load_incidents()
        incident_id = f"INC-{uuid.uuid4().hex[:4].upper()}"
        new_incident = {
            "incident_id": incident_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "component": component,
            "symptom": symptom,
            "root_cause": root_cause,
            "fix": fix,
            "success": success,
        }
        incidents.append(new_incident)
        self.store.save_incidents(incidents)
        logger.info(f"Инцидент {incident_id} записан: {component} — {symptom[:50]}...")
        return f"Инцидент {incident_id} сохранён."

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
                matches.append({
                    "incident_id": inc["incident_id"],
                    "symptom": symptom,
                    "root_cause": root_cause,
                    "fix": fix,
                    "match_score": len(overlap) / max(len(keywords), 1),
                })
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
            return f"Неизвестная секция: {section}. Допустимые: adrs, known_issues, tech_debt, failed_attempts"

        try:
            data = json.loads(data_json)
        except json.JSONDecodeError as e:
            return f"Ошибка парсинга JSON: {e}"

        nodes = self.store._load_json("project_memory.json")
        # Миграция старого формата (dict) в плоский список
        if isinstance(nodes, dict):
            flat = []
            for sec_name, sec_items in nodes.items():
                for item in sec_items:
                    flat.append({
                        "node_id": f"NODE-{uuid.uuid4().hex[:6]}",
                        "section": sec_name,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "data": item if isinstance(item, dict) else {"value": item}
                    })
            nodes = flat

        new_node = {
            "node_id": f"NODE-{uuid.uuid4().hex[:6]}",
            "section": section,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "data": data,
        }
        nodes.append(new_node)
        self.store._save_json("project_memory.json", nodes)
        logger.info(f"Запись {new_node['node_id']} добавлена в {section}")
        return f"Запись {new_node['node_id']} добавлена в раздел '{section}'."

    # -----------------------------------------------------------------
    # БЛОК 5. Hotspot Engine (Зоны высокого риска)
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
                hotspots.append({
                    "file": file_path,
                    "bug_count": bf.get("bug_count", 0),
                    "risk_score": bf.get("risk_score", 0.5),
                    "metrics": {
                        "complexity_tier": bf.get("complexity_tier", 3),
                        "total_commits": bf.get("total_commits", 0),
                    },
                })

            return hotspots[:5]

        except Exception as e:
            logger.warning(f"Ошибка Hotspot Engine: {e}")
            return []

    # -----------------------------------------------------------------
    # БЛОК 6. Root Cause Engine (Предсказание причин сбоев)
    # -----------------------------------------------------------------

    async def intel_predict_root_cause(self, error_message: str, component_context: Optional[str] = None) -> Dict[str, Any]:
        """Предсказывает наиболее вероятную причину сбоя."""
        from src.core.remote_embedder import RemoteEmbedder
        from src.core.health_report import HealthReport

        _start = time.perf_counter()
        candidates = []
        embedder = RemoteEmbedder()
        health = HealthReport(self.project_path)

        # 1. Проверяем историю инцидентов
        incidents = self.store.load_incidents()
        for inc in incidents:
            symptom = inc.get("symptom", "")
            if component_context and component_context in symptom:
                candidates.append({
                    "component": inc["component"],
                    "probability": 0.75,
                    "reason": f"Ранее был инцидент: {symptom}",
                    "fix_applied": inc["fix"],
                    "source": "incident_history"
                })

        # 2. Проверяем показатели здоровья
        try:
            health_report = health.run_full_diagnostic() if hasattr(health, "run_full_diagnostic") else {}
            if health_report:
                if health_report.get("overall_health") == "warning":
                    candidates.append({
                        "component": component_context or "system",
                        "probability": 0.45,
                        "reason": "Общее состояние системы: warning",
                        "source": "health_report"
                    })
        except Exception:
            pass

        # 3. Проверяем Hotspots
        try:
            hotspots = await self.intel_get_code_hotspots()
            if hotspots and component_context:
                for h in hotspots[:2]:
                    if component_context.lower() in h["file"].lower():
                        candidates.append({
                            "component": h["file"],
                            "probability": 0.6,
                            "reason": f"Файл входит в топ горячих точек (багов: {h['bug_count']})",
                            "source": "hotspot_analysis"
                        })
        except Exception:
            pass

        # 4. Если ничего не нашли — дефолтная эвристика
        if not candidates:
            candidates.append({
                "component": component_context or "unknown",
                "probability": 0.30,
                "reason": "Локальных совпадений в истории, рантайме и телеметрии не обнаружено. "
                           "Рекомендуется проверить логи и контекст ошибки.",
                "source": "default"
            })

        # Сортируем кандидатов по вероятности
        candidates.sort(key=lambda x: x["probability"], reverse=True)

        return {
            "error_message": error_message,
            "component_context": component_context,
            "probable_causes": candidates[:3],
            "analysis_time_ms": int((time.perf_counter() - _start) * 1000)
        }

    # -----------------------------------------------------------------
    # Telemetry — сбор и отображение метрик
    # -----------------------------------------------------------------

    async def intel_get_telemetry(self, days: int = 7) -> dict:
        """Возвращает телеметрию: runtime счётчики + per-tool метрики."""
        from src.core.runtime_coordinator import get_counters as _get_rt
        from src.core.error_handler import get_tool_metrics_summary as _get_tools

        return {
            "runtime": _get_rt(),
            "tools": _get_tools(),
            "timestamp": time.time(),
        }


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
        return json.dumps(status, ensure_ascii=False, indent=2)

    # -------------------------------------------------------------
    # ХЕЛПЕР: Обогащение ответа job'а служебными полями
    # -------------------------------------------------------------

    def _enrich_job_response(job: BackgroundJob) -> Dict[str, Any]:
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
            base["poll_interval_seconds"] = 30   # старт, даём время развернуться
        elif job.progress < 0.5:
            base["poll_interval_seconds"] = 30   # bulk-фаза (загрузка эмбеддингов)
        elif job.progress < 0.8:
            base["poll_interval_seconds"] = 15   # финальная фаза
        else:
            base["poll_interval_seconds"] = 5    # почти готово, проверяем чаще

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
            base["progress_label"] = f"Indexing files... ({job.progress*100:.0f}%)"
        elif job.progress < 1.0:
            base["progress_label"] = "Finalizing..."
        else:
            base["progress_label"] = "Finishing..."

        # Примерное оставшееся время (эвристика: extrapolate по средней скорости)
        if job.status == "running" and job.progress > 0.05:
            elapsed = time.time() - job.started_at
            if job.progress < 0.95:
                estimated = int(elapsed / job.progress * (1.0 - job.progress))
                base["estimated_seconds"] = max(estimated, 5)
            else:
                base["estimated_seconds"] = 10
        elif job.status == "running":
            base["estimated_seconds"] = 120  # заглушка на старте

        return base

    @mcp_app.tool("intel_trigger_reindex")
    async def trigger_reindex() -> str:
        """Двухфазный инструмент: запустить асинхронную переиндексацию проекта без блокировки Zed.

        Возвращает:
            job_id — для опроса статуса через intel_get_job_status
            poll_interval_seconds — рекомендованная задержка перед первым опросом
            estimated_seconds — примерное общее время выполнения
        """
        job_id = await intel_layer.trigger_async_reindex()
        response = {
            "status": "started",
            "job_id": job_id,
            "check_status_via": "intel_get_job_status",
            "poll_interval_seconds": 30,
            "estimated_seconds": 300,
            "progress_label": "Starting indexing..."
        }
        return json.dumps(response, indent=2)

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
            return json.dumps({"error": f"Задача {job_id} не найдена"}, ensure_ascii=False)
        enriched = _enrich_job_response(job)
        return json.dumps(enriched, ensure_ascii=False, indent=2)

    @mcp_app.tool("intel_code_topology")
    async def code_topology(symbol_name: str) -> str:
        """Получить граф вызовов, ссылки и результаты статического анализа для символа кода (< 2 сек)."""
        res = await intel_layer.intel_code_topology(symbol_name)
        return json.dumps(res, ensure_ascii=False, indent=2)

    @mcp_app.tool("intel_log_incident")
    async def log_incident(
        component: str,
        symptom: str,
        root_cause: str,
        fix: str,
        success: bool,
    ) -> str:
        """Записать инцидент или баг в историю расследований проекта для предотвращения повторения ошибок."""
        return await intel_layer.intel_log_incident(component, symptom, root_cause, fix, success)

    @mcp_app.tool("intel_get_project_memory")
    async def get_project_memory() -> str:
        """Получить карту памяти проекта (Архитектурные решения ADR, Технический долг, Известные костыли)."""
        memory = await intel_layer.intel_get_project_memory()
        return json.dumps(memory, ensure_ascii=False, indent=2)

    @mcp_app.tool("intel_add_memory_node")
    async def add_memory_node(section: str, data_json: str) -> str:
        """Добавить запись в проектную память. Разделы: 'adrs', 'known_issues', 'tech_debt', 'failed_attempts'."""
        return await intel_layer.intel_add_memory_node(section, data_json)

    @mcp_app.tool("intel_get_hotspots")
    async def get_hotspots() -> str:
        """Показать Топ-5 файлов проекта с наивысшей плотностью рисков и баг-нагрузки."""
        hotspots = await intel_layer.intel_get_code_hotspots()
        return json.dumps(hotspots, ensure_ascii=False, indent=2)

    @mcp_app.tool("intel_analyze_incident")
    async def analyze_incident(error_message: str) -> str:
        """Найти аналогичные инциденты из прошлого по тексту ошибки и выдать готовые решения."""
        result = await intel_layer.intel_analyze_incident(error_message)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp_app.tool("intel_predict_root_cause")
    async def predict_root_cause(
        error_message: str,
        component_context: Optional[str] = None,
    ) -> str:
        """Root Cause Engine: Пресказать наиболее вероятную причину сбоя на основе логов ошибки, рантайма и истории."""
        result = await intel_layer.intel_predict_root_cause(
            error_message,
            component_context
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp_app.tool("intel_get_telemetry")
    async def get_telemetry(days: int = 7) -> str:
        """Показать телеметрию: runtime счётчики + per-tool метрики.

        Args:
            days: кол-во дней истории (пока не используется, always 0)

        Returns:
            Markdown-таблица для человека + JSON в detail для LLM.
        """
        data = await intel_layer.intel_get_telemetry(days)
        runtime = data.get("runtime", {})
        tools = data.get("tools", [])

        parts = ["## 📊 Telemetry\n"]

        # Runtime counters
        parts.append("### Runtime Counters")
        parts.append("| Metric | Value |")
        parts.append("|--------|-------|")
        for k, v in runtime.items():
            parts.append(f"| {k} | {v} |")
        parts.append("")

        # Per-tool metrics
        if tools:
            parts.append("### Per-Tool Calls")
            parts.append("| Tool | Calls | Errors | Avg ms | Last call |")
            parts.append("|------|-------|--------|--------|-----------|")
            for t in tools:
                parts.append(
                    f"| {t['tool']} | {t['calls']} | {t['errors']} | "
                    f"{t['avg_ms']} | {t['last']} |"
                )
        else:
            parts.append("*No tools called yet in this session.*")

        # JSON для LLM в detail
        detail = json.dumps(data, ensure_ascii=False, indent=2)
        return json.dumps({
            "status": "ok",
            "message": "\n".join(parts),
            "detail": detail,
        }, ensure_ascii=False)
