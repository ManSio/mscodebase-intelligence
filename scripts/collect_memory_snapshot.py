#!/usr/bin/env python3
"""collect_memory_snapshot.py — ежедневный снимок метрик памяти для Experiment 1-L.

Append JSONL: {date_utc, revision, memory_metrics} — только чтение memory store
(JSON-файлы вне проекта), MCP-рантайм и LanceDB НЕ нужны (§5.17: БД — только
через MCP; memory store — безопасный источник).

Usage:
    python scripts/collect_memory_snapshot.py [--out <jsonl>]

Out по умолчанию: <data_root>/experiments/longitudinal_1L.jsonl
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# §5.9 ENCODING SAFETY (Windows)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — переключение кодировки опционально
        pass


def _revision() -> str:
    try:
        p = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        rev = (p.stdout or b"").decode("utf-8", "replace").strip()
        return rev if p.returncode == 0 and rev else "unknown"
    except Exception:  # noqa: BLE001 — диагностика
        return "unknown"


def _memory_metrics() -> dict:
    from src.core.intelligence.store import IntelligenceStore

    try:
        return IntelligenceStore(ROOT).memory_metrics()
    except Exception as e:  # noqa: BLE001 — диагностика: снимок не должен падать
        return {"error": str(e)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Experiment 1-L: ежедневный снимок памяти")
    parser.add_argument("--out", default="", help="путь к JSONL (по умолч. data_root/experiments/longitudinal_1L.jsonl)")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else None
    if out_path is None:
        from src.core.artifact_paths import get_data_dir

        out_path = get_data_dir(ROOT) / "experiments" / "longitudinal_1L.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "revision": _revision(),
        "memory_metrics": _memory_metrics(),
    }

    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False, default=str) + "\n")

    print(f"SNAPSHOT: {snapshot['date_utc']} rev={snapshot['revision'][:12]} "
          f"-> {out_path} (lines={sum(1 for _ in open(out_path, encoding='utf-8'))})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — краш = exit 1
        import traceback

        traceback.print_exc()
        sys.exit(1)
