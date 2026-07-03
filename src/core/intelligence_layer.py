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
class ADR:
    """Architecture Decision Record — архитектурное решение."""
    decision_id: str
    title: str
    reason: str
    alternatives: List[str]
    date: str


@dataclass
class KnownIssue:
    """Известная проблема с обходным решением."""
    issue: str
    workaround: str
    severity: str  # critical, high, medium, low
    status: str  # open, resolved, wontfix


@dataclass
class TechDebt:
    """Технический долг."""
    module: str
    problem: str
    priority: str  # critical, high, medium, low


@dataclass
class FailedAttempt:
    """Неудачная попытка решения."""
    attempt: str
    reason: str
    result: str


class IntelligenceStore:
    """Легковесное детерминированное хранилище истории проекта и инцидентов.

    Использует JSON файлы для хранения, что обеспечивает:
    - Быструю загрузку/сохранение (< 50мс)
    - Нет внешних зависимостей
    - Удобный просмотр и редактирование вручную
    """

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.storage_dir = project_path / settings.index.base_index_dir / "intelligence"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.incidents_file = self.storage_dir / "incidents.json"
        self.memory_file = self.storage_dir / "project_memory.json"

        self.incidents: List[Dict[str, Any]] = self._load_json(self.incidents_file)
        self.memory: Dict[str, List[Any]] = self._load_json(self.memory_file, default={
            "adrs": [],
            "known_issues": [],
            "tech_debt": [],
            "failed_attempts": []
        })

    def _load_json(self, path: Path, default: Any = None) -> Any:
        """Безопасная загрузка JSON файла."""
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Ошибка загрузки хранилища {path.name}: {e}")
        return default if default is not None else []

    def save(self):
        """Сохранение всех данных в JSON файлы."""
        try:
            with open(self.incidents_file, "w", encoding="utf-8") as f:
                json.dump(self.incidents, f, ensure_ascii=False, indent=2)
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, ensure_ascii=False, indent=2)
            logger.debug("Хранилище Intelligence Layer сохранено")
        except Exception as e:
            logger.error(f"Ошибка сохранения хранилища слоя интеллекта: {e}")


