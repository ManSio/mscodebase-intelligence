import json
from collections import Counter
from pathlib import Path

data = json.loads(Path("experiments/closure_walk/results/closure_walk.json").read_text(encoding="utf-8"))
violations = data["out_scope_violations"]
files = set(v["file"] for v in violations)
dirs = Counter(v["file"].split("/")[0] for v in violations)
exts = Counter(Path(v["file"]).suffix for v in violations)
print(f"Total violations: {len(violations)} in {len(files)} files")
print("\nBy top-level dir:")
for d, c in sorted(dirs.items(), key=lambda x: -x[1]):
    print(f"  {d}: {c}")
print("\nBy extension:")
for e, c in sorted(exts.items(), key=lambda x: -x[1]):
    print(f"  {e}: {c}")
