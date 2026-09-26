"""E16 probe: что реально покрывает корпус E15 и есть ли в репо RU-документация для честного документного замера."""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

R = Path(r"D:\Project\MSCodeBase")
t = (R / "experiments" / "embeddinggemma" / "bench.py").read_text(encoding="utf-8")


def block(name: str) -> str:
    i = t.index(name + " = [")
    j = t.index("]", i)
    return t[i:j]


cyr = re.compile(r"[А-Яа-яЁё]")
golds = re.findall(r'\"(src/[^\"]+\.py)\"', block("GOLD"))
dist = re.findall(r'\"(src/[^\"]+\.py)\"', block("DISTRACTORS"))

print(f"GOLD py: {len(golds)}, DISTRACTORS py: {len(dist)}")

# насколько целевые py реально содержат RU-комментарии/стринги
print("\n— RU в золотых py —")
for p in sorted(set(golds)):
    fp = R / p
    if not fp.exists():
        continue
    s = fp.read_text(encoding="utf-8", errors="replace")
    n = len(cyr.findall(s))
    flag = "RU!" if n > 300 else ("ru?" if n else "EN-only")
    print(f"  {p:58s} cyr={n:6d} {flag}")

# документный корпус, доступный в репо для E16
print("\n— RU-документация в репо (.md) —")
cands = []
for p in sorted((R / "docs").rglob("*.md")):
    s = p.read_text(encoding="utf-8", errors="replace")
    n = len(cyr.findall(s))
    if n > 1500:
        rel = p.relative_to(R)
        cands.append(rel)
        print(f"  {str(rel):70s} cyr={n:6d}")
print(f"  кандидатов-документов: {len(cands)}")
