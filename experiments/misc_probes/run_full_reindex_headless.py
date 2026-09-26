"""Headless full-reindex driver via the production MCP path.

Starts the real mscodebase-intelligence MCP server (`python -m src.main`) as a
stdio child, then calls the SAME tools Zed would:
    intel_trigger_reindex(mode="full")  -> job_id
    intel_get_job_status(job_id)        -> poll until completed/failed
This exercises the real graph-lock + recreate_table_physical + normalized-path
reindex, without needing Zed.

Run with the EXTENSION venv python (it has the `mcp` client):
    <extension>\\venv\\Scripts\\python.exe experiments\\misc_probes\\run_full_reindex_headless.py
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

EXT = Path(r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence")
PY = EXT / "venv" / "Scripts" / "python.exe"
PROJECT = Path(r"D:\Project\MSCodeBase")

LOG = Path(os.environ.get("TEMP", ".")) / "opencode" / "full_reindex_headless.log"
LOG.parent.mkdir(parents=True, exist_ok=True)

JOB_RE = re.compile(r"Job ID:\s*`([0-9a-f]+)`")
STATUS_RE = re.compile(r"Статус:\s*`(\w+)`")
PCT_RE = re.compile(r"`(\d+)%`")
ERR_RE = re.compile(r"Ошибка:\s*(.+)")


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


async def main() -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["PYTHONPATH"] = str(EXT)
    env["PROJECT_PATH"] = str(PROJECT)
    env["PYTHONUTF8"] = "1"

    params = StdioServerParameters(
        command=str(PY), args=["-u", "-m", "src.main"], env=env, cwd=str(EXT),
    )

    # Bounded poll budget (full reindex ~10-20 min on CPU embedder).
    deadline = time.time() + float(os.environ.get("REINDEX_TIMEOUT_SEC", "2400"))

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            log("initialize...")
            await session.initialize()

            tools = [t.name for t in (await session.list_tools()).tools]
            log(f"tools={len(tools)} trigger_present={'intel_trigger_reindex' in tools}")
            if "intel_trigger_reindex" not in tools:
                log("FAIL: intel_trigger_reindex not registered")
                return 2

            if os.environ.get("DRY_RUN") == "1":
                log("DRY_RUN: plumbing OK, not triggering")
                return 0

            log("calling intel_trigger_reindex(mode=full)...")
            res = await session.call_tool("intel_trigger_reindex", {"mode": "full"})
            text = "\n".join(
                c.text for c in res.content if getattr(c, "type", "") == "text"
            )
            log("--- trigger response ---")
            for ln in text.splitlines():
                log("  " + ln)
            m = JOB_RE.search(text)
            if not m:
                log("FAIL: no job_id parsed")
                return 2
            job_id = m.group(1)
            log(f"job_id={job_id}")

            last = ""
            while time.time() < deadline:
                await asyncio.sleep(20)
                st = await session.call_tool("intel_get_job_status", {"job_id": job_id})
                stext = "\n".join(
                    c.text for c in st.content if getattr(c, "type", "") == "text"
                )
                sm = STATUS_RE.search(stext)
                status = sm.group(1) if sm else "?"
                pm = PCT_RE.search(stext)
                pct = pm.group(1) if pm else "?"
                line = f"status={status} pct={pct}%"
                em = ERR_RE.search(stext)
                if em:
                    line += f" err={em.group(1).strip()}"
                if line != last:
                    log(line)
                    last = line
                if status in ("completed", "failed", "error"):
                    log(f"DONE: {status}")
                    log("--- final status ---")
                    for ln in stext.splitlines():
                        log("  " + ln)
                    return 0 if status == "completed" else 1
            log("TIMEOUT waiting for job")
            return 3


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
