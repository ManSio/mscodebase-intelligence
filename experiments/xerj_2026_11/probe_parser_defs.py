"""Is a call site recorded as a definition? Probe one file."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.indexing.parser import CodeParser  # noqa: E402

parser = CodeParser()
target = ROOT / "src" / "core" / "graph_rag.py"
candidates = [name for name in dir(parser) if "definition" in name and not name.startswith("_")]
print("methods:", candidates)

for name in candidates:
    try:
        syms = getattr(parser, name)(target)
    except TypeError:
        continue
    except Exception as exc:  # noqa: BLE001
        print(f"{name}: error {exc}")
        continue
    hits = [s for s in (syms or []) if s.get("line") in (93, 94, 95, 96)]
    print(f"{name}: {len(syms or [])} symbols, around line 93: {hits}")
