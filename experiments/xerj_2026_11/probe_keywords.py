"""Feasibility: would a Cyrillic keyword channel find the gold files E1 misses?

For each missed positive task, take the Russian content words from the question
and count how often each occurs in the gold file. If all are 0, the channel
cannot help and must not be built.
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]

CASES = [
    ("P04", "Где решается, нужно ли переиндексировать файл?", "src/core/indexing/freshness.py"),
    ("P06", "Какая функция возвращает путь прогресса?", "src/core/artifact_paths.py"),
    ("P13", "Где хранится схема `file_hash` / `file_mtime_ns`?", "src/core/indexing/db_manager.py"),
    ("P14", "Какой документ является каноном публичных чисел?", "docs/FACTS.md"),
    ("P15", "Где LSP-инструмент отправляет за ссылками?", "src/mcp/tools/lsp_tools.py"),
]
STOP = {"где", "какая", "какой", "нужно", "файл", "функция", "документ", "является",
        "отправляет", "хранится", "решается", "возвращает", "каноном", "числа"}

for task_id, question, gold in CASES:
    words = [w.lower() for w in re.findall(r"[\w-]{4,}", question)]
    words = [w for w in words if w not in STOP and not w.startswith("file_")]
    text = (ROOT / gold).read_text(encoding="utf-8", errors="ignore").lower()
    counts = {w: len(re.findall(rf"\b{re.escape(w)}", text)) for w in words}
    print(f"{task_id} gold={gold}")
    print(f"    words={words} counts={counts}")
    print(f"    any_hit={any(counts.values())}")
