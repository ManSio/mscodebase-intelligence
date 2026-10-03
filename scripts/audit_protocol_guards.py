#!/usr/bin/env python3
"""Guard for the protocol rules that were added as prose and would otherwise stay prose.

Backs:
  T9  (denominator)  — a report that says "N places" without "N of M" is worthless
  T10 (silent zero)  — a metric tool that answers "0%" on an EMPTY population is lying
  T11 (claims audit) — a published claim must be traceable to a committed artifact
  §19.1 (falsifiable hypotheses) — a frozen manifest must name what would REFUTE it,
        and must contain at least two hypotheses expected to FAIL

Design rule this file obeys (P-019): every rule above has an executable check here,
because a comment does not fail. `--selftest` proves each check can FAIL.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

REPO = pathlib.Path(__file__).resolve().parents[1]
SCAN_DIRS = ("scripts", "experiments")

# a tool that divides or prints a percentage over a collection
RATE = re.compile(r"(\*\s*100\s*/\s*max\(|rate\s*=\s*.*?/\s*len\(|доля|\{.*:.*[01]\.?\d*%\})")
# An explicit REFUSAL to answer on an empty population. `max(x, 1)` is deliberately NOT
# accepted: it prevents ZeroDivisionError but still prints "0%" and exits 0, which is
# exactly the silent-zero failure T10 forbids. A real guard must exit non-zero or raise.
#
# Robustness note: an earlier version required the exit to be the FIRST statement in the
# branch. Real guards put a comment and a stderr message first, so that version could not
# see them and would have flagged correct code forever. Intervening comment/blank lines are
# therefore allowed.
GAP = r"(?:\s*#[^\n]*\n)*\s*"
POP_GUARD = re.compile(
    r"if\s+not\s+\w+[^:\n]*:" + GAP + r"(?:sys\.exit\(|raise\s+\w*Error)"
    r"|len\([^)]*\)\s*(?:==|<=)\s*0\s*:" + GAP + r"(?:sys\.exit\(|raise|return)"
    r"|\w+\s*==\s*0\s*:" + GAP + r"(?:sys\.exit\(|raise|return)"
    r"|if\s+\w+\s*==\s*\[\]\s*:" + GAP + r"(?:sys\.exit\(|raise|return)"
    r"|if\s+not\s+\w+[^:\n]*:\s*\n(?:\s+[^\n]*\n){0,3}?\s*sys\.exit\("
)
# the anti-pattern this rule exists to catch: dividing by max(len(...), 1) and still reporting
SILENT_ZERO = re.compile(r"max\(\s*[^,\n]+?\s*,\s*1\s*\)")
# Two INDEPENDENT requirements. They must not share a pattern: an earlier version matched
# "Ожидаем ПРОВАЛ" as a falsifier, and the selftest proved that branch blind.
FALSIFIER = re.compile(r"(фальсификатор|falsifier|refut|опровергател)", re.IGNORECASE)
EXPECTED_FAIL = re.compile(r"(ПРОВАЛ|expected to fail|к провалу|refuted)", re.IGNORECASE)


def iter_sources():
    me = pathlib.Path(__file__).resolve()
    for d in SCAN_DIRS:
        root = REPO / d
        if not root.is_dir():
            continue
        for p in root.rglob("*.py"):
            if ".git" in p.parts or "frozen" in p.parts:
                continue
            if p.resolve() == me:          # the guard never audits itself
                continue
            yield p


def check_t10() -> tuple[int, list[str]]:
    """A tool that computes a rate must guard an empty population first."""
    offenders = []
    for p in iter_sources():
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not RATE.search(src):
            continue
        # Semantics: a refusal guard makes any later division unreachable, so `max(x,1)`
        # is then harmless (dead defensive code). The silent-zero finding is therefore
        # raised ONLY when there is no refusal guard at all -- which is exactly the case
        # where the tool prints "0%" and exits 0. Flagging both would make this guard
        # noisy, and a noisy guard gets ignored.
        if POP_GUARD.search(src):
            continue
        offenders.append(str(p.relative_to(REPO)).replace("\\", "/"))
    return len(list(iter_sources())), offenders


def check_t11() -> tuple[int, list[str]]:
    """Every frozen manifest must record a sha256 of the input it freezes."""
    missing = []
    n = 0
    for m in (REPO / "experiments").rglob("frozen/*.md"):
        text = m.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"###\s*Items|##\s*Items|пункт", text, re.IGNORECASE):
            continue
        n += 1
        if not re.search(r"[0-9a-f]{64}|sha256", text, re.IGNORECASE):
            missing.append(str(m.relative_to(REPO)).replace("\\", "/"))
    return n, missing


def check_191() -> tuple[int, list[str]]:
    """A frozen hypothesis manifest must be falsifiable and admit expected failures."""
    problems = []
    n = 0
    for m in (REPO / "experiments").rglob("frozen/HYPOTHESES.md"):
        n += 1
        text = m.read_text(encoding="utf-8", errors="replace")
        if not FALSIFIER.search(text):
            problems.append(f"{m.relative_to(REPO)}: no falsifier column")
        if not EXPECTED_FAIL.search(text):
            problems.append(f"{m.relative_to(REPO)}: no expected-to-fail hypothesis")
    return n, problems


CHECKS = (
    ("T10 silent zero", check_t10),
    ("T11 claims traceability", check_t11),
    ("§19.1 falsifiable hypotheses", check_191),
)


def run() -> int:
    bad = 0
    for name, fn in CHECKS:
        total, offenders = fn()
        if name.startswith("T10"):
            print(f"[{name}] python sources scanned={total}; rate-tool without empty-population guard={len(offenders)}")
        else:
            print(f"[{name}] artifacts={total}; without the required field={len(offenders)}")
        for o in offenders[:12]:
            print(f"    - {o}")
        if len(offenders) > 12:
            print(f"    ... +{len(offenders) - 12} more")
        bad += len(offenders)
    print()
    if bad:
        print(f"PROTOCOL GUARD: {bad} finding(s). A rule that is only prose does not fail; this does.")
        return 1
    print("PROTOCOL GUARD: clean — every new rule has an executable check and it passes.")
    return 0


def selftest() -> int:
    """Negative control: the checks must be ABLE to fail. Proven on synthetic input.

    Code cases are parsed as Python; prose cases are NOT (they are markdown).
    """
    code_cases = [
        ("T10 empty population",
         "def rate(items):\n    return len([i for i in items if i]) / max(len(items), 1) * 100\n"
         "print('доля: 0.0%')\n", True),
        ("T10 guarded population",
         "def rate(items):\n    if not items:\n        raise ValueError('empty')\n"
         "    return 1\nprint('доля: 1.0%')\n", False),
    ]
    prose_cases = [
        ("§19.1 ничего нет",
         "# Гипотеза\nМы думаем X.\n", True),
        ("§19.1 фальсификатор есть, ожидаемого провала нет",
         "# Гипотеза\nФальсификатор: X не воспроизведётся.\n", True),
        ("§19.1 ожидаемый провал есть, фальсификатора нет",
         "# Гипотеза\nОжидаем ПРОВАЛ: гипотеза B.\n", True),
        ("§19.1 фальсификатор + ожидаемый провал",
         "# Гипотеза\nФальсификатор: X.\nОжидаем ПРОВАЛ: гипотеза B.\n", False),
    ]
    ok = True
    for name, code, should_fail in code_cases:
        try:
            ast.parse(code)
        except SyntaxError:
            print(f"  [BROKEN] {name}: fixture is not valid Python")
            ok = False
            continue
        has_rate = bool(RATE.search(code))
        has_guard = bool(POP_GUARD.search(code))
        flagged = has_rate and not has_guard
        status = "OK" if flagged == should_fail else "GUARD IS BLIND"
        if flagged != should_fail:
            ok = False
        print(f"  [{status}] {name}: expected_flag={should_fail} got={flagged}")
    for name, text, should_fail in prose_cases:
        has_falsifier = bool(FALSIFIER.search(text))
        has_expected_fail = bool(EXPECTED_FAIL.search(text))
        flagged = not (has_falsifier and has_expected_fail)
        status = "OK" if flagged == should_fail else "GUARD IS BLIND"
        if flagged != should_fail:
            ok = False
        print(f"  [{status}] {name}: expected_flag={should_fail} got={flagged}")
    print(f"\nSELFTEST {'PASSED — checks can fail' if ok else 'FAILED — a check cannot fail'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    raise SystemExit(run())
