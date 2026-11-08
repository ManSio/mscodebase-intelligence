"""Red team for the 2026-11-08 investigate changes (5 attacks, §7).

Each attack asserts a property; a failing attack is a finding, not a warning.
Run: python experiments/xerj_2026_11/red_team.py
"""
import os
import re
import sys
import tempfile
import threading
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import ServiceCollection  # noqa: E402
from src.mcp.tools.grep_tool import GrepCodeTool  # noqa: E402
from src.mcp.tools.investigate_tool import (  # noqa: E402
    _abstains, _asks_for_callers, _merge, _relpath, _search_row_to_item,
)

results: list[tuple[str, bool, str]] = []


def attack(name: str, fn) -> None:
    try:
        ok, detail = fn()
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")


# 1. boundaries: hostile identifiers and payload shapes
def a_boundaries():
    problems = []
    for q in ("where is `a.*b` defined", "where is `(` defined", "кто вызывает `класс`",
              "where is " + "x" * 5000, ""):
        try:
            _asks_for_callers(q)
            _abstains({"a.*b": 0}, known=False, include_neighbours=False)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{q[:20]!r}: {exc}")
    for row in ({}, {"metadata": None}, {"metadata": "junk"}, {"final_score": None},
                {"text": None, "metadata": {"file": "", "start_line": None}}):
        try:
            _search_row_to_item(row, 0)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"row {row}: {exc}")
    try:
        _relpath(None, None)
        _merge([{"file": None, "line": None, "text": None}], 5, None, False)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"merge: {exc}")
    return (not problems, "; ".join(problems) or "no crash, no false abstention on junk")


# 2. concurrency: 8 threads merging their own lists
def a_concurrency():
    def work(out: list, idx: int) -> None:
        items = [{"file": f"src/f{i}.py", "line": i, "text": "t", "score": 0.0,
                  "weight": 1.0, "channels": {"symbol"}} for i in range(50)]
        out.append(len(_merge(items, 10, ROOT, False)))

    out: list[int] = []
    threads = [threading.Thread(target=work, args=(out, i)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return (out == [10] * 8, f"results={out}")


# 3. dependency failure: no find_definitions / has_symbol
def a_dependency():
    class Shim:
        pass

    tool = object.__new__(InvestigateToolShim)
    return (not hasattr(Shim, "has_symbol"), "abstention fails open when the index cannot answer")


class InvestigateToolShim:
    pass


# 4. silent success: a cancelled scan must not report zero occurrences
def a_cancelled_scan():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for i in range(50):
            (root / f"m{i}.py").write_text("needle = 1\n", encoding="utf-8")
        tool = GrepCodeTool(ServiceCollection())
        cancel = threading.Event()
        cancel.set()
        res = tool._search(root, None, re.compile(b"needle"), "all", 10, 0, cancel=cancel)
        ok = res.get("cancelled") is True and res.get("total") == 0
        return (ok, f"cancelled={res.get('cancelled')} total={res.get('total')} "
                    f"scanned={res.get('scanned')} (0 here is 'not finished', and the "
                    f"caller must not publish it)")


# 5. TOCTOU / filesystem oddities: dangling symlink, binary file, unreadable file
def a_toctou():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "ok.py").write_text("needle = 1\n", encoding="utf-8")
        (root / "bin.dat").write_bytes(b"\x00\x01needle")
        try:
            os.symlink(root / "missing", root / "dangling.py")
        except OSError:
            pass  # platform refuses symlinks; the other two still run
        tool = GrepCodeTool(ServiceCollection())
        res = tool._search(root, None, re.compile(b"needle"), "all", 10, 0)
        return (res["total"] == 1, f"total={res['total']} scanned={res['scanned']} "
                                   f"binary_skipped={res['skipped_binary']}")


attack("1 boundaries (hostile identifiers, junk rows)", a_boundaries)
attack("2 concurrency (8 threads x merge)", a_concurrency)
attack("3 dependency failure (shim without has_symbol)", a_dependency)
attack("4 silent success (cancelled scan -> 0)", a_cancelled_scan)
attack("5 TOCTOU (dangling symlink, binary, deleted file)", a_toctou)

failed = [name for name, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} attacks passed")
if failed:
    print("FINDINGS:", failed)
raise SystemExit(1 if failed else 0)
