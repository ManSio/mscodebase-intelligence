"""Guard: the rule block must contain no digits at all."""
from __future__ import annotations

import re
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "PROTOCOL_PATCH_DRAFT.md"
text = P.read_text(encoding="utf-8")
start = text.index("```markdown", text.index("## 1."))
block = text[start + len("```markdown"):].split("```", 1)[0]
# The heading carries the section number (§11.1); the rule BODY must be digit-free.
body = "\n".join(line for line in block.splitlines() if not line.startswith("## "))
digits = re.findall(r"\d+", body)
print(f"digits in the rule body: {digits}")
print(f"body lines: {len(body.strip().splitlines())}")
raise SystemExit(1 if digits else 0)
