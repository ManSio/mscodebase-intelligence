"""Analyze real MCP tool usage from tool_metrics.json (historical telemetry).
Real data: which of the ~60 registered tools are actually used, error rates, latency.
"""
import json
import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

METRICS = Path(
    r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence\telemetry\tool_metrics.json"
)

def main() -> None:
    d = json.loads(METRICS.read_text(encoding="utf-8"))
    rows = []
    for tool, data in d.items():
        calls = int(data.get("calls", 0) or 0)
        errs = int(data.get("errors", 0) or 0)
        tms = int(data.get("total_ms", 0) or 0)
        route = str(data.get("route", ""))
        last = str(data.get("last_call", ""))
        rows.append((tool, calls, errs, tms, route, last))
    rows.sort(key=lambda r: -r[1])
    total = sum(r[1] for r in rows)
    print(f"{'TOOL':30}{'CALLS':>8}{'ERR':>6}{'AVG_MS':>9}   ROUTE")
    print("-" * 100)
    for tool, calls, errs, tms, route, last in rows:
        avg = tms / calls if calls else 0.0
        print(f"{tool:30}{calls:8}{errs:6}{avg:9.0f}   {route[:60]}")
    print("-" * 100)
    print(f"TOTAL_CALLS={total}  TOOLS_WITH_DATA={len(rows)}")
    zero = [t for t, c, *_ in rows if c == 0]
    print(f"TOOLS_WITH_ZERO_CALLS={len(zero)}: {zero}")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)