"""X5b — the decisive test for the ledger write.

crystal_act._save() wraps os.replace() in `except Exception:` and unlinks the temp
file. So a PermissionError does not crash the hook: THE WRITE IS DROPPED. The
ledger is the rotation/backoff state. Losing a write means the anti-repeat
counter does not advance, and the author's own comment (crystal_act.py:240-244)
says that exact outcome is the harm the atomic write was introduced to prevent.

Question: on Windows, does a concurrent holder of the ledger file cause the
delivery state to be silently lost?
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

SRC = pathlib.Path(r"D:\Project\_reference_repos\Tirthahq__crystal-memory__HEAD-6cb8479")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td) / "repo"
        shutil.copytree(SRC, repo, ignore=shutil.ignore_patterns(".git"))
        sys.path.insert(0, str(repo / "scripts"))
        spec = importlib.util.spec_from_file_location("crystal_act", repo / "scripts" / "crystal_act.py")
        ca = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(ca)

        ca.LEDGER = pathlib.Path(td) / "scratch" / ".act-ledger.json"
        ca.LEDGER.parent.mkdir(parents=True, exist_ok=True)
        ca.LEDGER.write_text("{}", encoding="utf-8")

        # CONTROL: no contention. The write must land.
        ca._save({"a": 1})
        ctl = json.loads(ca.LEDGER.read_text(encoding="utf-8"))
        print(f"CONTROL  no contention      -> ledger now {ctl}   (must be {{'a': 1}})")
        ctl_ok = ctl == {"a": 1}

        # TEST: a second handle holds the ledger open, exactly as a concurrent
        # hook / indexer / AV scan does on Windows.
        ca.LEDGER.write_text("{}", encoding="utf-8")
        holder = ca.LEDGER.open("r+", encoding="utf-8")
        try:
            ca._save({"b": 2})
            raised = None
        except Exception as e:                      # must NOT raise: it is swallowed
            raised = f"{type(e).__name__}: {e}"
        finally:
            holder.close()

        after = json.loads(ca.LEDGER.read_text(encoding="utf-8"))
        print(f"TEST     with a live holder -> _save raised: {raised}")
        print(f"         ledger content after the write: {after}")
        lost = after == {} and raised is None
        print(f"         the increment was LOST silently: {lost}")

        leftovers = list(ca.LEDGER.parent.glob("*.tmp*"))
        print(f"         temp files left behind: {[p.name for p in leftovers]}")

        print()
        if not ctl_ok:
            print("VERDICT X5b: VOID — even the control failed, the harness is wrong.")
        elif lost:
            print("VERDICT X5b: CONFIRMED — on Windows a live handle on the ledger makes "
                  "os.replace raise, the except swallows it, the temp file is deleted, and the "
                  "delivery/rotation state is DISCARDED WITH NO WARNING. The author's stated harm "
                  "('over-delivers AND lets the next save write a nearly-empty ledger over a good "
                  "one') is still reachable here, by a different mechanism than the one the "
                  "atomic write was added to close.")
            return 0
        else:
            print(f"VERDICT X5b: REFUTED — ledger content after contention = {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
