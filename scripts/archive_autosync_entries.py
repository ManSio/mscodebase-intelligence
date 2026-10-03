"""Archive auto-synced diary copies out of the live KNOWN_ISSUES board.

Problem (measured 2026-10-01): KNOWN_ISQUES.md held 448 lines against a 300-line
limit (rule R1), so nothing could be committed. 224 of those 448 lines — 29 blocks
— were not board entries at all. They were verbatim copies injected from
AGENT_DIARY.md by AutoDocUpdater during a full reindex, each carrying:

    **Источник:** AGENT_DIARY.md
    **Статус:** автоматически синхронизировано

An issue board that mirrors the diary holds every issue twice and cannot be
trimmed without deleting information. The diary is the source; the board keeps
hand-authored entries only.

This script moves those blocks to docs/archive/ and leaves everything else in
place. It never deletes: the archive is append-only, per §4.8 R4.

Safe to re-run: it selects by the marker, so a second run finds nothing to move
and exits 0 having changed nothing.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "KNOWN_ISSUES.md"
ARCHIVE_DIR = ROOT / "docs" / "archive"

MARKERS = ("Источник: AGENT_DIARY.md", "автоматически синхронизировано")


def main() -> int:
    if not LIVE.exists():
        print(f"no live board at {LIVE}")
        return 2
    text = LIVE.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    heads = [i for i, l in enumerate(lines) if l.startswith("## ")]

    if not heads:
        print("no sections found — refusing to guess at the structure")
        return 2

    header = lines[:heads[0]]
    blocks: list[tuple[int, int, bool]] = []
    for n, start in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        body = "\n".join(lines[start:end])
        is_auto = any(m in body for m in MARKERS)
        blocks.append((start, end, is_auto))

    moving = [(s, e) for s, e, a in blocks if a]
    if not moving:
        print(f"nothing to archive — {len(heads)} sections, none carry a diary marker")
        return 0

    month = date.today().strftime("%Y_%m")
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    target = ARCHIVE_DIR / f"KNOWN_ISSUES_{month}_AUTO_SYNC.md"

    preamble: list[str] = []
    if target.exists():
        preamble = ["<!-- appended by scripts/archive_autosync_entries.py -->", ""]
        existing = target.read_text(encoding="utf-8", errors="replace").splitlines()
        kept = existing
    else:
        kept = [
            f"# KNOWN_ISSUES {month} — auto-synced diary copies",
            "",
            "Moved verbatim out of `KNOWN_ISSUES.md` by "
            "`scripts/archive_autosync_entries.py`.",
            "",
            "These blocks were injected from `AGENT_DIARY.md` by AutoDocUpdater "
            "during a full",
            "reindex. They are not board entries; the diary remains the source. "
            "Moved, not",
            "deleted — the board had reached 448 lines against a 300-line limit (R1), "
            "and half",
            "of it was a second copy of the diary.",
            "",
            "---",
            "",
        ]

    kept = kept + preamble
    moved_lines = 0
    for start, end in moving:
        kept.append("")
        kept.extend(lines[start:end])
        moved_lines += end - start

    remaining: list[str] = list(header)
    for start, end, is_auto in blocks:
        if not is_auto:
            remaining.extend(lines[start:end])

    target.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    LIVE.write_text("\n".join(remaining).rstrip() + "\n", encoding="utf-8")

    print(f"archived {len(moving)} diary-copy blocks ({moved_lines} lines) -> "
          f"{target.relative_to(ROOT)}")
    print(f"live board: {len(lines)} -> {len(remaining)} lines "
          f"(limit 300: {'OK' if len(remaining) <= 300 else 'STILL OVER'})")
    print(f"kept {len(blocks) - len(moving)} hand-authored sections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())