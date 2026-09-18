# -*- coding: utf-8 -*-
"""pytest-plugin: dynamic trace тест(-функция → исполняемые src/* функции).

Bootstrap Pipeline Step 3: сколько связей тест→функция даёт РЕАЛЬНЫЙ запуск
(dynamic), в сравнении со статикой (0% по имени). Плагин импортируется из
корня репо как ``-p src.core.bootstrap_trace_plugin`` (пакет `src` в sys.path).

Использование (свой репо):
    python -m pytest tests/ -p src.core.bootstrap_trace_plugin

Для чужого проекта (корень репо должен лежать в sys.path):
    TRACE_SRC_ROOT=<корень исходников> TRACE_OUT=<путь к json> \\
        python -m pytest <project> -p src.core.bootstrap_trace_plugin

Дефолты: SRC_ROOT = <репо>/src, TRACE_OUT = cwd/trace_result.json.
"""

import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

SRC_ROOT = os.environ.get(
    "TRACE_SRC_ROOT",
    str(Path(__file__).resolve().parent.parent.parent / "src"),
)
TRACE_OUT = os.environ.get(
    "TRACE_OUT",
    os.path.join(os.getcwd(), "trace_result.json"),
)

per_test: dict[str, set[str]] = {}
current_test: list[str | None] = [None]

EXCLUDE_NAMES = {"__module__", "__new__", "__sizeof__", "__dir__", "__getattribute__", "__repr__", "__str__", "<module>"}


def _trace(frame, event, arg):
    if event != "call":
        return _trace
    if current_test[0] is None:
        return _trace
    fn = frame.f_code.co_filename
    if not fn.startswith(SRC_ROOT):
        return _trace
    qname = (frame.f_code.co_name or "") + "@" + fn[len(SRC_ROOT) + 1 :]
    if qname in EXCLUDE_NAMES:
        return _trace
    per_test[current_test[0]].add(qname)
    return _trace


def pytest_runtest_call(item):
    current_test[0] = item.nodeid
    if item.nodeid not in per_test:
        per_test[item.nodeid] = set()
    sys.settrace(_trace)


def pytest_runtest_teardown(item, nextitem):
    if current_test[0] is not None:
        sys.settrace(None)
        current_test[0] = None


def pytest_sessionfinish(session, exitstatus):
    json_path = TRACE_OUT
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({k: sorted(v) for k, v in per_test.items()}, f, indent=1)
    total = len(per_test)
    linked = [t for t, funcs in per_test.items() if funcs]
    unique_src_funcs = {f for funcs in per_test.values() for f in funcs}
    avg = sum(len(per_test[t]) for t in linked) / max(1, len(linked))
    print("\n[dynamic_trace] ============================================")
    print(f"[dynamic_trace] total tests traced: {total}")
    print(f"[dynamic_trace] tests executing >=1 src function: {len(linked)} ({100.0 * len(linked) / max(1, total):.1f}%)")
    print(f"[dynamic_trace] unique src functions executed: {len(unique_src_funcs)}")
    print(f"[dynamic_trace] avg src functions per linked test: {avg:.1f}")
    print(f"[dynamic_trace] JSON: {json_path}")
    print("[dynamic_trace] ============================================")
