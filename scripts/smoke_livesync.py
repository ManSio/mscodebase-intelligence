#!/usr/bin/env python3
"""Смоук-тест live-sync: эмулирует расширение IDE и проверяет, что демон
принимает несохранённое изменение и отдаёт его через read_live_file.

Запуск:
    python scripts/smoke_livesync.py --url ws://127.0.0.1:8089/ws/sync \
        --project <путь к проекту> --file <абс. путь к файлу в проекте>

Требования: запущенный демон (`python -m src.remote_main`) и установленный
пакет `websockets`. Тест не пишет ничего на диск проекта — меняет только
RAM-оверлей демона.

Вывод: строка 'SMOKE LIVESYNC: PASSED' при успехе.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

try:
    import websockets
except ImportError:
    print("FAIL: нужен пакет 'websockets' (pip install websockets)")
    sys.exit(2)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8089/ws/sync")
    ap.add_argument("--project", required=True, help="абс. путь к проекту")
    ap.add_argument("--file", required=True, help="абс. путь к файлу в проекте")
    ap.add_argument("--token", default=os.environ.get("MSCODEBASE_REMOTE_TOKEN", ""))
    args = ap.parse_args()

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    live_text = f"# live-sync smoke {os.getpid()}\n"
    got_registered = False
    got_ack = False

    async with websockets.connect(args.url, additional_headers=headers) as ws:
        await ws.send(json.dumps({"type": "hello", "root": args.project, "repo_id": args.project}))
        # hello -> registered
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if msg.get("type") == "registered":
            got_registered = True
            print(f"  registered: state={msg.get('state')}")
        # change -> ack
        await ws.send(json.dumps({
            "type": "change", "root": args.project, "abs_path": args.file,
            "content": live_text, "version": 1000,
        }))
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if msg.get("type") == "ack" and msg.get("version") == 1000:
            got_ack = True
        # save -> должен очистить оверлей
        await ws.send(json.dumps({"type": "save", "root": args.project, "abs_path": args.file}))
        await asyncio.sleep(0.5)

    if got_registered and got_ack:
        print("SMOKE LIVESYNC: PASSED")
        return 0
    print("SMOKE LIVESYNC: FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
