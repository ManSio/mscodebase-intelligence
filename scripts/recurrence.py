#!/usr/bin/env python3
"""recurrence.py — счётчик ре-оффенса из machine-readable тегов BREACH.

Зачем: «повторяется» без числа — это STORY (§19.4: числитель без знаменателя).
Тег в существующем реестре (второй дневник не создаём — P-006):

    BREACH: <CLASS-ID> | rule: §X | guard_at_time: yes|no | detected_by: gate|eye

Что считает:
  * n — сколько раз класс встречался;
  * after_guard — сколько из них случились, когда ПРЕВЕНТИВНЫЙ guard класса уже стоял
    (guard_at_time: yes). Это и есть ре-оффенс; n без него — просто история;
  * first/last — границы;
  * detected_by — кто заметил (gate/eye): если всё eye, класс не закрыт гейтом.

Коды возврата: 0 — данные есть; 1 — теги есть, но у класса after_guard > 0 (не закрыт);
2 — тегов нет (популяция пуста, метрика не определена, §19.6).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DIARY = Path(__file__).resolve().parents[1] / "AGENT_DIARY.md"

TAG = re.compile(
    r"BREACH:\s*(?P<cls>[A-Za-z0-9\-_.]+)\s*\|\s*"
    r"(?:date:\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\|\s*)?"
    r"rule:\s*(?P<rule>[^|]+?)\s*\|\s*"
    r"guard_at_time:\s*(?P<guard>yes|no)\s*\|\s*"
    r"detected_by:\s*(?P<who>gate|eye)",
    re.IGNORECASE,
)
HEADER = re.compile(r"^##\s*(?:CONTRADICTION\s+)?\[(?P<date>\d{4}-\d{2}-\d{2})")


def collect(text: str) -> list[dict]:
    out: list[dict] = []
    current_date = ""
    for line in text.splitlines():
        m = HEADER.match(line)
        if m:
            current_date = m.group("date")
            continue
        t = TAG.search(line)
        if t:
            out.append(
                {
                    "date": t.group("date") or current_date or "????-??-??",
                    "cls": t.group("cls").upper(),
                    "rule": t.group("rule").strip(),
                    "guard": t.group("guard").lower() == "yes",
                    "who": t.group("who").lower(),
                }
            )
    return out


def report(rows: list[dict]) -> int:
    if not rows:
        print("FATAL: 0 тегов BREACH — ре-оффенс не определён (§19.6)", file=sys.stderr)
        return 2

    by_class: dict[str, list[dict]] = {}
    for r in rows:
        by_class.setdefault(r["cls"], []).append(r)

    print(f"breach_tags={len(rows)} classes={len(by_class)}\n")
    print(f"{'class':<12}{'n':>3}{'after_guard':>13}{'first':>12}{'last':>12}  who")
    open_classes = 0
    for cls in sorted(by_class):
        rs = sorted(by_class[cls], key=lambda x: x["date"])
        after = sum(1 for r in rs if r["guard"])
        who = ",".join(sorted({r["who"] for r in rs}))
        if after:
            open_classes += 1
        print(f"{cls:<12}{len(rs):>3}{after:>13}{rs[0]['date']:>12}{rs[-1]['date']:>12}  {who}")

    print()
    for cls in sorted(by_class):
        for r in by_class[cls]:
            print(f"  {r['date']}  {cls}  {r['rule']}")
    return 1 if open_classes else 0


def selftest() -> int:
    ok = True
    good = """## [2026-01-01] — a
BREACH: MSC-P-01 | rule: §12 | guard_at_time: no | detected_by: eye
## [2026-01-02] — b
BREACH: MSC-P-01 | rule: §12 | guard_at_time: yes | detected_by: gate
"""
    rows = collect(good)
    print(f"selftest parse: {'OK' if len(rows) == 2 else 'FAIL'} — rows={len(rows)}")
    ok &= len(rows) == 2
    print(f"selftest dates: {'OK' if rows and rows[0]['date'] == '2026-01-01' else 'FAIL'}")
    ok &= bool(rows) and rows[0]["date"] == "2026-01-01"
    print(f"selftest guard flag: {'OK' if rows[1]['guard'] is True else 'FAIL'}")
    ok &= len(rows) > 1 and rows[1]["guard"] is True

    rc = report(rows)
    print(f"selftest report(open class) rc={rc} (ожидается 1)")
    ok &= rc == 1

    rc = report(collect("## [2026-01-01] — a\nBREACH: X-1 | rule: §1 | guard_at_time: no | detected_by: eye\n"))
    print(f"selftest report(closed) rc={rc} (ожидается 0)")
    ok &= rc == 0

    rc = report([])
    print(f"selftest report(empty) rc={rc} (ожидается 2)")
    ok &= rc == 2
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    if not DIARY.exists():
        print(f"FATAL: {DIARY} не найден", file=sys.stderr)
        return 2
    return report(collect(DIARY.read_text(encoding="utf-8")))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
