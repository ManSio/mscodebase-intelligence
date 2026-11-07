#!/usr/bin/env python3
"""audit_v2.py — НЕЗАВИСИМАЯ перепроверка measure.py.

Принцип §19.2: артефакт под аудитом (REPORT.md / measure.py) не является входом.
Здесь другой парсер (split по '\\n## ', не regex по строкам), другой счётчик,
и печать единицы измерения явно (§19.28): записи, а не строки.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
DIARY = ROOT / "AGENT_DIARY.md"

CLASSES = {
    "C1": r"переписал|переписала|перезаписал\w*\s+(файл|реестр|задач|состоян)|whole-file|CRLF|затёр|удалил раздел|пропал раздел",
    "C2": r"тихий ноль|тихого нуля|silent zero|0%|rc=0|0 результатов|пуст\w+ выборк",
}


def parse_simple(path: Path) -> list[tuple[int, str, str]]:
    """Возвращает [(start_line, header, body)] через split, без regex-заголовков."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    out = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(lines)
        out.append((s + 1, lines[s], "\n".join(lines[s:e])))
    return out


def main() -> int:
    print("sha256", hashlib.sha256(DIARY.read_bytes()).hexdigest())
    ents = parse_simple(DIARY)
    print("entries", len(ents))
    dated = [e for e in ents if re.match(r"^## \[?\d{4}-\d{2}-\d{2}", e[1])]
    print("dated", len(dated))
    undated = [e for e in ents if e not in dated]
    print("undated_headers", len(undated))
    for line, hdr, _ in undated:
        print(f"  undated L{line}: {hdr[:80]}")
    # дубли: одинаковый (дата, заголовок)
    keys = [re.sub(r"\s+", " ", e[1]).strip() for e in ents]
    dupes = {k for k in keys if keys.count(k) > 1}
    print("duplicate_headers", len(dupes))
    for k in dupes:
        print("  DUP:", k[:90])

    print("\n--- per-class, ЕДИНИЦА = запись ---")
    for cid, rx in CLASSES.items():
        pat = re.compile(rx, re.I)
        hit_entries = [e for e in ents if pat.search(e[2])]
        hit_lines = sum(len(pat.findall(e[2])) for e in ents)
        print(f"{cid}: entries {len(hit_entries)} из {len(ents)}, matched_lines {hit_lines}")

    print("\n--- C2 per-entry ---")
    pat = re.compile(CLASSES["C2"], re.I)
    n = 0
    for line, hdr, body in ents:
        ms = [m for m in body.splitlines() if pat.search(m)]
        if ms:
            n += 1
            print(f"{n:2d} entry L{line}: {hdr[:60]}")
            for m in ms[:3]:
                print(f"      | {m.strip()[:120]}")
    print("C2_entries", n)

    print("\n--- попадают ли 2 цитируемых инцидента в C1 ---")
    pat1 = re.compile(CLASSES["C1"], re.I)
    for target in (786, 1287):
        owner = None
        for line, hdr, body in ents:
            if line <= target < line + len(body.splitlines()):
                owner = (line, hdr, body)
                break
        if owner:
            line, hdr, body = owner
            print(f"L{target} -> entry L{line} [{hdr[:50]}] C1_match={bool(pat1.search(body))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
