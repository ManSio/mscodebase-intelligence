import os
import sys
from pathlib import Path

target = os.environ.get("TARGET_REPO")
if target:
    sys.path.insert(0, target)
else:
    candidate = Path(__file__).resolve().parents[1] / "repo"
    if candidate.is_dir():
        sys.path.insert(0, str(candidate))
