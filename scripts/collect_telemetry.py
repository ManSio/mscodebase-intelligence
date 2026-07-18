"""Telemetry Collector — ежедневный сбор метрик работы MCP.

Сохраняет снимок всех счётчиков в JSON-файл с временной меткой.
Файлы хранятся в .codebase_indices/telemetry/ по дате:

    .codebase_indices/telemetry/2026-07-05.json
    .codebase_indices/telemetry/2026-07-06.json
    ...

Использование:
    python scripts/collect_telemetry.py          # разовый сбор
    python scripts/collect_telemetry.py --daily   # добавить в планировщик Windows

Формат файла:
    [
        {
            "date": "2026-07-05",
            "captured_at": "2026-07-05T12:00:00",
            "uptime_sec": 3600,
            "counters": { ... },
            "project_context": { ... }
        },
        ...
    ]

Графики можно строить из накопившихся JSON-файлов любой BI-системой.
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path


def _setup_env():
    """Добавляет install-директорию в sys.path для импорта src.*."""
    candidates = [
        Path(__file__).resolve().parent.parent,  # dev repo
        Path(os.environ.get("PYTHONPATH", "")),  # env var
    ]
    for p in candidates:
        if p.exists() and str(p) not in sys.path:
            sys.path.insert(0, str(p))


def get_telemetry_dir() -> Path:
    """Возвращает директорию для хранения телеметрии."""
    for base in (".mscodebase", ".codebase_indices"):
        d = Path.cwd() / base / "telemetry"
        d.mkdir(parents=True, exist_ok=True)
        if d.exists():
            return d
    d = Path.cwd() / ".codebase_indices" / "telemetry"
    d.mkdir(parents=True, exist_ok=True)
    return d


def collect_counters() -> dict:
    """Собирает runtime счётчики."""
    result = {}
    try:
        from src.core.runtime_coordinator import get_counters
        from src.core.passport import get_uptime, RUN_ID, BUILD_ID
        result["counters"] = get_counters()
        result["uptime_sec"] = round(get_uptime(), 1)
        result["run_id"] = RUN_ID
        result["build_id"] = BUILD_ID or "<no git>"
    except Exception as e:
        result["counters_error"] = str(e)
    return result


def collect_project_stats() -> dict:
    """Собирает статистику проекта (state, index, chunks)."""
    result = {}
    try:
        from src.core.di_container import create_service_collection, IndexerFactoryKey
        from src.core.project_indexer_registry import ProjectIndexerRegistry
        from src.mcp.server import resolve_project_root, reset_project_root_cache

        reset_project_root_cache()
        pr = resolve_project_root()
        services = create_service_collection(pr)
        factory = services.resolve(IndexerFactoryKey)
        registry = services.resolve(ProjectIndexerRegistry)

        t0 = time.time()
        indexer = registry.get_indexer(pr, factory=factory)
        status = indexer.get_status()
        state = registry.get_state(pr)
        dt = round((time.time() - t0) * 1000, 1)

        result = {
            "project_path": str(pr),
            "state": state.name,
            "index_chunks": status.get("total_chunks", 0),
            "index_files": status.get("unique_files", 0),
            "index_symbols": status.get("symbols_count", status.get("symbols", 0)),
            "index_latency_ms": dt,
        }
    except Exception as e:
        result["error"] = str(e)
    return result


def build_snapshot() -> dict:
    """Строит полный снэпшот метрик (синхронно, без asyncio)."""
    snapshot = {
        "date": date.today().isoformat(),
        "captured_at": datetime.now().isoformat(timespec="seconds"),
    }
    snapshot.update(collect_counters())
    snapshot["project"] = collect_project_stats()

    # Resource monitor (RAM/CPU)
    try:
        from src.core.resource_monitor import get_global_resource_monitor
        snapshot["resources"] = get_global_resource_monitor().get_summary()
    except Exception:
        snapshot["resources"] = {"error": "unavailable"}

    # LLM ping + model info
    try:
        from src.core.remote_embedder import RemoteEmbedder
        _emb = RemoteEmbedder()
        _t0 = time.time()
        _emb.embed("ping")
        _ping = round((time.time() - _t0) * 1000, 1)
        _info = _emb.get_model_info()
        snapshot["llm"] = {
            "ping_ms": _ping,
            "provider": _info["provider"],
            "model": _info["model"],
            "configured_model": _info["configured_model"],
        }
    except Exception:
        snapshot["llm"] = {"error": "unavailable"}
    return snapshot


def save_snapshot(snapshot: dict, telemetry_dir: Path) -> Path:
    """Сохраняет снимок в файл (добавляет к существующим записям за день)."""
    date_str = snapshot["date"]
    filepath = telemetry_dir / f"{date_str}.json"

    entries = []
    if filepath.exists():
        try:
            entries = json.loads(filepath.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                entries = []
        except Exception:
            entries = []

    entries.append(snapshot)
    filepath.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return filepath


def get_history(days: int = 30) -> list:
    """Возвращает историю метрик за последние N дней."""
    telemetry_dir = get_telemetry_dir()
    history = []
    from datetime import timedelta

    for i in range(days):
        d = (date.today() - timedelta(days=i)).isoformat()
        fp = telemetry_dir / f"{d}.json"
        if fp.exists():
            try:
                entries = json.loads(fp.read_text(encoding="utf-8"))
                if isinstance(entries, list):
                    history.extend(entries)
            except Exception:
                pass
    return history


def setup_daily_task():
    """Создаёт задачу в планировщике Windows для ежедневного сбора в 23:00."""
    script_path = Path(__file__).resolve()
    python_exe = sys.executable
    task_name = "MSCodeBase Telemetry Collector"
    cmd = (
        f'schtasks /create /tn "{task_name}" /tr '
        f'"{python_exe} {script_path}" /sc daily /st 23:00 /f'
    )
    print(f"Creating task: {task_name}")
    print(f"Command: {cmd}")
    exit_code = os.system(cmd)
    if exit_code == 0:
        print("Task created successfully")
    else:
        print(f"Task creation returned: {exit_code}")


def main():
    parser = argparse.ArgumentParser(description="MSCodeBase Telemetry Collector")
    parser.add_argument("--daily", action="store_true", help="Add to Windows Task Scheduler")
    parser.add_argument("--history", type=int, default=0,
                        help="Show last N days of history as JSON")
    args = parser.parse_args()

    _setup_env()

    if args.history > 0:
        history = get_history(args.history)
        print(json.dumps(history, ensure_ascii=False, indent=2))
        return 0

    if args.daily:
        setup_daily_task()
        return 0

    telemetry_dir = get_telemetry_dir()
    snapshot = build_snapshot()
    filepath = save_snapshot(snapshot, telemetry_dir)

    print(f"Telemetry: {filepath}")
    print(f"  Date:    {snapshot['date']}")
    print(f"  Uptime:  {snapshot.get('uptime_sec', 0)}s")
    print(f"  Project: {snapshot.get('project', {}).get('project_path', 'N/A')}")
    print(f"  State:   {snapshot.get('project', {}).get('state', 'N/A')}")
    print(f"  Chunks:  {snapshot.get('project', {}).get('index_chunks', 0)}")
    print(f"  Counters: {len(snapshot.get('counters', {}))} metrics")
    return 0


if __name__ == "__main__":
    exit(main())
