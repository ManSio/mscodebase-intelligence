"""Рабочий черновик E16 — RU-документный корпус для bench.py.
⚠️ РАБОЧИЙ ФАЙЛ (не прод). Положит реальные .md в корпус и RU-запросы по их содержимому.
Методика: сборка происходит через bench.py с --chunk-tokens 203, --ubatch 512, pooling mean, raw (равные E15).
"""
from pathlib import Path

R = Path(r"D:\Project\MSCodeBase")

# Документный корпус: русскоязычные .md + англ. .md с RU-содержимым.
# Цели (RU-запрос → .md файл)
GOLD_DOCS = [
    ("как устроена мультиязычность эмбеддера и почему e5 выбран в прод", "docs/research/2026-07-12-e5-base-migration.md"),
    ("документация по архитектуре: диаграмировать связи модулей mcp и ide", "docs/ru/ARCHITECTURE.md"),
    ("глубокое описание архитектуры проекта и слоёв", "docs/ru/ARCHITECTURE_DEEP.md"),
    ("почему переиндексация одного файла дешевле чем полного проекта", "docs/ru/docs.md" if (R/"docs/ru/docs.md").exists() else "docs/ru/ARCHITECTURE.md"),
    ("обзор пакета universal-engine исследование что внутри", "docs/research/universal-engine-study/02-study-and-improvements.md"),
    ("как обучался nomic и что такое префиксы document search", "docs/research/universal-engine-study/.task-state.md"),
]

# Дистракторы — пока возьмём distractor-файлы исходников, чтобы чанк-пул был честным
DISTRACTORS_DOCS = [
    "src/providers/reranker/search_result_reranker.py",
    "src/core/search/bm25.py",
]
