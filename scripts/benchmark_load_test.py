"""Нагрузочное тестирование всех MCP-инструментов MSCodeBase.

Цель: прогнать все 59 инструментов, замерить latency, собрать телеметрию,
записать результаты в бенчмарк (benchmark_results.json) и docs.

Запуск: python benchmark_load_test.py
"""

import asyncio
import json
import time
import sys
import io
from datetime import datetime
from pathlib import Path

# Фикс кодировки для Windows консоли
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Импортируем create_mcp_server ДО добавления src/ в path
# (иначе src/mcp перекроет системный mcp пакет)
from src.mcp.server import create_mcp_server

# НЕ добавляем src/ в sys.path — это ломает системный mcp пакет

# Список всех инструментов (из регистрации в server.py)
ALL_TOOLS = [
    # High-Level Intel (15)
    "intel_get_runtime_status", "intel_trigger_reindex", "intel_get_job_status",
    "intel_get_project_memory", "intel_log_incident", "intel_add_memory_node",
    "intel_get_project_context", "intel_explain_project_state",
    "intel_predict_root_cause", "intel_analyze_incident", "intel_code_topology",
    "intel_get_hotspots", "intel_get_telemetry", "intel_tool_health",
    "intel_auto_collect_adrs", "intel_execution_timeline",
    # Core MCP & Search (40)
    "search_code", "get_symbol_info", "get_variable_flow", "cross_repo_search",
    "cross_project_deps", "impact_analysis", "get_repo_map", "get_repo_rank",
    "get_hotspots", "get_bug_correlation", "get_related_files", "graph_query",
    "get_index_status", "get_index_progress", "get_index_timeline",
    "index_health", "index_project_dir", "notify_change", "watcher_status",
    "get_logs", "get_health_report", "run_health_check", "get_commit_history",
    "get_file_history", "get_branch_info", "generate_chunk_summaries",
    "scan_changes", "find_similar_bugs", "predict_eta", "verify_action",
    "get_task_status", "submit_background_task", "read_live_file",
    "structural_search", "rename_symbol", "move_symbol", "safe_delete",
    "replace_symbol", "insert_before_symbol", "insert_after_symbol",
    "ack_impact",
    # Diagnostic (3)
    "debug_runtime_passport", "get_runtime_counters", "intel_execution_timeline",
]

# Аргументы для инструментов, требующих параметров
TOOL_ARGS = {
    "intel_get_job_status": {"job_id": "5a905db7"},
    "search_code": {"query": "ETA estimated_seconds reindex", "mode": "fast"},
    "get_symbol_info": {"query": "trigger_async_reindex"},
    "get_variable_flow": {"name": "job"},
    "impact_analysis": {"symbol": "trigger_async_reindex"},
    "cross_repo_search": {"query": "index"},
    "cross_project_deps": {"symbol": "Indexer"},
    "get_repo_map": {},
    "get_repo_rank": {},
    "get_hotspots": {},
    "get_bug_correlation": {"symbol": "Indexer"},
    "get_related_files": {"file_path": "src/core/indexer.py"},
    "graph_query": {"query": "MATCH (n) RETURN n LIMIT 1"},
    "get_index_status": {},
    "get_index_progress": {},
    "get_index_timeline": {},
    "index_health": {},
    "notify_change": {"file_path": "src/core/indexer.py"},
    "watcher_status": {},
    "get_logs": {},
    "get_health_report": {},
    "run_health_check": {},
    "get_commit_history": {},
    "get_file_history": {"file_path": "src/core/indexer.py"},
    "get_branch_info": {},
    "generate_chunk_summaries": {},
    "scan_changes": {},
    "find_similar_bugs": {"query": "index error"},
    "predict_eta": {"task_type": "reindex"},
    "verify_action": {"action": "test"},
    "get_task_status": {"task_id": "test"},
    "submit_background_task": {"task": {}},
    "read_live_file": {"path": "src/core/indexer.py"},
    "structural_search": {"pattern": "def.*index"},
    "rename_symbol": {"old_name": "test", "new_name": "test2", "apply": False},
    "move_symbol": {"symbol": "test", "to_file": "test.py", "apply": False},
    "safe_delete": {"symbol": "test", "apply": False},
    "replace_symbol": {"symbol": "test", "new_code": "pass", "apply": False},
    "insert_before_symbol": {"anchor": "test", "new_code": "pass", "apply": False},
    "insert_after_symbol": {"anchor": "test", "new_code": "pass", "apply": False},
    "ack_impact": {"file_path": "src/core/indexer.py"},
    "debug_runtime_passport": {},
    "get_runtime_counters": {},
    "intel_execution_timeline": {},
    "intel_get_project_context": {},
    "intel_explain_project_state": {},
    "intel_predict_root_cause": {"error_message": "test error"},
    "intel_analyze_incident": {"error_message": "test error"},
    "intel_code_topology": {"symbol_name": "trigger_async_reindex"},
    "intel_get_hotspots": {},
    "intel_get_telemetry": {},
    "intel_tool_health": {},
    "intel_auto_collect_adrs": {},
    "intel_get_project_memory": {},
    "intel_log_incident": {
        "component": "benchmark", "symptom": "test", "root_cause": "test",
        "fix": "test", "success": True
    },
    "intel_add_memory_node": {"section": "tech_debt", "data_json": "{}"},
    "intel_trigger_reindex": {},
    "intel_get_runtime_status": {},
}


