"""In-situ control #3 (REGRESSION): real IndexProjectRunner.run() parse phase.

Target: index_project_runner.py parse phase.
Pre-fix: `fut.result()` had NO timeout -> a hung `_parse_file_only` blocked the
phase forever (control: run() not returned within watchdog 6s).
Post-fix: each file is bounded by `run_bounded(..., MSCODEBASE_PARSE_TIMEOUT_SEC)`
so the phase completes even with a hung parser.

For a short control we set the per-file bound to 1s via env. If run() returns
within the watchdog, the phase is BOUNDED.

Run: PYTHONPATH=src python experiments/misc_probes/exp_in_situ_parse_timeout.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

os.environ["MSCODEBASE_PARSE_TIMEOUT_SEC"] = "1"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.indexing.index_project_runner import IndexProjectRunner  # noqa: E402

WATCHDOG = 8.0


class _FakeDBM:
    def __init__(self):
        self._lock = threading.Lock()

    def begin_write(self):
        return self._lock


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="parse_hang_"))
    (tmp / "a.py").write_text("x = 1\n", encoding="utf-8")

    runner = object.__new__(IndexProjectRunner)          # bypass __init__
    runner.path_manager = types.SimpleNamespace(is_safe_to_process=lambda p: True)
    runner.db_manager = _FakeDBM()
    runner.file_guard = types.SimpleNamespace(
        should_skip_dir=lambda d: False, should_skip_file=lambda f: False,
    )
    runner.table = None
    runner._notification_broker = None
    runner._last_reported_progress = -1
    runner._verify_and_repair_table_integrity = lambda: None

    def _hang_parse(*args, **kwargs):
        time.sleep(3600)     # a hung tree-sitter / file read

    runner._parse_file_only = _hang_parse

    done = threading.Event()

    def _run():
        try:
            runner.run(tmp, progress_callback=lambda *a: None)
        except Exception:
            pass
        finally:
            done.set()

    th = threading.Thread(target=_run, daemon=True)
    t0 = time.perf_counter()
    th.start()
    returned = done.wait(WATCHDOG)
    dt = time.perf_counter() - t0

    print(f"watchdog={WATCHDOG}s  per-file bound=1s  parse worker hangs=3600s")
    print(f"run() returned within watchdog: {returned} (after {dt:.2f}s)")
    if returned:
        print("in-situ #3 (parse phase): BOUNDED ✅ (hung file abandoned)")
        return 0
    print("in-situ #3 (parse phase): NOT BOUNDED ❌ (phase frozen)")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
