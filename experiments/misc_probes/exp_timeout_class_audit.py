"""Class audit: "in-thread timeout that cannot bound a non-cancellable call".

For each observed instance in src/, this reproduces the EXACT code shape in a
bounded control and asks: does the caller return within timeout+margin, or does
it block for the full simulated hang? A guard that does not fire is the bug.

Instances (source map):
  #1 index_project_runner.py:671-689  _safe_optimize  -> FIXED (daemon helper)
  #2 agentic_search.py:551-562        with pool + result(timeout=60)
  #3 index_project_runner.py:360-365  pool.submit + fut.result()  (no timeout)
  #4 error_handler.py:649-654         shared pool + result + future.cancel()
  #5 engine.py:48/505, health.py:145  non-daemon pools (atexit join risk)

Run: python experiments/misc_probes/exp_timeout_class_audit.py
"""
from __future__ import annotations

import concurrent.futures as cf
import sys
import threading
import time

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HANG = 5.0     # simulated hung worker
TMO = 1.0      # the timeout the code claims to enforce
MARGIN = 2.0   # allowed overshoot


def _hang():
    time.sleep(HANG)


def c1_fixed_helper() -> tuple[float, bool]:
    """The fixed pattern: daemon thread + Event.wait, no join."""
    done = threading.Event()

    def w():
        try:
            _hang()
        finally:
            done.set()

    th = threading.Thread(target=w, daemon=True)
    th.start()
    t0 = time.perf_counter()
    finished = done.wait(TMO)
    return time.perf_counter() - t0, finished


def c2_with_pool_result_timeout() -> float:
    """Mirror of agentic_search.py:551-562: `with ThreadPoolExecutor as pool`
    and `return pool.submit(...).result(timeout=T)`. On timeout the `with`
    __exit__ calls shutdown(wait=True) and JOINS the hung worker."""
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_hang)
        try:
            fut.result(timeout=TMO)
        except cf.TimeoutError:
            pass
    return time.perf_counter() - t0


def c3_no_timeout_future_result() -> float:
    """Mirror of index_project_runner.py:360-365: pool.submit + fut.result()
    with NO timeout -> blocks for the whole worker duration."""
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_hang)
        fut.result()          # no timeout at all
    return time.perf_counter() - t0


def c4_cancel_does_not_stop_running() -> tuple[bool, bool]:
    """Mirror of error_handler.py:649-654: result(timeout) then future.cancel().
    cancel() returns False for an already-running task (cannot stop it)."""
    pool = cf.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(_hang)
    time.sleep(0.2)                      # ensure it started
    try:
        fut.result(timeout=TMO)
    except cf.TimeoutError:
        pass
    cancelled = fut.cancel()             # running -> False
    alive = any(t.is_alive() and t.daemon is False
                for t in threading.enumerate())
    pool.shutdown(wait=False)
    return cancelled, alive


def c5_pool_workers_are_daemon() -> bool:
    """Are ThreadPoolExecutor workers daemon? If not, concurrent.futures'
    atexit `_python_exit` joins them -> a hung task blocks process exit."""
    pool = cf.ThreadPoolExecutor(max_workers=1)
    got = {}
    ev = threading.Event()

    def probe():
        got["daemon"] = threading.current_thread().daemon
        ev.set()

    pool.submit(probe)
    ev.wait(2)
    pool.shutdown(wait=False)
    return got.get("daemon", True)


def main() -> int:
    print(f"config: hang={HANG}s timeout={TMO}s margin={MARGIN}s\n")
    results: dict[str, bool] = {}

    dt, finished = c1_fixed_helper()
    ok = (dt < TMO + MARGIN) and not finished
    results["#1 fixed helper"] = not ok   # verdict = "bug present"
    print(f"#1 fixed helper (daemon+Event.wait): returned {dt:.2f}s "
          f"finished={finished} -> {'BOUNDED ✅' if ok else 'NOT BOUNDED ❌'}")

    dt = c2_with_pool_result_timeout()
    hung = dt > HANG - 0.5
    results["#2 agentic_search"] = hung
    print(f"#2 agentic_search(with pool+result(timeout)): returned {dt:.2f}s "
          f"-> {'JOINS HUNG WORKER (guard dead) ✅BUG' if hung else 'bounded'}")

    dt = c3_no_timeout_future_result()
    unbounded = dt > HANG - 0.5
    results["#3 parse phase"] = unbounded
    print(f"#3 parse phase (fut.result() no timeout): returned {dt:.2f}s "
          f"-> {'UNBOUNDED ✅BUG' if unbounded else 'bounded'}")

    cancelled, alive = c4_cancel_does_not_stop_running()
    bad = (cancelled is False and alive)
    results["#4 error_handler cancel"] = bad
    print(f"#4 error_handler (result(timeout)+cancel): cancel()={cancelled} "
          f"worker_alive={alive} -> {'CANCEL CANNOT STOP RUNNING ✅BUG' if bad else 'ok'}")

    is_daemon = c5_pool_workers_are_daemon()
    bad = (is_daemon is False)
    results["#5 non-daemon pools"] = bad
    print(f"#5 ThreadPoolExecutor worker daemon={is_daemon} -> "
          f"{'NON-DAEMON (atexit join risk) ✅BUG' if bad else 'daemon (safe)'}")

    print("\n=== VERDICTS ===")
    for k, v in results.items():
        print(f"  {k}: {'CONFIRMED' if v else 'REFUTED'}")
    # expected: #1 safe(False), #2/#3/#4/#5 confirmed issues (True)
    expected = {"#1 fixed helper": False, "#2 agentic_search": True,
                "#3 parse phase": True, "#4 error_handler cancel": True,
                "#5 non-daemon pools": True}
    consistent = all(results[k] == expected[k] for k in expected)
    print(f"\naudit consistent with source inspection: {consistent}")
    return 0 if consistent else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
