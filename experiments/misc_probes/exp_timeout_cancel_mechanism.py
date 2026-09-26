"""Experiment: does an in-thread timeout actually bound a non-cancellable call?

Reproduces the mechanism behind the IVF finalize hang:
  - `Future.result(timeout=)` does NOT stop a running thread;
  - `ThreadPoolExecutor.shutdown(wait=True)` (in a finally) JOINS that thread;
  - hence a "timeout guard" that ends in wait=True cannot fire.

HYPOTHESIS (H1): with a worker that sleeps longer than the timeout,
  (A) result(timeout=T) raises after ~T while the worker KEEPS running;
  (B) shutdown(wait=True) then blocks for the REMAINING worker time (the hang);
  (C) shutdown(wait=False) returns immediately.
HYPOTHESIS (H2): real bounding requires a daemon thread (abandon) or a
  separate process with hard kill.

Run: python experiments/misc_probes/exp_timeout_cancel_mechanism.py
"""
from __future__ import annotations

import sys
import threading
import time

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

WORK = 6.0   # seconds the "native call" runs
TMO = 1.0    # the timeout we pretend to enforce


def _busy_box(tag: str, seconds: float = WORK) -> None:
    time.sleep(seconds)


def part_a_result_timeout_does_not_cancel() -> tuple[float, bool, float]:
    from concurrent.futures import ThreadPoolExecutor

    ex = ThreadPoolExecutor(max_workers=1)
    t0 = time.perf_counter()
    fut = ex.submit(_busy_box, "A")
    timed_out = False
    try:
        fut.result(timeout=TMO)
    except Exception:
        timed_out = True
    t_after_result = time.perf_counter() - t0
    still_running = any(th.is_alive() for th in threading.enumerate()
                        if th is not threading.current_thread())
    # emulate the code's finally:
    t1 = time.perf_counter()
    ex.shutdown(wait=True)
    t_shutdown_wait_true = time.perf_counter() - t1
    return t_after_result, still_running, t_shutdown_wait_true


def part_c_shutdown_no_wait() -> float:
    from concurrent.futures import ThreadPoolExecutor

    ex = ThreadPoolExecutor(max_workers=1)
    ex.submit(_busy_box, "C", 20.0)  # deliberately longer than the test
    time.sleep(0.2)
    t1 = time.perf_counter()
    ex.shutdown(wait=False)
    return time.perf_counter() - t1


def part_d_daemon_thread_abandon() -> tuple[float, bool]:
    t = threading.Thread(target=_busy_box, args=("D", 20.0), daemon=True)
    t.start()
    t0 = time.perf_counter()
    t.join(timeout=TMO)
    return time.perf_counter() - t0, t.is_alive()


def _child_sleep() -> None:  # pragma: no cover - subprocess entry
    time.sleep(60)


def part_e_process_hard_kill() -> float:
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    p = ctx.Process(target=_child_sleep)
    p.start()
    t0 = time.perf_counter()
    p.join(timeout=TMO)
    killed = False
    if p.is_alive():
        p.terminate()
        p.join(timeout=5)
        killed = True
    dt = time.perf_counter() - t0
    assert killed, "process should have been killed"
    return dt


def main() -> int:
    print(f"config: work={WORK}s timeout={TMO}s\n")

    a_t, a_alive, a_shutdown = part_a_result_timeout_does_not_cancel()
    print("A) result(timeout) then finally shutdown(wait=True)  [CURRENT CODE]")
    print(f"   raised timeout after : {a_t:.2f}s  (expected ~{TMO}s)")
    print(f"   worker still running : {a_alive}")
    print(f"   shutdown(wait=True)  : blocked {a_shutdown:.2f}s  (HANG)")
    print(f"   => total before return ~ {a_t + a_shutdown:.2f}s "
          f"(should have been ~{TMO}s)\n")

    c_t = part_c_shutdown_no_wait()
    print("C) shutdown(wait=False)")
    print(f"   returned in          : {c_t:.3f}s (does not join)\n")

    d_t, d_alive = part_d_daemon_thread_abandon()
    print("D) daemon thread + join(timeout)")
    print(f"   returned in          : {d_t:.2f}s; worker alive={d_alive} "
          f"(abandoned; daemon => process can exit)\n")

    e_t = part_e_process_hard_kill()
    print("E) separate process + terminate() on timeout")
    print(f"   returned in          : {e_t:.2f}s; child killed=True\n")

    verdict_h1 = (a_t < 2.0) and a_alive and (a_shutdown > 2.0)
    verdict_h2 = (d_t < 2.0) and (e_t < 2.5)
    print(f"H1 (timeout cannot cancel; wait=True hangs): "
          f"{'CONFIRMED' if verdict_h1 else 'REFUTED'}")
    print(f"H2 (daemon/process bound the call):          "
          f"{'CONFIRMED' if verdict_h2 else 'REFUTED'}")
    return 0 if (verdict_h1 and verdict_h2) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
