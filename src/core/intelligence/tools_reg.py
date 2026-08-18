"""
MCP Tool Registration for Intelligence Layer.

Вынесено из layer.py для декомпозиции God Object (P1-5 architecture review).
layer.py уменьшен с 1572 до ~1170 строк.
"""

import asyncio
import logging
from typing import Optional

from src.utils.i18n import _

logger = logging.getLogger("MSCodeBase.Intelligence")


def register_intelligence_tools(mcp_app, intel_layer):
    """
    Регистрирует 16 инструментов Intelligence Layer в MCP сервере.

    Вызывайте эту функцию при инициализации MCP-сервера в src/mcp/server.py.
    Инструменты агрегируют функциональность для уменьшения количества вызовов.
    """
    from src.core.intelligence.jobs import job_manager

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
    async def trigger_reindex(mode: str = "incremental") -> str:
        """Двухфазный инструмент: запустить асинхронную переиндексацию проекта без блокировки Zed.

        Параметры:
            mode: "incremental" — только изменённые файлы (быстро)
                  "full" — очистить БД и переиндексировать всё с нуля

        Возвращает:
            job_id — для опроса статуса через intel_get_job_status
            poll_interval_seconds — рекомендованная задержка перед первым опросом
            estimated_seconds — примерное общее время выполнения
        """
        if mode == "full":
            try:
                # ── АТОМАРНАЯ очистка БД (фикс INC-6C62 'Not found' при full reindex) ──
                # drop_table + create_table в LanceDB НЕ удаляет физические файлы:
                # новая таблица наследует цепочку версий со ссылками на мёртвые
                # фрагменты -> финальная optimize падает с 'Not found'. Вместо этого:
                # close (mmap) → gc → rmtree директории таблицы → reconnect.
                _idx = getattr(intel_layer, "indexer", None)
                _dbm = getattr(_idx, "db_manager", None) if _idx else None
                if _dbm is not None and hasattr(_dbm, "recreate_table_physical"):
                    # Guard: запрещаем concurrent search читать БД во время очистки
                    if hasattr(_dbm, "set_reindexing"):
                        _dbm.set_reindexing()
                    try:
                        if not _dbm.recreate_table_physical():
                            logger.warning(
                                "recreate_table_physical failed — fallback to drop+create"
                            )
                            try:
                                _dbm.db.drop_table(_dbm.table_name)
                            except Exception:
                                pass  # таблицы может не быть
                            _dbm.db.create_table(_dbm.table_name, schema=_dbm.schema)
                            _dbm.reset_connection()
                    finally:
                        if hasattr(_dbm, "clear_reindexing"):
                            _dbm.clear_reindexing()
                else:
                    # Fallback: если db_manager недоступен — старый rmtree (редко)
                    # Задача 4/5: индекс теперь в системной папке, не в проекте.
                    import shutil

                    from src.core.artifact_paths import (
                        get_index_dir,
                        legacy_project_dirs,
                    )

                    _targets = [get_index_dir(intel_layer.project_path)]
                    _targets += legacy_project_dirs(intel_layer.project_path)
                    ext_root = __import__('os').environ.get('_ext_root', '')
                    if ext_root:
                        _targets.append(__import__('pathlib').Path(ext_root) / '.codebase_indices')
                    for _t in _targets:
                        if _t.exists() and _t.is_dir():
                            shutil.rmtree(str(_t), ignore_errors=True)
            except Exception as e:
                return f"⚠️ Ошибка при очистке БД: {e}"
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

    @mcp_app.tool("intel_reset_index")
    async def reset_index() -> str:
        """Полный сброс индекса: удалить LanceDB БД и запустить переиндексацию с нуля. Не требует перезапуска."""
        try:
            # Consistency Engine (WS2): полный сброс — индекс недоверен до пересоздания.
            try:
                from src.core.consistency import get_consistency_tracker

                get_consistency_tracker().mark_corrupted(
                    "index", "intel_reset_index: full wipe"
                )
            except Exception:  # noqa: BLE001
                pass
            # 1. СНАЧАЛА закрываем все handle'ы БД (mmap) — до удаления файлов
            _idx = getattr(intel_layer, "indexer", None)
            _dbm = getattr(_idx, "db_manager", None) if _idx else None
            if _dbm is not None:
                try:
                    _dbm.close_for_maintenance()  # close + gc.collect() + sleep(0.5)
                except Exception as _close_err:
                    logger.warning(f"close_for_maintenance failed: {_close_err}")
            # Освобождаем PID-lock ДО rmtree (как recreate_table_physical):
            # .write_lock внутри db_dir держит открытый fd — иначе rmtree
            # упрётся в PermissionError, оставив ЧАСТИЧНО удалённую БД
            # (смешанное состояние: fresh-путь пуст, канонический — с wrapped-
            # версиями). Повторно захватываем после пересоздания директории.
            _lock_released = False
            if _dbm is not None and _dbm._db_lock is not None:
                try:
                    if _dbm._db_lock.is_held():
                        _dbm._db_lock.release()
                        _lock_released = True
                except Exception as _rel_err:
                    logger.warning(f"reset_index: PID-lock release failed: {_rel_err}")
            # 2. THEN физически удаляем директории. ignore_errors=False — залоченные
            #    mmap-файлы НЕ пропускаются молча: PermissionError → fresh DB path.
            #    Задача 4/5: основной таргет — системная папка (вне проекта).
            import shutil

            from src.core.artifact_paths import (
                get_index_dir,
                legacy_project_dirs,
            )

            _targets = [get_index_dir(intel_layer.project_path)]
            _targets += legacy_project_dirs(intel_layer.project_path)
            ext_root = __import__('os').environ.get('_ext_root', '')
            if ext_root:
                _targets.append(__import__('pathlib').Path(ext_root) / '.codebase_indices')
            _removed_ok = True
            for _t in _targets:
                if _t.exists() and _t.is_dir():
                    try:
                        shutil.rmtree(str(_t), ignore_errors=False)
                        logger.info(f"Removed index dir: {_t}")
                    except PermissionError as _perm_err:
                        _removed_ok = False
                        logger.warning(
                            f"Index dir locked (mmap): {_t} ({_perm_err}) — fresh DB path"
                        )
                    except Exception as _rm_err:
                        _removed_ok = False
                        logger.warning(f"Index dir removal failed: {_rm_err}")
            # 3. Пересоздаём чистую БД (пустая таблица) или fresh path
            if _dbm is not None:
                try:
                    if _removed_ok:
                        from pathlib import Path as _P

                        from src.sources.local_fs.windows import to_win_long_path
                        _P(to_win_long_path(_dbm.db_path)).mkdir(
                            parents=True, exist_ok=True
                        )
                        if _lock_released:
                            try:
                                _dbm._db_lock.acquire()
                            except Exception as _reacq_err:
                                logger.warning(
                                    f"reset_index: PID-lock re-acquire failed: {_reacq_err}"
                                )
                        _dbm.reset_connection()
                    else:
                        _dbm._switch_to_fresh_path()
                except Exception as _recreate_err:
                    return f"⚠️ Ошибка при пересоздании БД: {_recreate_err}"
        except Exception as e:
            return f"⚠️ Ошибка при удалении БД: {e}"
        # Запускаем переиндексацию
        job_id = await intel_layer.trigger_async_reindex()
        await asyncio.sleep(2)
        job = job_manager.get_job(job_id) if hasattr(job_manager, "get_job") else None
        progress = round(job.progress * 100) if job else 0
        p_label = job.status if job else "starting"
        enriched = intel_layer._enrich_job_response(job) if job else {}
        estimated_sec = enriched.get("estimated_seconds", 120)
        from datetime import datetime, timedelta
        _eta_dt = datetime.now() + timedelta(seconds=estimated_sec)
        _eta_time = _eta_dt.strftime("%H:%M:%S")
        if estimated_sec >= 120:
            eta_str = f"~{estimated_sec // 60}м"
        elif estimated_sec >= 60:
            eta_str = f"~{estimated_sec // 60}м {estimated_sec % 60}с"
        else:
            eta_str = f"~{estimated_sec}с"
        _now = datetime.now().strftime("%H:%M:%S")
        _bar = "[" + "█" * (progress // 7) + "░" * (15 - progress // 7) + "]"
        _pct = min(progress, 100)
        return (
            f"📦 **MSCodeBase: Indexing Started**\n"
            f"🏗️  **Progress:** {_bar} `{_pct}%`\n"
            f"⏱️ Старт: `{_now}` | Статус: `{p_label}`\n"
            f"⏱️ **ETA:** {eta_str} (готовность к `{_eta_time}`)\n"
            f"📌 Job ID: `{job_id}`\n"
            f"{'─' * 50}\n"
            f"💡 *Следующая проверка: не ранее `{_eta_time}`.*"
        )

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
        # Парсим прогресс чанков из embed лога ТЕКУЩЕГО job (инцидент 2026-08-13:
        # лог-файл общий и накапливается — без фильтра по времени парсер показывал
        # СТАРЫЕ «7426/7426 (100%)» прошлой индексации, пока текущий full reindex
        # ещё в фазе parsing (embed-строки не писаны). Фильтр: только строки,
        # не старше job.started_at.
        try:
            import datetime as _dt
            import re

            from src.core.log_manager import get_main_log_path
            _log_path = get_main_log_path()
            _started_ts = job.started_at or 0
            if _log_path.exists():
                with open(str(_log_path), 'r', encoding='utf-8', errors='replace') as _f:
                    for _line in reversed(_f.readlines()):
                        # Строки до старта job — прошлая сессия/индексация, пропускаем
                        try:
                            _line_ts = _dt.datetime.strptime(
                                _line[:19], "%Y-%m-%d %H:%M:%S"
                            ).timestamp()
                            if _line_ts < _started_ts - 2:
                                continue
                        except (ValueError, IndexError):
                            continue
                        _m = re.search(r'\[embed\]\s+(\d+)/(\d+)', _line)
                        if _m:
                            _done, _total = int(_m.group(1)), int(_m.group(2))
                            # Instant скорость (мгновенная) — из batch=4ch/0.1s=56ch/s
                            _m_inst = re.search(r'batch=\d+ch/[\d.]+s=(\d+)ch/s', _line)
                            _inst = int(_m_inst.group(1)) if _m_inst else 0
                            # Average скорость (средняя) — из avg=21ch/s
                            _m_avg = re.search(r'avg=(\d+)ch/s', _line)
                            _avg = int(_m_avg.group(1)) if _m_avg else 0
                            _m_elapsed = re.search(r'elapsed=(\d+)s', _line)
                            _elapsed = int(_m_elapsed.group(1)) if _m_elapsed else 0
                            _remaining = _total - _done
                            # ETA на основе instant скорости (более точная)
                            _speed = _inst if _inst > 0 else _avg
                            _eta = _remaining / max(_speed, 1)
                            _pct = _done / _total * 100
                            _bar_len = 25
                            _filled = int(_bar_len * _done / _total)
                            _ch_bar = "█" * _filled + "░" * (_bar_len - _filled)
                            result += (
                                f"\n"
                                f"📊 **Чанки:** {_ch_bar} `{_pct:.0f}%`\n"
                                f"   `{_done}/{_total}` ({_remaining} осталось)\n"
                                f"   Скорость: `{_inst} ch/s` (avg: `{_avg} ch/s`) | ETA: `{_eta:.0f}с ({_eta/60:.1f}мин)`\n"
                                f"   Прошло: `{_elapsed}с`"
                            )
                            break
        except Exception:
            pass
        if job.error:
            result += f"\n❌ Ошибка: {job.error}\n"
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
    async def get_project_memory(
        include_retracted: bool = False,
        verify_on_read: bool = True,
        limit: int = 3,
    ) -> str:
        """Получить карту памяти проекта (Архитектурные решения ADR, Технический долг, Известные костыли).

        ADR-0002: REFUTED-узлы скрыты по умолчанию; include_retracted=True — показать все (аудит).
        ADR-0003: verify_on_read=True (по умолчанию) — ленивая проверка ACTIVE-узлов при чтении
        (SILENT_ABSENCE -> REFUTED, найденные -> VERIFIED); False — отключить для отладки.
        limit: сколько узлов секции показывать в сводке (0 — показать все; аудит/полный список).
        Вывод включает VOR-ресипт: checked/total узлов, бюджет, latency — потребитель
        видит, сколько реально проверено в этом чтении (пол: измерение ниже пола — преждевременно).
        """
        memory, stats = await intel_layer.intel_get_project_memory(
            include_retracted=include_retracted, verify_on_read=verify_on_read
        )
        from src.utils.ui_formatter import format_project_memory

        return format_project_memory(memory, stats=stats, limit=limit)

    @mcp_app.tool("intel_add_memory_node")
    async def add_memory_node(section: str, data_json: str, status: str = "ACTIVE") -> str:
        """Добавить запись в проектную память. Разделы: 'adrs', 'known_issues', 'tech_debt', 'failed_attempts'.

        status (ADR-0002): 'ACTIVE' (по умолчанию, не проверено) | 'VERIFIED' (проверено против кода).
        REFUTED при записи недоступен — только через intel_retract_memory_node.
        """
        return await intel_layer.intel_add_memory_node(section, data_json, status)

    @mcp_app.tool("intel_retract_memory_node")
    async def retract_memory_node(node_id: str, reason: str) -> str:
        """Отозвать узел проектной памяти (ADR-0002): ACTIVE/VERIFIED → REFUTED.

        reason обязателен — отзыв не бывает молчаливым. Отозванный узел
        скрывается из intel_get_project_memory (виден с include_retracted=True).
        """
        return await intel_layer.intel_retract_memory_node(node_id, reason)

    @mcp_app.tool("intel_restore_memory_node")
    async def restore_memory_node(node_id: str, reason: str) -> str:
        """Восстановить узел из REFUTED (ручной возврат факта, ADR-0002/0003).

        Переводит узел из REFUTED обратно в ACTIVE, фиксирует причину восстановления
        (restore_reason) и время (restored_at). Добавляет флаг
        false_retraction=true для метрики ложных отзывов (спека v1).
        Восстановление без непустой причины невозможно.
        """
        return await intel_layer.intel_restore_memory_node(node_id, reason)

    @mcp_app.tool("intel_supersede_memory_node")
    async def supersede_memory_node(node_id: str, reason: str, new_node_id: str = "") -> str:
        """Пометить узел как SUPERSEDED — заменён более свежим фактом.

        SUPERSEDED — терминальный статус (не REFUTED): факт был верен, но устарел.
        В отличие от REFUTED, это не опровержение, а естественная смена знания.
        Опционально: new_node_id — ID нового узла, который замещает старый.
        """
        return await intel_layer.intel_supersede_memory_node(node_id, reason, new_node_id)

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
            logger.warning(f"Exception suppressed at tools_reg.py: {e}")
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
