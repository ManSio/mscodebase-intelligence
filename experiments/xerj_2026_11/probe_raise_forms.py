"""Does the `raise` line-check miss anything real? (redone: name on another line?)"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]

misses = []
with_name = 0
alone = 0
for path in (ROOT / "src").rglob("*.py"):
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not (stripped == "raise" or re.fullmatch(r"raise\s*\(", stripped)
                or re.fullmatch(r"raise\s+\(", stripped)):
            continue
        alone += 1
        # the exception name is expected on one of the next two lines
        for follow in lines[i + 1:i + 3]:
            if re.match(r"\s*[A-Za-z_][\w.]*\s*\(", follow):
                misses.append(f"{path.relative_to(ROOT).as_posix()}:{i + 1}")
                break
        else:
            with_name += 1

total = alone + with_name
print(f"raise statements whose line has no exception name: {alone}")
print(f"  of them, name on the next 2 lines (line-heuristic MISSES these): {len(misses)}")
print(f"  other (comment/blank continuation): {with_name}")
for m in misses[:8]:
    print("   miss:", m)
