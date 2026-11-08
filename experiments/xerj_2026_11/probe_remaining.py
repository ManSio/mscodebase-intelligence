"""Two measurements for the remaining open items.

1. "who raises X" is detected by the matched LINE containing `raise`. How often
   is a raise multi-line, where a line check would miss it? (If it is rare, the
   AST change is not worth a parser+reindex cost.)
2. Cancellation is checked every 16 files. How much wall time is that, measured
   on this repo? (If it is tens of milliseconds, the granularity item is closed.)
"""
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import ServiceCollection  # noqa: E402
from src.mcp.tools.grep_tool import GrepCodeTool  # noqa: E402

# ── 1. raise forms ──────────────────────────────────────────────────────────
single = multiline = 0
samples = []
for path in (ROOT / "src").rglob("*.py"):
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("raise "):
            continue
        # a raise whose exception is on the same line, closing paren present
        if re.search(r"raise\s+[\w.]+\s*\(.*\)", stripped) or re.search(r"raise\s+[\w.]+$", stripped):
            single += 1
        else:
            multiline += 1
            if len(samples) < 5:
                samples.append(f"{path.relative_to(ROOT).as_posix()}:{i + 1}: {stripped[:70]}")

total = single + multiline
print(f"raise statements in src/: {total} — single-line {single}, needs-lookahead {multiline} "
      f"({multiline / max(1, total):.1%})")
for s in samples:
    print("   ", s)

# ── 2. cancellation granularity ─────────────────────────────────────────────
tool = GrepCodeTool(ServiceCollection())
pattern = re.compile(rb"def ")
files = sorted(p for p in (ROOT / "src").rglob("*.py"))[:16]
started = time.perf_counter()
for path in files:
    try:
        path.read_bytes()
    except OSError:
        pass
tiny = time.perf_counter() - started

whole = time.perf_counter()
tool._search(ROOT, None, pattern, "code", 32, 0)
full = time.perf_counter() - whole
print(f"\n16 file reads: {tiny * 1000:.1f} ms | full grep scan: {full:.2f} s "
      f"| granularity share: {tiny / max(1e-9, full):.1%}")
