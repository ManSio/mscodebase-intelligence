"""Find (and optionally clear) the vector store for an external project."""
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.artifact_paths import get_data_root, get_index_dir  # noqa: E402

PROJECT = Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pallets__itsdangerous__HEAD-672971d")
store = Path(get_index_dir(PROJECT)).parent
print("store:", store)
for child in sorted(store.rglob("*")):
    if child.is_dir() and "lance" in child.name.lower():
        print("  vector dir:", child)
if "--clear" in sys.argv:
    for child in sorted(store.rglob("*"), reverse=True):
        if child.is_dir() and "lance" in child.name.lower():
            shutil.rmtree(child, ignore_errors=True)
            print("  removed", child)
