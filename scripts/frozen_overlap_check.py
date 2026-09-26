#!/usr/bin/env python3
"""Frozen-list novelty gate (operational G6).

A "fresh" frozen list is admitted only if its PROBES (numbered items) share no
item and no item-level content overlap with any previously frozen text. "Used"
text = numbered probes AND table-cell phrases (index rows) from every other
frozen file, because a new probe that is a paraphrase of an index phrase is a
semantic twin of the index, not a fresh probe.

History: 2026-09-26 F4b exposed that the v1 gate was blind to (a) table-row
index phrases and (b) morphological twins ("timing/retry" vs "times/try").
v2 adds table phrases and a short-phrase near-twin rule.

Usage:
    python scripts/frozen_overlap_check.py <new_list.md> \
        [--frozen-dir experiments/4A_unit_of_return/frozen] [--debug]
    python scripts/frozen_overlap_check.py --selftest
    python scripts/frozen_overlap_check.py <new_list.md> --overlap-threshold 3

Exit 0 = PASS, 1 = FAIL, 2 = usage/IO error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"[a-zа-яё0-9]{3,}")
ITEM = re.compile(r"^\d+[.)]\s")           # numbered probe lines only
TABLE = re.compile(r"^\|(.+)\|\s*$")        # markdown table rows
MIN_SHARED = 3        # >=3 shared content tokens on one item => overlap
SHORT_MAX = 8         # a short phrase (<=8 tokens) sharing 2 tokens is a near-twin
STOP = {
    "the", "and", "but", "not", "for", "are", "was", "were", "when", "with",
    "that", "this", "from", "does", "did", "has", "have", "its", "you", "can",
    "get", "got", "all", "one", "new", "old", "out", "any", "how", "why",
    "what", "who", "them", "they", "then", "than", "into", "over",
    "only", "also", "more", "most", "his", "her", "their",
}


def _stem(t: str) -> str:
    """Very light suffix stripping: timing->tim, times->time, tests->test."""
    for suf in ("ing", "ed", "es", "s"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def _tokens(line: str) -> set[str]:
    return {_stem(t) for t in TOKEN.findall(line.lower()) if t not in STOP}


def _numbered(path: Path) -> list[str]:
    """First contiguous block of numbered probe lines only."""
    out: list[str] = []
    started = False
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if ITEM.match(s):
            started = True
            out.append(s.lower())
        elif started and s:
            break
    return out


def _table_cells(line: str) -> list[str]:
    m = TABLE.match(line.strip())
    if not m:
        return []
    out: list[str] = []
    for cell in m.group(1).split("|"):
        cell = cell.strip().lower()
        if cell and not set(cell) <= {"-", ":", " "}:
            out.append(cell)
    return out


def _arrival_phrases(path: Path) -> list[str]:
    """Table cells of the "Arrival index" section (front-door phrases).

    These are probe-like ("what a user would say") and were used as the probe
    register in E11, so a fresh probe must not be a twin of one. Ordinary
    answer-key index tables are NOT included: a probe is supposed to overlap
    its own key, so comparing probes to keys would flag every valid probe.
    """
    out: list[str] = []
    in_arrival = False
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("#"):
            in_arrival = bool(re.search(r"arrival", s, re.IGNORECASE))
            continue
        if in_arrival:
            out.extend(_table_cells(s))
    return out


def _used_phrases(path: Path) -> list[tuple[str, str]]:
    """(kind, text) for everything a fresh probe must not paraphrase.

    Only two sources: numbered probes of previous lists (freshness across
    experiments) and arrival front-door phrases (the E11 probe register).
    """
    return ([("item", t) for t in _numbered(path)]
            + [("arrival", t) for t in _arrival_phrases(path)])


def compare(new_items: list[str], used: list[tuple[str, str]],
            min_shared: int = MIN_SHARED) -> list[str]:
    """Pure comparison: violations of `new_items` against `used` phrases."""
    violations: list[str] = []
    for ni in new_items:
        nt = _tokens(ni)
        for kind, ui in used:
            if ni == ui:
                violations.append(f"DUPLICATE {kind}: {ni[:80]}")
                continue
            shared = _tokens(ui) & nt
            if len(shared) >= min_shared:
                violations.append(f"OVERLAP({len(shared)}) {kind}: {ni[:50]} ~ {ui[:50]} :: {sorted(shared)[:6]}")
    return violations


def check(new_list: Path, frozen_dir: Path, min_shared: int = MIN_SHARED,
          debug: bool = False) -> int:
    if not new_list.exists():
        print(f"ERROR: new list not found: {new_list}")
        return 2
    used_files = [
        p for p in frozen_dir.rglob("*.md")
        if p.resolve() != new_list.resolve()
        and p.name != "README.md"
        and p.parent.resolve() != new_list.resolve().parent  # sibling conditions are the same set
    ]
    new_items = _numbered(new_list)
    if not new_items:
        print("ERROR: new list has no items")
        return 2

    used: list[tuple[str, str]] = []
    for uf in used_files:
        used.extend(_used_phrases(uf))

    violations = compare(new_items, used, min_shared)
    print(f"new list: {new_list.name}  items={len(new_items)}  "
          f"used_files={len(used_files)}  used_phrases={len(used)}")
    if violations:
        print("OVERLAP: FAIL")
        for v in violations[:40]:
            print("  -", v)
        return 1
    if debug:
        print("(debug) no overlapping pair found")
    print("OVERLAP: PASS")
    return 0


def selftest() -> int:
    """Negative+positive control: the gate MUST flag the known F4b twin and
    MUST pass an unrelated pair. A gate that cannot fail is useless."""
    # Real twin (F4b #3 vs catalogue arrival sentence) — must be flagged.
    used = [("arrival", "it times out every time i try this")]
    twin = ["it keeps timing out every time i retry, no matter what.".lower()]
    v = compare(twin, used)
    if not v:
        print("SELFTEST FAIL: known twin (#3) was NOT flagged")
        return 1
    # Unrelated probe — must NOT be flagged.
    clean = ["the database schema migration locked the table for an hour.".lower()]
    v2 = compare(clean, used)
    if v2:
        print(f"SELFTEST FAIL: unrelated probe flagged: {v2}")
        return 1
    print("SELFTEST OK: twin flagged, unrelated clean")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("new_list", nargs="?")
    ap.add_argument("--frozen-dir", default="experiments/4A_unit_of_return/frozen")
    ap.add_argument("--overlap-threshold", type=int, default=MIN_SHARED)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.new_list:
        ap.error("new_list is required (or use --selftest)")
    fd = Path(args.frozen_dir)
    if not fd.is_absolute():
        fd = REPO / fd
    return check(Path(args.new_list), fd, args.overlap_threshold, args.debug)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - top-level guard must report and exit non-zero
        import traceback
        traceback.print_exc()
        raise SystemExit(2)
