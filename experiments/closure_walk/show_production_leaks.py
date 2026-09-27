import json
from pathlib import Path

data = json.loads(Path("experiments/closure_walk/results/closure_walk.json").read_text(encoding="utf-8"))
for v in data["out_scope_violations"]:
    if v["file"].startswith(("src/", "scripts/")):
        print(f"{v['file']}:{v['line']} [{v['pattern']}] {v['match']}")