async def run_tool(mcp, tool_name: str) -> dict:
    """Выполняет один инструмент и замеряет время."""
    args = TOOL_ARGS.get(tool_name, {})
    start = time.perf_counter()
    try:
        # FastMCP хранит инструменты в mcp._tool_manager
        tool = mcp._tool_manager.get_tool(tool_name)
        if tool is None:
            return {"name": tool_name, "status": "NOT_FOUND", "ms": 0}

        result = await tool.fn(**args)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "name": tool_name,
            "status": "OK",
            "ms": round(elapsed_ms, 1),
            "result_len": len(str(result)) if result else 0,
        }
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "name": tool_name,
            "status": "ERROR",
            "ms": round(elapsed_ms, 1),
            "error": str(e)[:100],
        }


async def main():
    print("[*] Создание MCP-сервера...")
    mcp = create_mcp_server()

    print(f"[*] Всего инструментов: {len(ALL_TOOLS)}")
    results = []

    # Прогон по одному (parallel вызовы могут уронить rate-limit)
    for i, tool_name in enumerate(ALL_TOOLS, 1):
        res = await run_tool(mcp, tool_name)
        results.append(res)
        status_icon = "[+]" if res["status"] == "OK" else "[X]" if res["status"] == "ERROR" else "[!]"
        print(f"  {i:2d}/{len(ALL_TOOLS)} {status_icon} {tool_name:35s} {res['ms']:7.1f}ms {res['status']}")

    # Статистика
    ok = [r for r in results if r["status"] == "OK"]
    errors = [r for r in results if r["status"] == "ERROR"]
    not_found = [r for r in results if r["status"] == "NOT_FOUND"]

    total_ms = sum(r["ms"] for r in results)
    avg_ms = total_ms / len(results) if results else 0

    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_tools": len(ALL_TOOLS),
        "ok": len(ok),
        "errors": len(errors),
        "not_found": len(not_found),
        "total_ms": round(total_ms, 1),
        "avg_ms": round(avg_ms, 1),
        "results": results,
    }

    # Сохраняем в бенчмарк
    out_path = Path("benchmark_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n[*] ИТОГО: {len(ok)} OK, {len(errors)} ERROR, {len(not_found)} NOT_FOUND")
    print(f"⏱  Общее время: {total_ms:.1f}ms, среднее: {avg_ms:.1f}ms")
    print(f"[*] Результаты: {out_path}")

    if errors:
        print("\n[X] ОШИБКИ:")
        for e in errors:
            print(f"  - {e['name']}: {e['error']}")


if __name__ == "__main__":
    asyncio.run(main())
