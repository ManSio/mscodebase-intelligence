#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EXP-29 — разметка панели E28 на symbol/NL ДО прогона (freeze-before-look).

Правило детерминированное, не подгоняется глазами и не смотрит на результаты:
  symbolic := в запросе есть snake_case(_x), CamelCase(xX), путь (:: / . / слэш)
              либо одиночный токен без пробелов длиной >= 2
  иначе NL
Метки пишутся В ЗАМОРОЖЕННЫЙ файл — это часть входа, а не постфактум-разметка.
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "experiments/e28_denseoff/frozen/queries.jsonl"
DST = ROOT / "experiments/e29_symbol_ab/frozen/queries_labeled.jsonl"

SNAKE = re.compile(r"[A-Za-z_][A-Za-z0-9]*_[A-Za-z0-9_]+")
CAMEL = re.compile(r"\b[A-Z][a-z]+[A-Z][A-Za-z0-9]*\b")
PATHY = re.compile(r"::|[\w]/|\.\w+\(")


def label(q: str) -> str:
    if SNAKE.search(q) or CAMEL.search(q) or PATHY.search(q):
        return "symbolic"
    toks = q.split()
    if len(toks) == 1 and len(toks[0].strip(".,?")) >= 2:
        return "symbolic"
    return "NL"


rows = [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines() if l.strip()]
out = []
for r in rows:
    r = dict(r)
    r["subset"] = label(r["query"])
    out.append(r)

DST.write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in out) + "\n",
               encoding="utf-8", newline="\n")
sha = hashlib.sha256(DST.read_bytes()).hexdigest()
(DST.parent / "MANIFEST.sha256").write_text(f"{sha}  queries_labeled.jsonl\n", encoding="utf-8", newline="\n")

from collections import Counter  # noqa: E402
c = Counter(r["subset"] for r in out)
print("label rule: snake_case | CamelCase | pathy | single-token")
print("counts:", dict(c), "total:", len(out))
print("sha256", sha)
if c["symbolic"] < 8:
    print("WARNING: symbolic subset < 8 — вывод будет 'N мал', а не 'проверено'", file=__import__("sys").stderr)