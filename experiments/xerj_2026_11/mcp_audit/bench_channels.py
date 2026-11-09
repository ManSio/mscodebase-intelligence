"""Before/after for the two latency terms changed on 2026-11-09.

Sequential is the old shape (grep per identifier, tests per file); concurrent is
the shipped shape. Same process, same index, same machine.
"""

from __future__ import annotations

import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.stdout.reconfigure(encoding="utf-8")

from src.core.di_container import create_service_collection  # noqa: E402
from src.core.test_impact import predict_affected_tests  # noqa: E402
from src.mcp.tools.grep_tool import GrepCodeTool  # noqa: E402

ROOT = Path(r"D:\Project\MSCodeBase")
IDENTS = ["graph", "stage"]
FILES = [
    "src/core/search/engine.py",
    "src/mcp/tools/investigate_tool.py",
    "src/mcp/tools/search_tools.py",
]


def scan(tool, ident):
    return tool._search(  # noqa: SLF001
        ROOT, None, re.compile(re.escape(ident).encode(), re.IGNORECASE), "code", 32, 0
    )


def main() -> int:
    services = create_service_collection(ROOT)
    tool = GrepCodeTool(services)

    t = time.perf_counter()
    for ident in IDENTS:
        scan(tool, ident)
    sequential_grep = time.perf_counter() - t

    t = time.perf_counter()
    single = GrepCodeTool(services)._search(  # noqa: SLF001
        ROOT,
        None,
        re.compile(re.escape(IDENTS[0]).encode()),
        "code",
        32,
        0,
        extra_patterns=[re.compile(re.escape(IDENTS[1]).encode())],
    )
    concurrent_grep = time.perf_counter() - t
    assert single["extra_totals"], "second identifier must be counted in one walk"

    t = time.perf_counter()
    for rel in FILES:
        predict_affected_tests([rel], str(ROOT))
    sequential_tests = time.perf_counter() - t

    t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(FILES)) as pool:
        list(pool.map(lambda f: predict_affected_tests([f], str(ROOT)), FILES))
    concurrent_tests = time.perf_counter() - t

    print(f"grep  sequential={sequential_grep:.3f}s concurrent={concurrent_grep:.3f}s")
    print(f"tests sequential={sequential_tests:.3f}s concurrent={concurrent_tests:.3f}s")
    print(
        "old channel sum = "
        f"{sequential_grep + sequential_tests:.3f}s, new = "
        f"{concurrent_grep + concurrent_tests:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
