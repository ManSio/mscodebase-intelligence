#!/usr/bin/env python3
"""fp_heldout.py — FP-аудит класса C2 на held-out корпусе (EXPERIMENTS_LOG.md).

Отвечает на возражение: «89% — свойство нашего корпуса, на другой популяции будет иначе».
Печатает все совпавшие строки, чтобы разметить их руками.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "EXPERIMENTS_LOG.md"
C2 = r"тихий ноль|тихого нуля|silent zero|0%|rc=0|0 результатов|пуст\w+ выборк"


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if not text.strip():
        print("FATAL: пустой вход", file=sys.stderr)
        return 2
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    if not starts:
        print("FATAL: 0 записей", file=sys.stderr)
        return 2
    pat = re.compile(C2, re.I)
    n = 0
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(lines)
        ms = [ln for ln in lines[s:e] if pat.search(ln)]
        if ms:
            n += 1
            print(f"{n:2d} entry L{s + 1}: {lines[s][:70]}")
            for m in ms[:2]:
                print(f"      | {m.strip()[:120]}")
    print("C2_entries", n, "из", len(starts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
