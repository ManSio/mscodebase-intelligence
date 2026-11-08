import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\Project\MSCodeBase")
from src.core.search.scoring import auto_detect_intent

p = Path(r"D:\Project\MSCodeBase\experiments\e30_prod_rerank\frozen\QUERIES.jsonl")
rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
for q in rows:
    intent = auto_detect_intent(q["query"])
    if q["gold_file"].startswith("docs/") or intent == "docs":
        print(q["id"], intent, q["gold_file"], "|", q["query"][:80])
