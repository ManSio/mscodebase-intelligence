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
    Регистрирует 13 инструментов Intelligence Layer в MCP сервере.

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
                import shutil
                # Удаляем только .codebase_indices (НЕ project_path!)
                _targets = [
                    intel_layer.project_path / '.codebase_indices',
                ]
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
        """Полный сброс индекса: удалить LanceDB БД и запустить переиндексацию с нуля. Не требует перезагрузки."""
        try:
            import shutil
            # Удаляем только .codebase_indices (НЕ project_path!)
            _targets = [
                intel_layer.project_path / '.codebase_indices',
            ]
            ext_root = __import__('os').environ.get('_ext_root', '')
            if ext_root:
                _targets.append(__import__('pathlib').Path(ext_root) / '.codebase_indices')
            for _t in _targets:
                if _t.exists() and _t.is_dir():
                    shutil.rmtree(str(_t), ignore_errors=True)
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
        # Парсим прогресс чанков из последнего embed лога
        try:
            import re
            from src.core.log_manager import get_main_log_path
            _log_path = get_main_log_path()
            if _log_path.exists():
                with open(str(_log_path), 'r', encoding='utf-8', errors='replace') as _f:
                    for _line in reversed(_f.readlines()):
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
