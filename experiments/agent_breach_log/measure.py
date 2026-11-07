#!/usr/bin/env python3
"""agent_breach_log / measure.py — измеритель повторяемости классов нарушений.

Зачем: статья dev.to (2026-11-07) утверждает «три паттерна, повторы, ре-оффенс»,
но не публикует знаменатель. Этот скрипт считает классы нарушений по нашим
реестрам, с контролем (selftest) и held-out режимом.

Правила:
  §19.6 — на пустой входной выборке скрипт ПАДАЕТ (rc=2), а не печатает 0.
  §19.3 — selftest: positive control (должен найти) + negative (должен молчать).
  §19.4 — печатает N из M (доля), а не только N.

Классы заморожены в frozen/CLASSES.md (сформированы на AGENT_DIARY.md,
проверяются на EXPERIMENTS_LOG.md — held-out).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
DIARY = ROOT / "AGENT_DIARY.md"
EXP = ROOT / "EXPERIMENTS_LOG.md"

# Классы: (id, human name, regex). Регистронезависимо.
CLASSES: list[tuple[str, str, str]] = [
    ("C1", "destructive_rewrite", r"переписал|переписала|перезаписал\w*\s+(файл|реестр|задач|состоян)|whole-file|CRLF|затёр|удалил раздел|пропал раздел"),
    ("C2", "silent_zero", r"тихий ноль|тихого нуля|silent zero|0%|rc=0|0 результатов|пуст\w+ выборк"),
    ("C3", "unenforced_rule", r"не вызвал|не исполн|проигнор|advisory|правило\W+не примен|не применил|остался в тексте"),
    ("C4", "judgment_drift", r"вместо того|сверх задачи|самовольн|не то, что просил|расширил задачу|drifted"),
    ("C5", "verification_theater", r"повторн\w+ прогон|прогнал\w* ещё раз|для подтверждения|re-run|перепрогнал"),
]

HEADER = re.compile(r"^##\s+(?:\[(?P<date>\d{4}-\d{2}-\d{2})\]\s*)?(?P<title>.*)$")


def entries(path: Path) -> list[dict]:
    """Режет markdown на записи по заголовкам '## '."""
    out: list[dict] = []
    cur: dict | None = None
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = HEADER.match(line)
        if m:
            if cur:
                out.append(cur)
            cur = {"line": i, "date": m.group("date") or "", "title": m.group("title")[:70], "body": []}
        elif cur is not None:
            cur["body"].append(line)
    if cur:
        out.append(cur)
    for e in out:
        e["text"] = e["title"] + "\n" + "\n".join(e["body"])
    return out


def classify(es: list[dict]) -> dict[str, list[dict]]:
    res: dict[str, list[dict]] = {}
    for cid, _name, rx in CLASSES:
        pat = re.compile(rx, re.IGNORECASE)
        res[cid] = [e for e in es if pat.search(e["text"])]
    return res


def report(es: list[dict], label: str) -> int:
    if not es:
        print(f"FATAL: {label} дал 0 записей — метрика не интерпретируема (§19.6)", file=sys.stderr)
        return 2
    dated = [e for e in es if e["date"]]
    by_month: dict[str, int] = {}
    for e in dated:
        by_month[e["date"][:7]] = by_month.get(e["date"][:7], 0) + 1
    print(f"=== {label} ===")
    print(f"entries_total\t{len(es)}")
    print(f"entries_dated\t{len(dated)}")
    if dated:
        ds = sorted(e["date"] for e in dated)
        print(f"date_range\t{ds[0]}..{ds[-1]}")
    print("months\t" + ", ".join(f"{k}={v}" for k, v in sorted(by_month.items())))
    res = classify(es)
    print()
    for cid, name, _rx in CLASSES:
        hits = res[cid]
        print(f"{cid}\t{name}\t{len(hits)} из {len(es)}\t{100.0 * len(hits) / len(es):.1f}%")
    print()
    print("--- hits (line | date | title) ---")
    for cid, name, _rx in CLASSES:
        print(f"[{cid}] {name}")
        for e in res[cid]:
            print(f"  L{e['line']:<5} {e['date'] or '(no date)':<10} {e['title']}")
    return 0


def selftest() -> int:
    """Positive control (каждый класс находится) + negative (молчит на чистом тексте)."""
    positives = {
        "C1": "2026-01-01 переписал файл целиком, CRLF утерян",
        "C2": "2026-01-02 сканер напечатал 0% при rc=0 на пустой выборке",
        "C3": "2026-01-03 правило было advisory, агент проигнорировал и не вызвал тул",
        "C4": "2026-01-04 сверх задачи расширил задачу и сделал вместо того",
        "C5": "2026-01-05 повторный прогон для подтверждения, re-run без изменений",
    }
    ok = True
    for cid, _name, rx in CLASSES:
        hit = re.search(rx, positives[cid], re.IGNORECASE) is not None
        print(f"selftest positive {cid}: {'OK' if hit else 'FAIL'} — {positives[cid][:50]}")
        ok &= hit

    clean = ["2026-01-06 Добавлен парсер CSV.", "2026-01-07 Ускорен поиск на 12%."]
    for cid, _name, rx in CLASSES:
        hits = [s for s in clean if re.search(rx, s, re.IGNORECASE)]
        print(f"selftest negative {cid}: {'OK' if not hits else 'FAIL'} — hits={len(hits)}")
        ok &= not hits

    # §19.6: пустая выборка обязана падать, а не печатать 0
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        empty_path = Path(td) / "empty.md"
        empty_path.write_text("", encoding="utf-8")
        rc = report(entries(empty_path), "selftest-empty")
    print(f"selftest empty-input: rc={rc} (ожидается 2)")
    ok &= rc == 2
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    path = EXP if "--heldout" in argv else DIARY
    label = "HELD-OUT: EXPERIMENTS_LOG.md" if "--heldout" in argv else "EXPLORATION: AGENT_DIARY.md"
    es = entries(path)
    if not es:
        print(f"FATAL: {path} дал 0 записей (§19.6)", file=sys.stderr)
        sys.exit(2)
    return report(es, label)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