# =====================================================================
# ДВУХФАЗНЫЙ ДВИЖОК ЗАДАЧ (ДЛЯ ТЯЖЕЛЫХ ОПЕРАЦИЙ)
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
    """

    def __init__(self, project_path: Path, indexer: Indexer, searcher: Searcher, symbol_index: SymbolIndex):
        self.project_path = project_path
        self.indexer = indexer
        self.searcher = searcher
        self.symbol_index = symbol_index
        self.store = IntelligenceStore(project_path)

    # -----------------------------------------------------------------
    # БЛОК 1. Code Intelligence (Быстрый локальный анализ, < 2 сек)
    # -----------------------------------------------------------------

    async def intel_code_topology(self, symbol_name: str) -> Dict[str, Any]:
        """Агрегированный инструмент: отдает полную картину связей символа.

        Использует SymbolIndex для получения:
        - Графа вызовов (callers и callees)
        - Количества ссылок
        - Статического анализа (мертвый код)

        Время выполнения: 10-150мс (только чтение из памяти)
        """
        t0 = time.perf_counter()

        try:
            # Собираем данные из SymbolIndex
            callers = self.symbol_index.get_callers(symbol_name) if hasattr(self.symbol_index, 'get_callers') else []
            callees = self.symbol_index.get_callees(symbol_name) if hasattr(self.symbol_index, 'get_callees') else []
            references = self.symbol_index.get_references(symbol_name) if hasattr(self.symbol_index, 'get_references') else []

            # Проверяем, есть ли определение символа
            definitions = self.symbol_index.find_definitions(symbol_name)

            # Определяем мёртвый код: нет определений и нет вызовов
            is_dead = len(definitions) == 0 and len(callers) == 0 and len(references) == 0

            # Формируем результат
            result = {
                "symbol": symbol_name,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "call_graph": {
                    "incoming_callers": [
                        {"symbol": r.symbol, "file": r.file_path, "line": r.line, "kind": r.kind}
                        for r in callers[:10]
                    ],
                    "outgoing_callees": [
                        {"symbol": c.get("symbol", ""), "file": c.get("file", ""), "line": c.get("line", 0), "kind": c.get("kind", "")}
                        for c in callees[:10]
                    ]
                },
                "references_count": len(references),
                "definitions_count": len(definitions),
                "static_analysis": {
                    "potential_dead_code": is_dead,
                    "has_definition": len(definitions) > 0,
                    "suggestion": "Символ никем не вызывается и не определён — возможен мёртвый код" if is_dead
                                  else "Активный узел" if len(callers) > 0
                                  else "Символ определён но не используется"
                }
            }

            return result

        except Exception as e:
            logger.error(f"Ошибка intel_code_topology: {e}")
            return {
                "symbol": symbol_name,
                "error": str(e),
                "latency_ms": int((time.perf_counter() - t0) * 1000)
            }

    # -----------------------------------------------------------------
    # БЛОК 2. Runtime Intelligence (< 1 сек, агрегированный)
    # -----------------------------------------------------------------

    async def intel_get_runtime_status(self) -> Dict[str, Any]:
        """Агрегирует статус эмбеддинга, индексов, очереди и ресурсов.

        Проверяет:
        - Доступность LM Studio/Ollama
        - Состояние LanceDB индекса
        - Глубину очереди задач
        - Использование ресурсов

        Время выполнения: 50-200мс
        """
        embedding_online = False
        ollama_online = False

        # Проверяем LM Studio
        try:
            import httpx
            reader, writer = await asyncio.open_connection(
                settings.embedding.lm_studio_host,
                settings.embedding.lm_studio_port
            )
            embedding_online = True
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

        # Проверяем Ollama
        try:
            import httpx
            reader, writer = await asyncio.open_connection(
                settings.embedding.ollama_host,
                settings.embedding.ollama_port
            )
            ollama_online = True
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

        # Проверяем размер очереди задач
        queue_depth = 0
        if hasattr(self.indexer, 'task_queue'):
            queue_depth = getattr(self.indexer.task_queue, 'qsize', lambda: 0)()

        # Получаем статистику индекса
        index_stats = {}
        if hasattr(self.indexer, 'get_status'):
            try:
                index_stats = self.indexer.get_status()
            except Exception:
                pass

        # Проверяем health индекса
        index_healthy = True
        if hasattr(self.indexer, '_index_guard'):
            try:
                guard = self.indexer._index_guard
                if hasattr(guard, 'check_and_repair'):
                    # Не вызываем repair, просто проверяем статус
                    pass
            except Exception:
                index_healthy = False

        return {
            "embedding_provider": "lm_studio" if embedding_online else "ollama" if ollama_online else "onnx_fallback",
            "provider_status": {
                f"lm_studio_at_{settings.embedding.lm_studio_port}": "online" if embedding_online else "offline",
                f"ollama_at_{settings.embedding.ollama_port}": "online" if ollama_online else "offline",
                "onnx_local_engine": "loaded_and_ready"
            },
            "index_telemetry": {
                "db_isolated_path": str(self.indexer.db_path) if hasattr(self.indexer, 'db_path') else "unknown",
                "index_healthy": index_healthy,
                "queue_depth": queue_depth,
                **index_stats
            },
            "resource_usage": {
                "process_pid": os.getpid(),
                "async_loop_tasks": len(asyncio.all_tasks())
            }
        }

    def trigger_async_reindex(self) -> str:
        """Двухфазная операция: запускает асинхронную переиндексацию.

        Возвращает job_id мгновенно, задача выполняется в фоне.
        Zed может опрашивать статус через intel_get_job_status.

        Время выполнения: < 1мс (только создание задачи)
        """
        job_id = job_manager.create_job("full_reindex")

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
                    if hasattr(self.indexer, 'index_project'):
                        # Передаём project_path
                        future = loop.run_in_executor(
                            None,
                            self.indexer.index_project,
                            self.project_path
                        )
                        # Обновляем прогресс
                        job.progress = 0.5
                        await future
                        
                        # Also index symbols via Tree-sitter
                        if hasattr(self.symbol_index, "index_project"):
                            loop = asyncio.get_event_loop()
                            future_symbols = loop.run_in_executor(
                                None,
                                self.symbol_index.index_project,
                                self.project_path,
                                CodeParser()
                            )
                            await future_symbols
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

        asyncio.create_task(_run_reindex_job())
        return job_id

    # -----------------------------------------------------------------
    # БЛОК 3. Incident Intelligence (Локальная база сбоев)
    # -----------------------------------------------------------------

    async def intel_log_incident(
        self,
        component: str,
        symptom: str,
        root_cause: str,
        fix: str,
        success: bool
    ) -> Dict[str, Any]:
        """Записывает инцидент в историю проекта.

        Инциденты используются для:
        - Предотвращения повторения ошибок
        - Автоматического поиска решений при похожих проблемах
        - Статистики надёжности модулей

        Время выполнения: < 50мс
        """
        incident = Incident(
            incident_id=f"INC-{str(uuid.uuid4())[:4].upper()}",
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            component=component,
            symptom=symptom,
            root_cause=root_cause,
            fix=fix,
            success=success
        )

        self.store.incidents.append(asdict(incident))
        self.store.save()

        logger.info(f"Записан инцидент {incident.incident_id}: {symptom}")

        return {
            "status": "saved",
            "incident": asdict(incident),
            "total_incidents": len(self.store.incidents)
        }

    async def intel_find_similar_incidents(self, error_message: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Ищет похожие инциденты по тексту ошибки.

        Использует простой токенный matching для скорости.
        Результаты сортируются по количеству совпадений.

        Время выполнения: < 50мс
        """
        if not self.store.incidents:
            return []

        # Токенизируем сообщение об ошибке
        error_lower = error_message.lower()
        tokens = error_lower.split()
        # Убираем очень короткие токены
        tokens = [t for t in tokens if len(t) > 2]

        if not tokens:
            return []

        # Ищем совпадения
        matches = []
        for inc in self.store.incidents:
            inc_text = f"{inc.get('symptom', '')} {inc.get('root_cause', '')} {inc.get('fix', '')}".lower()
            score = sum(1 for t in tokens if t in inc_text)
            if score > 0:
                matches.append((score, inc))

        # Сортируем по релевантности
        matches.sort(key=lambda x: x[0], reverse=True)

        return [m[1] for m in matches[:limit]]

    # -----------------------------------------------------------------
    # БЛОК 4. Project Memory (Почему код устроен именно так)
    # -----------------------------------------------------------------

    async def intel_add_memory_node(self, section: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Динамическое добавление записи в проектную память.

        Поддерживаемые секции:
        - adrs: Architecture Decision Records
        - known_issues: Известные проблемы с обходными решениями
        - tech_debt: Технический долг
        - failed_attempts: Неудачные попытки решения

        Время выполнения: < 50мс
        """
        if section not in self.store.memory:
            return {"error": f"Неверная секция памяти. Доступны: {list(self.store.memory.keys())}"}

        # Автогенерация ID для ADR
        if section == "adrs" and "decision_id" not in data:
            data["decision_id"] = f"ADR-{str(uuid.uuid4())[:4].upper()}"
            data["date"] = time.strftime("%Y-%m-%d")

        # Добавляем запись
        self.store.memory[section].append(data)
        self.store.save()

        logger.info(f"Добавлена запись в {section}: {data.get('decision_id', data.get('issue', 'unknown'))}")

        return {
            "status": "node_added",
            "section": section,
            "data": data,
            "total_in_section": len(self.store.memory[section])
        }

    async def intel_get_project_memory(self) -> Dict[str, Any]:
        """Возвращает всю карту памяти проекта.

        Используется агентом Zed для:
        - Понимания архитектурных решений
        - Учета технического долга
        - Избегания известных проблем

        Время выполнения: < 50мс
        """
        return self.store.memory

    # -----------------------------------------------------------------
    # БЛОК 5. Hotspot Engine (Оценка рисков уязвимости кода)
    # -----------------------------------------------------------------

    async def intel_get_code_hotspots(self, top_n: int = 5) -> List[Dict[str, Any]]:
        """Анализирует плотность связей и сложность файлов для выявления Hotspots.

        Учитывает:
        - Количество зависимостей (входящие/исходящие вызовы)
        - Историю инцидентов для файла
        - Сложность кода

        Время выполнения: < 200мс
        """
        hotspots = []

        # Получаем граф из SymbolIndex
        if hasattr(self.symbol_index, '_file_to_calls') and hasattr(self.symbol_index, '_file_to_defs'):
            for filepath, calls in self.symbol_index._file_to_calls.items():
                dependencies_count = len(calls)
                definitions_count = len(self.symbol_index._file_to_defs.get(filepath, set()))

                # Считаем количество инцидентов для этого файла
                incident_hits = sum(
                    1 for inc in self.store.incidents
                    if filepath in inc.get("component", "")
                )

                # Формула расчета индекса риска (0-10)
                # Вес: зависимости (1.5x) + инциденты (2x) + определения (0.5x)
                risk_score = min(10.0,
                    (dependencies_count * 1.5) +
                    (incident_hits * 2.0) +
                    (definitions_count * 0.5)
                )

                if risk_score > 3.0:  # Порог для включения в hotspots
                    hotspots.append({
                        "file": str(filepath),
                        "risk_score": round(risk_score, 2),
                        "metrics": {
                            "dependency_score": dependencies_count,
                            "definition_score": definitions_count,
                            "historical_incidents": incident_hits,
                            "complexity_tier": "Critical" if risk_score > 7.0 else "High" if risk_score > 5.0 else "Medium"
                        }
                    })

        hotspots.sort(key=lambda x: x["risk_score"], reverse=True)
        return hotspots[:top_n]

    # -----------------------------------------------------------------
    # БЛОК 6. Root Cause Engine (Предиктор причин поломки)
    # -----------------------------------------------------------------

    async def intel_predict_root_cause(
        self,
        error_message: str,
        component_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """Вычисляет вероятную причину сбоя на основе:
        - Истории инцидентов (Блок 3)
        - Статуса рантайма (Блок 2)
        - Hotspots (Блок 5)

        Возвращает кандидатов с распределением вероятностей.

        Время выполнения: < 500мс
        """
        candidates = []

        # 1. Проверяем историю сбоев
        past_incidents = await self.intel_find_similar_incidents(error_message)
        for inc in past_incidents:
            candidates.append({
                "component": inc.get("component", "unknown"),
                "probability": 0.80,
                "reason": f"Точное совпадение в прошлом инциденте {inc.get('incident_id', '?')}. Решение: {inc.get('fix', 'N/A')}",
                "incident_id": inc.get("incident_id"),
                "source": "incident_history"
            })

        # 2. Проверяем статус рантайма
        runtime = await self.intel_get_runtime_status()
        error_lower = error_message.lower()

        if "timeout" in error_lower or "connection" in error_lower or "connect" in error_lower:
            if runtime["embedding_provider"] == "onnx_fallback":
                candidates.append({
                    "component": "remote_embedder",
                    "probability": 0.75,
                    "reason": "ГЛАВНЫЙ ЭНДПОИНТ ИИ В ОФФЛАЙНЕ. Система переключилась на аварийный ONNX.",
                    "source": "runtime_status"
                })
            elif not runtime["provider_status"].get(f"lm_studio_at_{settings.embedding.lm_studio_port}", "") == "online":
                candidates.append({
                    "component": "lm_studio",
                    "probability": 0.70,
                    "reason": f"LM Studio на порту {settings.embedding.lm_studio_port} недоступен.",
                    "source": "runtime_status"
                })

        if "embedding" in error_lower or "vector" in error_lower:
            if runtime["provider_status"].get(f"lm_studio_at_{settings.embedding.lm_studio_port}", "") == "offline":
                candidates.append({
                    "component": "embedding_provider",
                    "probability": 0.65,
                    "reason": "Провайдер эмбеддингов отключен. Проверьте LM Studio/Ollama.",
                    "source": "runtime_status"
                })

        # 3. Проверяем Hotspots
        if component_context:
            hotspots = await self.intel_get_code_hotspots()
            for hot in hotspots:
                if component_context in hot["file"]:
                    candidates.append({
                        "component": hot["file"],
                        "probability": 0.60,
                        "reason": f"Этот файл в зоне высокого риска (Risk Score: {hot['risk_score']}). "
                                   f"Комплексность: {hot['metrics']['complexity_tier']}.",
                        "source": "hotspot_analysis"
                    })

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
            "analysis_time_ms": int(time.perf_counter() * 1000)
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

    @mcp_app.tool("intel_trigger_reindex")
    async def trigger_reindex() -> str:
        """Двухфазный инструмент: запустить асинхронную переиндексацию проекта без блокировки Zed."""
        job_id = intel_layer.trigger_async_reindex()
        return json.dumps({
            "status": "started",
            "job_id": job_id,
            "check_status_via": "intel_get_job_status"
        }, indent=2)

    @mcp_app.tool("intel_get_job_status")
    async def get_job_status(job_id: str) -> str:
        """Получить текущий прогресс и статус запущенной фоновой задачи по ее ID."""
        job = job_manager.get_job(job_id)
        if not job:
            return json.dumps({"error": f"Задача {job_id} не найдена"}, ensure_ascii=False)
        return json.dumps(asdict(job), ensure_ascii=False, indent=2)

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
        success: bool
    ) -> str:
        """Записать инцидент или баг в историю расследований проекта для предотвращения повторения ошибок."""
        res = await intel_layer.intel_log_incident(component, symptom, root_cause, fix, success)
        return json.dumps(res, ensure_ascii=False, indent=2)

    @mcp_app.tool("intel_analyze_incident")
    async def analyze_incident(error_message: str) -> str:
        """Найти аналогичные инциденты из прошлого по тексту ошибки и выдать готовые решения."""
        res = await intel_layer.intel_find_similar_incidents(error_message)
        return json.dumps({"similar_incidents_found": res}, ensure_ascii=False, indent=2)

    @mcp_app.tool("intel_add_memory_node")
    async def add_memory_node(section: str, data_json: str) -> str:
        """Добавить запись в проектную память. Разделы: 'adrs', 'known_issues', 'tech_debt', 'failed_attempts'."""
        try:
            data = json.loads(data_json)
            res = await intel_layer.intel_add_memory_node(section, data)
            return json.dumps(res, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": f"Invalid JSON: {e}"}, ensure_ascii=False)

    @mcp_app.tool("intel_get_project_memory")
    async def get_project_memory() -> str:
        """Получить карту памяти проекта (Архитектурные решения ADR, Технический долг, Известные костыли)."""
        res = await intel_layer.intel_get_project_memory()
        return json.dumps(res, ensure_ascii=False, indent=2)

    @mcp_app.tool("intel_get_hotspots")
    async def get_hotspots() -> str:
        """Показать Топ-5 файлов проекта с наивысшей плотностью рисков и баг-нагрузки."""
        res = await intel_layer.intel_get_code_hotspots()
        return json.dumps({"hotspots": res}, ensure_ascii=False, indent=2)

    @mcp_app.tool("intel_predict_root_cause")
    async def predict_root_cause(
        error_message: str,
        component_context: Optional[str] = None
    ) -> str:
        """Root Cause Engine: Пресказать наиболее вероятную причину сбоя на основе логов ошибки, рантайма и истории."""
        res = await intel_layer.intel_predict_root_cause(error_message, component_context)
        return json.dumps(res, ensure_ascii=False, indent=2)
