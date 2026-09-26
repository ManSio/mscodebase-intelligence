#!/usr/bin/env python3
"""Frozen-list novelty gate (operational G6).

A "fresh" frozen list is admitted only if it shares no item and no item-level
content overlap with any previously used list (archived under experiments/**/
frozen/). This turns the abstract "non-overlapping held-out set" rule into an
executable check.

Usage:
    python scripts/frozen_overlap_check.py <new_list.md> \
        [--frozen-dir experiments/4A_unit_of_return/frozen]

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
ITEM = re.compile(r"^\d+[.)]\s")  # numbered item lines only
MIN_SHARED = 3  # >=3 shared CONTENT tokens on one item => overlap
STOP = {
    "the", "and", "but", "not", "for", "are", "was", "were", "when", "with",
    "that", "this", "from", "does", "did", "has", "have", "its", "you", "can",
    "get", "got", "all", "one", "new", "old", "out", "any", "how", "why",
    "what", "who", "who", "them", "they", "then", "than", "into", "over",
    "does", "only", "also", "more", "most", "its", "his", "her", "their",
}


def _items(path: Path) -> list[str]:
    """First contiguous block of numbered item lines only.

    Stops at the first non-item, non-blank line after the block starts, so
    trailing numbered lists (e.g. a "next steps" section) are not counted.
    """
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


def _tokens(line: str) -> set[str]:
    return {t for t in TOKEN.findall(line) if t not in STOP}


def check(new_list: Path, frozen_dir: Path) -> int:
    if not new_list.exists():
        print(f"ERROR: new list not found: {new_list}")
        return 2
    used_files = [
        p for p in frozen_dir.rglob("*.md")
        if p.resolve() != new_list.resolve() and p.name != "README.md"
    ]
    new_items = _items(new_list)
    if not new_items:
        print("ERROR: new list has no items")
        return 2

    violations: list[str] = []
    for uf in used_files:
        for ui in _items(uf):
            ut = _tokens(ui)
            for ni in new_items:
                if ni == ui:
                    violations.append(f"DUPLICATE item vs {uf.name}: {ni[:80]}")
                    continue
                shared = ut & _tokens(ni)
                if len(shared) >= MIN_SHARED:
                    violations.append(
                        f"OVERLAP({len(shared)}) vs {uf.name}: "
                        f"{ni[:60]} ~ {ui[:60]} :: {sorted(shared)[:6]}"
                    )
    print(f"new list: {new_list.name}  items={len(new_items)}  "
          f"compared_against={len(used_files)} used list(s)")
    if violations:
        print("OVERLAP: FAIL")
        for v in violations[:40]:
            print("  -", v)
        return 1
    print("OVERLAP: PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("new_list")
    ap.add_argument("--frozen-dir",
                    default="experiments/4A_unit_of_return/frozen")
    args = ap.parse_args()
    fd = Path(args.frozen_dir)
    if not fd.is_absolute():
        fd = REPO / fd
    return check(Path(args.new_list), fd)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - top-level guard must report and exit non-zero
        import traceback
        traceback.print_exc()
        raise SystemExit(2)
