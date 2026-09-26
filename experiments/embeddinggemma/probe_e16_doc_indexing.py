"""E16 probe: индексирует ли прод-индексатор .md (RU-документацию) вообще?
Если да — документный корпус из docs/ru (*.md) + RU-запросы по содержимому.
Если нет — .md вне прод-корпуса, и E15-оценка на коде остаётся прод-релевантной (но вопрос RU-доков владельцу честно закрыть в портфолио)."""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
R = Path(r"D:\Project\MSCodeBase")

# 1) что реально в PARSE_EXTENSIONS (src/core/extensions.py)
ext_t = (R / "src" / "core" / "extensions.py").read_text(encoding="utf-8")
m = re.search(r"PARSE_EXTENSIONS\s*=\s*\{[^}]*\}", ext_t)
print("PARSE_EXTENSIONS:", m.group(0)[:300] if m else "NOT FOUND")

# 2) как parser/extension-boundary трактует .md — ищем в parser.py и коде индексатора
for fname in ["src/core/indexing/parser.py", "src/core/extensions.py",
              "src/core/indexing/db_writer.py"]:
    p = R / fname
    if not p.exists():
        continue
    t = p.read_text(encoding="utf-8")
    hits = [l for l in t.splitlines() if ".md" in l]
    if hits:
        print(f"\n— {fname} (строки с .md) —")
        for h in hits[:8]:
            print("   ", h.strip()[:120])

# 3) есть ли вообще доки на русском в docs/ru
docs_ru = sorted((R / "docs" / "ru").glob("*.md")) if (R / "docs" / "ru").exists() else []
print(f"\ndocs/ru/*.md: {len(docs_ru)}")

# 4) ключ: поддерживает ли прод-индексатор markdown/rationale
idx_t = ""
for cand in ["src/core/indexing/project_indexer_registry.py", "src/core/indexing/parser.py"]:
    p = R / cand
    if p.exists():
        idx_t += p.read_text(encoding="utf-8")
print("\n'pandoc/markdown/.md' в индексаторе:", sum(1 for x in idx_t.splitlines() if ".md" in x or "markdown" in x.lower()))
