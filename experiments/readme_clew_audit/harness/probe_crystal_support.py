import base64
import json
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

KWS = ["Claude Code", "opencode", "Codex", "Cursor", "hook", "macOS", "Linux",
       "Windows", "unsupported", "requires", "supported"]

for f in ("INSTALL.md", "README.md"):
    p = subprocess.run(
        ["gh", "api", f"repos/Tirthahq/crystal-memory/contents/{f}?ref=7a129db"],
        capture_output=True)
    try:
        m = json.loads(p.stdout.decode("utf-8", "replace"))
        t = base64.b64decode(m["content"]).decode("utf-8")
    except Exception as e:
        print(f"=== {f}: unavailable ({e}) ===")
        continue
    print(f"=== {f} ({len(t)} chars) ===")
    seen = set()
    for kw in KWS:
        n = 0
        for line in t.split("\n"):
            if kw.lower() in line.lower() and line.strip() and line.strip() not in seen:
                seen.add(line.strip())
                print(f"  [{kw}] {line.strip()[:160]}")
                n += 1
                if n >= 3:
                    break