r"""scripts/redact.py — scrub personal paths and usernames from text output.

Usage:
    python scripts/redact.py < input.txt > output.txt
    python scripts/redact.py input.txt output.txt
    python scripts/redact.py --selftest

Replaces:
    - Drive-rooted project paths (D:\Project\..., D:/Project/...) → <project>
    - Owner username (word-bounded) → <user>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

USERNAME = "mis" + "ha"
PATTERNS = [
    (re.compile(r"[A-Za-z]:[\\/]Project"), "<project>"),
    (re.compile(rf"(?<![A-Za-z]){USERNAME}(?![A-Za-z])"), "<user>"),
]


def redact(text: str) -> str:
    for pat, repl in PATTERNS:
        text = pat.sub(repl, text)
    return text


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        sample = r"Path: D:\Project\MSCodeBase\src — user misha confirmed."
        out = redact(sample)
        assert "<project>" in out, f"drive path not redacted: {out}"
        assert "<user>" in out, f"username not redacted: {out}"
        assert "D:" not in out, f"drive letter remains: {out}"
        assert "misha" not in out, f"username remains: {out}"
        print("selftest PASS")
        return 0
    if len(sys.argv) == 3:
        src, dst = Path(sys.argv[1]), Path(sys.argv[2])
        dst.write_text(redact(src.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
        return 0
    text = sys.stdin.read()
    sys.stdout.write(redact(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
