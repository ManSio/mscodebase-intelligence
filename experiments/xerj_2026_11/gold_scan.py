"""Gold draft (step 1 of 2): every occurrence per candidate symbol.

Output goes to gold_scan.txt next to this file; the frozen gold set is written
by hand afterwards from that file plus reading the source.
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11")
REPOS = {
    "itsdangerous": BASE / "pallets__itsdangerous__HEAD-672971d",
    "iniconfig": BASE / "pytest-dev__iniconfig__HEAD-a9e0ad1",
}
SYMBOLS = {
    "itsdangerous": ["Signer", "TimestampSigner", "Serializer", "URLSafeSerializer",
                     "BadSignature", "want_bytes"],
    "iniconfig": ["IniConfig", "ParseError", "Config", "SectionWrapper", "parse"],
}

out: list[str] = []
for repo, root in REPOS.items():
    out.append(f"######## {repo} ({root.name})")
    files = sorted(p for p in root.rglob("*.py") if ".git" not in p.parts)
    for symbol in SYMBOLS[repo]:
        out.append(f"\n--- {symbol}")
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace")
            hits = [(i, line.strip()) for i, line in enumerate(text.splitlines(), 1)
                    if pattern.search(line)]
            if hits:
                rel = path.relative_to(root).as_posix()
                out.append(f"  {rel}: {len(hits)} hits")
                for line_no, line in hits[:4]:
                    out.append(f"      {line_no}: {line[:110]}")

target = Path(__file__).with_name("gold_scan.txt")
target.write_text("\n".join(out), encoding="utf-8", newline="")
print(f"wrote {target.name}: {len(out)} lines")
