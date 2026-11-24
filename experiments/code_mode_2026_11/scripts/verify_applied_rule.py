"""Verify the applied §11.1 in the live protocol: digit-free body, core length budget."""
from __future__ import annotations

import re
from pathlib import Path

P = Path.home() / ".config" / "opencode" / "AGENTS.md"
text = P.read_text(encoding="utf-8")
lines = text.splitlines()

start = next(i for i, line in enumerate(lines) if line.startswith("## §11.1"))
end = next(i for i, line in enumerate(lines) if i > start and line.startswith("## §12"))
body = [line for line in lines[start + 1:end] if line.strip()]

digits = [d for line in body for d in re.findall(r"\d+", line)]
print(f"§11.1 at line {start + 1}, body lines {len(body)}")
print(f"digits in body: {digits}")
print(f"core lines total: {len(lines)}")
print(f"has Guard: {'Guard:' in '\n'.join(body)}")
ok = not digits and len(lines) <= 200 and "Guard:" in "\n".join(body)
print("VERDICT:", "PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
