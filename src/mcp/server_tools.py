"""
server_tools.py — Регистрация MCP-инструментов.

Выделено из server.py (Фаза 2, Шаг 1).
Содержит:
- register_all_tools() — регистрация 18 core-инструментов + codebase hub + execute_script
- _register_intelligence_tools() — 13 intel_* инструментов (intelligence/layer.py)
- _register_inline_tools() — 12 inline @mcp.tool (debug_runtime_passport, ..., refresh_db_connection, notify_change, read_live_file, get_logs, get_health_report, ack_impact)
- dev_tools: generate_docs, bump_version, install_git_hooks (3)
- Всего: 18 + 13 + 7 + 3 = 41 инструмент (+ 1 optional execute_script = 42)
- DI Container: 18 unique services (19 add_singleton calls, 1 duplicate key)
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("mscodebase_server.tools")

# ══════════════════════════════════════════════════════════
# Регистрация core-инструментов (18 шт + execute_script optional)
# ══════════════════════════════════════════════════════════


def register_all_tools(mcp, services):
    """Регистрирует core-инструменты + codebase hub + execute_script.

    Hub & Spoke архитектура:
    - codebase(action) — единый интерфейс для всех операций с кодом
    - execute_script(code) — выполнение Python-кода (отключено по умолчанию,
      требуется MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true в .env)
    - ML-инструменты (search, symbol, graph, intel) — остаются native

    Вызывается из create_mcp_server().
    """
    _exec_script_enabled = (
        os.environ.get("MSCODEBASE_EXECUTE_SCRIPT_ENABLED", "false").lower() == "true"
    )
    from src.mcp.tools.analysis_tools import (
        GenerateChunkSummariesTool,
        GetRepoMapTool,
        GetRepoRankTool,
        ScanChangesTool,
        StructuralSearchTool,
    )
    from src.mcp.tools.codebase_tool import CodebaseTool

    if _exec_script_enabled:
        from src.mcp.tools.codebase_tool import ExecuteScriptTool
    from src.mcp.tools.doc_tools import StaleDetectorTool
    from src.mcp.tools.graph_tools import (
        CrossProjectDepsTool,
        CrossRepoSearchTool,
        GraphQueryTool,
    )
    from src.mcp.tools.investigation_tools import (
        FindSimilarBugsTool,
        GetBugCorrelationTool,
        GetHotspotsTool,
    )
    from src.mcp.tools.lifecycle_tools import (
        GetTaskStatusTool,
        SubmitBackgroundTaskTool,
        VerifyActionTool,
    )
    from src.mcp.tools.search_tools import (
        GetSymbolInfoTool,
        ImpactAnalysisTool,
        SearchCodeTool,
    )

    # Список всех инструментов для регистрации
    tool_classes = [
        # Search (3)
        SearchCodeTool,
        GetSymbolInfoTool,
        ImpactAnalysisTool,
        # Hub: codebase (единый интерфейс для всех операций)
        CodebaseTool,
        # Analysis (5)
        StructuralSearchTool,
        GetRepoMapTool,
        GetRepoRankTool,
        ScanChangesTool,
        GenerateChunkSummariesTool,
        # Graph (3 — Фаза 2: graph_query мультиплексирует 4 бывших тула)
        CrossRepoSearchTool,
        CrossProjectDepsTool,
        GraphQueryTool,
        # Investigation (3)
        GetBugCorrelationTool,
        GetHotspotsTool,
        FindSimilarBugsTool,
        # Lifecycle (3)
        SubmitBackgroundTaskTool,
        GetTaskStatusTool,
        VerifyActionTool,
        # Doc tools (1)
        StaleDetectorTool,
    ]

    # Spoke: execute_cript — только если явно включён
    if _exec_script_enabled:
        tool_classes.append(ExecuteScriptTool)
        logger.warning(
            "⚠️ ExecuteScriptTool включён — RCE-риск: код выполняется на хосте "
            "без sandbox-изоляции. Убедитесь, что понимаете последствия."
        )
    else:
        logger.info(
            "🔒 ExecuteScriptTool отключён. Включить: MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true в .env"
        )

    # ─── CodeGraph-inspired DEFAULT_TOOLS filter ──────────
    _raw_allowlist_env = os.environ.get("MSCODEBASE_MCP_TOOLS")
    _raw_allowlist = (_raw_allowlist_env or "").strip()
    if _raw_allowlist_env is not None and not _raw_allowlist:
        _show_all = True
        _allowed_names = set()
    elif _raw_allowlist:
        _allowed_names = set(_raw_allowlist.split(","))
        _show_all = False
    else:
        _allowed_names = {
            # Hub: codebase — единый интерфейс
            "codebase",
            # execute_script в allowlist при MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true
            "execute_script",
            # ML-native (не заменяются E2B)
            "search_code",
            "get_symbol_info",
            "impact_analysis",
            "intel_get_runtime_status",
            "intel_get_project_context",
            "intel_get_project_memory",
            "intel_code_topology",
            "intel_auto_collect_adrs",
            "graph_query",  # Фаза 2: мультиплексирует graph_query + cypher + related + flow
            "structural_search",
            # Diagnostic
            "diagnostics",
            "debug_runtime_passport",
            "get_runtime_counters",
            "intel_execution_timeline",
            # Doc tools
            "stale_detector",
        }
        _show_all = False

    if _show_all:
        logger.info(f"📐 MCP Tools: все {len(tool_classes)} инструментов видимы")
        _filtered_classes = tool_classes
    else:
        _before = len(tool_classes)
        _filtered_classes = []
        for _cls in tool_classes:
            _inst = _cls(services)
            _name = _inst.name
            if _name not in _allowed_names:
                logger.debug(f"  🔇 Tool hidden: {_name}")
                continue
            _filtered_classes.append(_cls)
        logger.info(
            f"📐 MCP Tools: {len(_filtered_classes)}/{_before} видимы "
            f"(MSCODEBASE_MCP_TOOLS={_raw_allowlist or 'default'})"
        )

    from mcp.types import ToolAnnotations

    _write_tool_names = {
        "codebase",
        "rename_symbol",
        "move_symbol",
        "safe_delete",
        "replace_symbol",
        "insert_before_symbol",
        "insert_after_symbol",
        "ack_impact",
        "notify_change",
        "index_project_dir",
    }

    registered = 0
    failed = []
    for tool_cls in _filtered_classes:
        try:
            instance = tool_cls(services)
            _name = instance.name
            _annotations = ToolAnnotations(
                readOnlyHint=_name not in _write_tool_names,
                idempotentHint=True,
            )
            mcp.tool(name=_name, annotations=_annotations)(instance.execute)
            registered += 1
            logger.debug(f"  🔧 Tool registered: {instance.name}")
        except Exception as e:
            failed.append((tool_cls.__name__, str(e)))
            logger.error(
                f"  ❌ Tool {tool_cls.__name__} failed to register: {e}",
                exc_info=True,
            )
    if failed:
        logger.warning(
            f"⚠️ {len(failed)}/{len(tool_classes)} tools failed to register: "
            f"{[n for n, _ in failed]}"
        )
    else:
        logger.info(f"✅ Все {registered} инструментов зарегистрированы")

    # ─── Intelligence Layer (13 инструментов) ──────
    _register_intelligence_tools(mcp, services)

    # ─── Inline diagnostic tools (7 шт) ────────────
    _register_inline_tools(mcp, services)

    # ─── Dev tools (3 шт: generate_docs, bump_version, install_git_hooks) ───
    from src.mcp.tools.dev_tools import register_dev_tools
    register_dev_tools(mcp)

    total_core = len(tool_classes)
    total_intel = 13
    total_inline = 7
    total_dev = 3
    logger.info(
        f"✅ Все инструменты зарегистрированы "
        f"({total_core} core + {total_intel} intel + {total_inline} inline + {total_dev} dev = "
        f"{total_core + total_intel + total_inline + total_dev} total)"
    )


# ══════════════════════════════════════════════════════════
# Intelligence Layer
# ══════════════════════════════════════════════════════════


def _register_intelligence_tools(mcp, services):
    """Регистрирует 13 инструментов Intelligence Layer.

    Multi-window (INC-6BCB-v2): Indexer/Searcher/SymbolIndex больше НЕ
    зарегистрированы как singleton. Используем resolve_indexer_for_request()
    для получения per-project инстанса.
    INC-6BCB-v3.1: передаём services для late-resolve.
    """
    try:
        from src.core.intelligence.layer import (
            ProjectIntelligenceLayer,
            register_intelligence_tools,
        )
        from src.mcp.tools.base import resolve_indexer_for_request

        idx = resolve_indexer_for_request(services)
        intel_layer = ProjectIntelligenceLayer(
            project_path=idx.project_path,
            indexer=idx,
            searcher=idx.searcher,
            symbol_index=idx._symbol_index,
            services=services,
        )
        register_intelligence_tools(mcp, intel_layer)

        # ═══ Авто-сбор ADR при старте ═══
        # Заполняет project_memory.json архитектурными решениями из git-лога
        # без необходимости вручную вызывать intel_auto_collect_adrs.
        try:
            result = intel_layer.intel_auto_collect_adrs(max_commits=100)
            logger.info(f"  📚 ADR auto-collect: {result[:120]}")
        except Exception as adr_e:
            logger.info(f"  📚 ADR auto-collect skip: {adr_e}")

        logger.info("  🧠 Intel tools registered (13 tools)")
    except Exception as e:
        logger.warning(f"  ⚠️ Intel layer not registered: {e}")


# ══════════════════════════════════════════════════════════
# Inline diagnostic tools (7 шт)
# ══════════════════════════════════════════════════════════


def _register_inline_tools(mcp, services):
    """Регистрирует 7 inline-инструментов, определённых прямо в server_tools.py.

    debug_runtime_passport, intel_get_project_context, intel_explain_project_state,
    get_runtime_counters, intel_tool_health, intel_execution_timeline, refresh_db_connection.
    """

    # ─── 1. debug_runtime_passport ─────────────────
    @mcp.tool("debug_runtime_passport")
    async def debug_runtime_passport() -> str:
        """Диагностика: возвращает 'паспорт' текущего процесса MCP.

        Если RUN_ID в ответе отличается от ожидаемого — значит процесс
        не перезапустился после обновления кода (Zed держит старый).
        """
        import getpass

        from src.mcp.server import (
            _BUILD_ID,
            _RUN_ID,
            _RUN_PID,
            _RUN_SOURCE_FILE,
            _RUN_STARTED_AT,
            _default_project_root,
            _ext_root,
            _services_cache,
            resolve_project_root,
        )
        from src.mcp.tools.base import _is_self_index_path
        from src.utils.ui_formatter import _val, header, section

        pr = _default_project_root or resolve_project_root()

        # Bridge state
        _bridge = None
        _bridge_err = None
        try:
            from src.core.lsp_project_bridge import read_project_from_bridge

            _bridge = str(read_project_from_bridge(max_wait=0.1))
        except Exception as e:
            _bridge_err = str(e)

        # Registry state
        _registry_paths: list[str] = []
        _registry_state_info: dict[str, Any] = {}
        _project_state: str = "UNKNOWN"
        try:
            from src.core.di_container import ProjectIndexerRegistry as PIRKey

            if _services_cache is not None:
                _reg = _services_cache.resolve(PIRKey)
                _registry_paths = [str(p) for p in _reg.get_all_paths()]
                _registry_state_info = _reg.get_stats()
                _st = _reg.get_state(pr)
                _project_state = _st.name
        except Exception as e:
            _project_state = f"ERROR: {e}"

        uptime_sec = round(time.time() - _RUN_STARTED_AT, 1)

        result = header("debug_runtime_passport", "ok")
        result += section("🧬 Process")
        result += f"• **RUN_ID:** `{_val(_RUN_ID)}`\n"
        result += f"• **BUILD_ID:** `{_val(_BUILD_ID, '<no git>')}`\n"
        result += f"• **PID:** `{_RUN_PID}`\n"
        result += f"• **Started:** `{datetime.fromtimestamp(_RUN_STARTED_AT).isoformat()}`\n"
        result += f"• **Uptime:** `{uptime_sec}s`\n"
        result += f"• **Source:** `{_val(_RUN_SOURCE_FILE)}`\n"
        result += f"• **User:** `{getpass.getuser()}`\n"
        result += section("🗂 Project")
        result += f"• **CWD:** `{_val(str(Path.cwd().resolve()))}`\n"
        result += f"• **Ext Root:** `{_val(str(_ext_root))}`\n"
        result += f"• **Default Project:** `{_val(str(pr))}`\n"
        result += f"• **Project State:** `{_val(_project_state)}`\n"
        result += section("🔗 Bridge")
        result += f"• **State:** {_val(_bridge)}\n"
        if _bridge_err:
            result += f"• **Error:** `{_val(_bridge_err)}`\n"
        result += section("📦 Registry")
        result += f"• **Paths:** {', '.join(_registry_paths) if _registry_paths else '—'}\n"
        result += f"• **Cached Projects:** `{_registry_state_info.get('cached_projects', 0)}`\n"
        result += f"• **Cache Hits:** `{_registry_state_info.get('cache_hits', 0)}`\n"
        result += f"• **Cache Misses:** `{_registry_state_info.get('cache_misses', 0)}`\n"
        result += section("🌱 Env")
        result += f"• **PROJECT_PATH:** `{_val(os.environ.get('PROJECT_PATH'))}`\n"
        result += f"• **ZED_WORKTREE_ROOT:** `{_val(os.environ.get('ZED_WORKTREE_ROOT'))}`\n"
        result += f"• **MSCODEBASE_ALLOW_SELF_INDEX:** `{_val(os.environ.get('MSCODEBASE_ALLOW_SELF_INDEX'))}`\n"
        _pp = (os.environ.get("PYTHONPATH") or "").split(os.pathsep)[0] or None
        result += f"• **PYTHONPATH[0]:** `{_val(_pp)}`\n"
        result += f"• **Self-Index Guard:** `{_val(str(_is_self_index_path(pr)))}`\n"
        return result

    # ─── 2. intel_get_project_context ─────────────
    @mcp.tool("intel_get_project_context")
    async def intel_get_project_context(project_root: str = "") -> str:
        """Единый снэпшот состояния проекта: state, index, bridge, health,
        memory (incidents/ADRs) и фоновые задачи — одним вызовом.

        Args:
            project_root: путь к проекту (по умолчанию — текущий проект).

        Returns:
            JSON со всей известной информацией о проекте.
        """
        from src.core.intelligence.project_context import ProjectContext
        from src.mcp.server import _default_project_root, resolve_project_root

        _default = _default_project_root or resolve_project_root()
        target = Path(project_root).resolve() if project_root else _default
        ctx = ProjectContext(target, services)
        snap = await ctx.capture()
        return json.dumps(snap.to_dict(), ensure_ascii=False, indent=2)

    # ─── 3. intel_explain_project_state ───────────
    @mcp.tool("intel_explain_project_state")
    async def intel_explain_project_state(project_root: str = "") -> str:
        """Человекочитаемый диагноз состояния проекта.

        Args:
            project_root: путь к проекту (по умолчанию — текущий).

        Returns:
            Текстовый диагноз с состоянием каждого слоя.
        """
        from src.core.intelligence.project_context import ProjectContext
        from src.core.runtime_coordinator import RuntimeCoordinator
        from src.mcp.server import _default_project_root, resolve_project_root

        _default = _default_project_root or resolve_project_root()
        target = Path(project_root).resolve() if project_root else _default

        coord = RuntimeCoordinator(services)
        verdict = await coord.can_execute(target)

        ctx = ProjectContext(target, services)
        snap = await ctx.capture()

        lines = [
            f"📂 Project: {target}",
            "",
            f"=== State: {verdict.state} ===",
            "",
        ]
        if verdict.ok:
            lines.append("✅ Ready to execute")
        else:
            lines.append(f"❌ Cannot execute: {verdict.reason}")
            lines.append(f"   {verdict.detail}")

        lines.append("")
        lines.append("── Index ──")
        lines.append(f"  Chunks: {snap.index_chunks or 0}")
        lines.append(f"  Files:  {snap.index_files or 0}")
        lines.append(f"  Symbols: {snap.index_symbols or 0}")
        lines.append(f"  Embedder: {snap.index_embedder or 'N/A'}")
        lines.append("")
        lines.append("── Bridge ──")
        if snap.bridge_synced:
            lines.append(f"  ✅ LSP synchronized: {snap.bridge_path}")
        else:
            lines.append("  ❌ LSP not synced")
        lines.append("")
        lines.append("── Runtime ──")
        lines.append(f"  PID: {snap.runtime_pid or 'N/A'}")
        lines.append(f"  Uptime: {snap.runtime_uptime or 0}s")
        lines.append("")
        lines.append("── Health ──")
        if snap.health_ok:
            lines.append("  ✅ OK")
        if snap.health_warnings:
            for w in snap.health_warnings[:5]:
                lines.append(f"  ⚠️  {w}")
        if snap.health_errors:
            for e in snap.health_errors[:5]:
                lines.append(f"  ❌ {e}")
        lines.append("")
        lines.append("── Memory ──")
        lines.append(f"  Incidents: {snap.memory_incidents}")
        lines.append(f"  ADRs: {snap.memory_adrs}")
        lines.append(f"  Known issues: {snap.memory_known_issues}")
        if verdict.warnings:
            lines.append("")
            lines.append("── Warnings ──")
            for w in verdict.warnings:
                lines.append(f"  ⚠️  {w}")
        if verdict.requires_reindex:
            lines.append("")
            lines.append("── Action Required ──")
            lines.append(
                "  Run intel_trigger_reindex() then check status via intel_get_job_status()"
            )
        if not verdict.requires_bridge_sync and snap.bridge_path:
            lines.append("")
            lines.append("── Bridge path ──")
            lines.append(f"  LSP workspace: {snap.bridge_path}")

        return chr(10).join(lines)

    # ─── 4. get_runtime_counters ──────────────────
    @mcp.tool("get_runtime_counters")
    async def get_runtime_counters() -> str:
        """Возвращает счётчики runtime: сколько запросов выполнено,
        сколько отклонено и по какой причине.

        Если blocked > 5% от calls — архитектура требует внимания.
        """
        from src.core.runtime_coordinator import get_counters
        from src.utils.i18n import _
        from src.utils.ui_formatter import header, section

        counters = get_counters()
        result = header("Runtime Counters", "ok")
        result += section(_("📊 Состояние"))
        calls = counters.get("can_execute_calls", 0)
        ready = counters.get("verdict_ready", 0)
        blocked_pct = round((1 - ready / max(calls, 1)) * 100, 1)
        result += _(
            "• **Checks:** {calls} | **Ready:** {ready} | **Blocked:** {blocked}%\n",
            calls=calls,
            ready=ready,
            blocked=blocked_pct,
        )
        result += section(_("🚫 Блокировки"))
        for k, v in counters.items():
            if k.startswith("verdict_blocked_") and v:
                reason = k.replace("verdict_blocked_", "").replace("_", " ")
                result += f"• {reason}: {v}\n"
        result += section(_("⚠️ Предупреждения"))
        has_warnings = False
        for k, v in counters.items():
            if k.startswith("warnings_") and v:
                w = k.replace("warnings_", "").replace("_", " ")
                result += f"• {w}: {v}\n"
                has_warnings = True
        if not has_warnings:
            result += _("• No warnings\n")
        result += section(_("⏱ Производительность"))
        result += _("• **Wait:** {time:.1f}s\n", time=counters.get("total_wait_time_sec", 0))
        return result

    # ─── 5. intel_tool_health ─────────────────────
    @mcp.tool("intel_tool_health")
    async def intel_tool_health() -> str:
        """Панель здоровья инструментов:成功率, latency, confidence, routes."""
        from src.core.error_handler import get_global_idle_metrics, get_tool_metrics_summary
        from src.utils.i18n import _

        metrics = get_tool_metrics_summary()
        if not metrics:
            return _("📊 **Tool Health**") + "\n" + _("No data yet")

        idle = get_global_idle_metrics()
        lines = [_("📊 **Tool Health**") + "\n"]
        lines.append(
            _(
                "⏱ Idle: {idle}% | Active: {active}% | Calls: {calls}",
                idle=idle["idle_pct"],
                active=idle["active_pct"],
                calls=idle["total_calls"],
            )
            + "\n"
        )
        lines.append("| Tool | Health | Calls | P50 | P95 | Repeat | Routes |")
        lines.append("|------|--------|-------|-----|-----|--------|--------|")

        for m in metrics:
            name = m["tool"]
            calls = m["calls"]
            errors = m["errors"]
            ok_rate = ((calls - errors) / max(calls, 1)) * 100
            bars = "█" * int(ok_rate / 10) + "░" * (10 - int(ok_rate / 10))
            p50 = f"{m['p50_ms']:.0f}ms" if m.get("p50_ms") else "—"
            p95 = f"{m['p95_ms']:.0f}ms" if m.get("p95_ms") else "—"
            repeat = m.get("repeat_pct", 0)
            routes = m.get("route", {})
            route_str = ", ".join(f"{k}={v}" for k, v in sorted(routes.items())) if routes else "—"
            lines.append(
                f"| {name} | {bars} {ok_rate:.0f}% | {calls} | {p50} | {p95} | {repeat:.0f}% | {route_str} |"
            )

        return "\n".join(lines)

    # ─── 7. intel_execution_timeline ──────────────
    @mcp.tool("intel_execution_timeline")
    async def intel_execution_timeline(limit: int = 15) -> str:
        """Лента последних действий системы (имплиситный success signal).

        Args:
            limit: сколько последних записей показать (по умолчанию 15, макс 50).

        Returns:
            Таблица с хронологией вызовов.
        """
        from src.core.error_handler import get_execution_timeline
        from src.utils.i18n import _

        timeline = get_execution_timeline()
        if not timeline:
            return _("📋 **Execution Timeline**") + "\n" + _("No data yet")

        limit = min(max(limit, 1), 50)
        recent = timeline[-limit:]

        lines = [_("📋 **Execution Timeline**") + "\n"]
        lines.append("| Time | Tool | ms | Status | Route | Confidence | Results |")
        lines.append("|------|------|----|--------|-------|------------|---------|")

        for e in recent:
            status = "✅" if e["ok"] else "❌"
            route = e["route"] or "—"
            conf = f"{e['confidence']:.2f}" if e["confidence"] is not None else "—"
            res = str(e["results"]) if e["results"] is not None else "—"
            lines.append(
                f"| {e['time']} | {e['tool']} | {e['ms']}ms | {status} | {route} | {conf} | {res} |"
            )

        return "\n".join(lines)

    # ─── 7. refresh_db_connection ─────────────────
    @mcp.tool("refresh_db_connection")
    async def refresh_db_connection() -> str:
        """Сбрасывает handle БД и переподключается к LanceDB.

        Вызывать после внешних миграций (drop_table, add_columns)
        или когда таблица повреждена. Не требует перезапуска MCP.
        """
        try:
            from src.mcp.tools.base import resolve_indexer_for_request

            indexer = resolve_indexer_for_request(services)
            if indexer is None:
                return "❌ No active indexer"
            db_manager = getattr(indexer, "db_manager", None)
            if db_manager is None:
                return "❌ db_manager not found on indexer"
            db_manager.reset_connection()
            count = db_manager.table.count_rows() if db_manager.table else 0
            return f"✅ DB connection refreshed. Table: {db_manager.table_name} ({count} rows)"
        except Exception as e:
            return f"❌ refresh_db_connection failed: {e}"

    # ─── 8. notify_change (standalone) ─────────────
    @mcp.tool("notify_change")
    async def notify_change(file_path: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
        """Обновляет индекс одного файла через LSP VFS или диск.

        P0: замыкает workflow edit → notify → reindex. Доступен напрямую
        (также работает через hub-инструмент index(action="notify")).

        Args:
            file_path: путь к файлу (абсолютный или относительно корня проекта).
            kwargs: опциональные доп. параметры.
        """
        from src.mcp.tools.indexing_tools import NotifyChangeTool

        tool = NotifyChangeTool(services)
        return await NotifyChangeTool.execute.__wrapped__(tool, file_path=file_path, kwargs=kwargs)

    # ─── 9. read_live_file (standalone) ────────────
    @mcp.tool("read_live_file")
    async def read_live_file(
        absolute_path: str = "",
        file_path: str = "",
        start_line: int = 0,
        end_line: int = 0,
    ) -> dict:
        """Читает файл из памяти LSP (включая несохранённые изменения).

        Доступен напрямую (также через system(action="read")).

        Args:
            absolute_path: абсолютный путь к файлу (Windows формат).
            file_path: относительный путь от корня проекта.
            start_line: первая строка (1-indexed). 0 = с начала.
            end_line: последняя строка (включительно). 0 = до конца.
        """
        from src.mcp.tools.system_tools import ReadLiveFileTool

        tool = ReadLiveFileTool(services)
        return await ReadLiveFileTool.execute.__wrapped__(
            tool,
            absolute_path=absolute_path,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        )

    # ─── 10. get_logs (standalone) ─────────────────
    @mcp.tool("get_logs")
    async def get_logs(project_root: str = "", kwargs: Optional[Dict[str, Any]] = None) -> dict:
        """Возвращает последние ошибки и предупреждения из логов проекта.

        Доступен напрямую (также через system(action="logs")).

        Args:
            project_root: путь к проекту (по умолчанию — текущий).
            kwargs: опциональные доп. параметры.
        """
        from src.mcp.tools.system_tools import GetLogsTool

        tool = GetLogsTool(services)
        return await GetLogsTool.execute.__wrapped__(tool, project_root=project_root, kwargs=kwargs)

    # ─── 11. get_health_report (standalone) ────────
    @mcp.tool("get_health_report")
    async def get_health_report(
        project_root: str = "", kwargs: Optional[Dict[str, Any]] = None
    ) -> dict:
        """Полная диагностика системы: индекс, bridge, health, providers.

        Доступен напрямую (также через system(action="health")).

        Args:
            project_root: путь к проекту (по умолчанию — текущий).
            kwargs: опциональные доп. параметры.
        """
        from src.mcp.tools.system_tools import GetHealthReportTool

        tool = GetHealthReportTool(services)
        return await GetHealthReportTool.execute.__wrapped__(
            tool, project_root=project_root, kwargs=kwargs
        )

    # ─── 12. ack_impact (standalone) ───────────────
    @mcp.tool("ack_impact")
    async def ack_impact(file_path: str) -> dict:
        """Подтверждает осведомлённость о влиянии изменений в файле.

        Вызывается после impact_analysis(). Открывает окно (TTL=600s),
        в течение которого write-операции на файле разрешены.
        Доступен напрямую (также через write(action="ack")).

        Args:
            file_path: путь к файлу, чьё влияние подтверждается.
        """
        from src.core.modification_guard import ack_impact as _ack_impact

        return _ack_impact(file_path)

    logger.info("  🔧 Inline diagnostic tools registered (12 tools)")


# ══════════════════════════════════════════════════════════
# Системный промпт
# ══════════════════════════════════════════════════════════


def register_system_prompt(mcp):
    """Регистрирует mscodebase-rules prompt для AI-агента."""
    mcp_prompt_text = """
# MSCODEBASE INTELLIGENCE CORE SYSTEM RULES

You operate under a strict deterministic execution matrix...

## 1. MCP PRIORITY RULES
- For ANY question about code → `search_code` FIRST
- If `get_index_status` returns chunks=0 → index_project_dir first
- If chunks > 0 → search_code for semantic, get_symbol_info for exact

## 2. RECONNAISSANCE BEFORE ACTION
- NEVER guess line numbers. Use get_symbol_info or grep before read_file.
- CONTEXT BUDGET: maximum 50 lines per read_file call.
- NEVER ingest entire files.

## 3. ERROR HANDLING
- If MCP tool returns error → pivot, don't retry same params
- Use get_logs for diagnostics
- Report exact error signatures

## 4. PATH PROTOCOL
- Native Windows paths (backslashes) for MCP tools
- Relative paths for notify_change (from project root)
- Absolute paths for project_root params
"""
    mcp.prompt(
        name="mscodebase-rules",
        description="Системные правила для работы с кодовой базой MSCodeBase",
    )(lambda: mcp_prompt_text)
