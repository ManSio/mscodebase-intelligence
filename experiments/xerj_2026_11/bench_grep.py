"""Time grep_code on this repo (before/after the prefilter change).

Run: python experiments/xerj_2026_11/bench_grep.py
The tool is the same one `investigate`'s grep channel calls, so the number here
is the number that decides whether that channel finishes inside its 15 s budget.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import create_service_collection  # noqa: E402
from src.mcp.tools.grep_tool import GrepCodeTool  # noqa: E402

PATTERNS = ["build_call_graph", "partner_agreement", "def +begin_write"]


def main() -> int:
    services = create_service_collection(ROOT)
    try:
        tool = GrepCodeTool(services)
        for pattern in PATTERNS:
            started = time.perf_counter()
            out = asyncio.run(tool.execute(pattern=pattern, project_root=str(ROOT)))
            elapsed = time.perf_counter() - started
            first = out.splitlines()[0] if out else ""
            print(f"{elapsed:8.2f}s  {pattern:<22}  {len(out):>6} B  {first[:90]}")
    finally:
        shutdown = getattr(services, "shutdown", None)
        if callable(shutdown):
            try:
                asyncio.run(shutdown())
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
