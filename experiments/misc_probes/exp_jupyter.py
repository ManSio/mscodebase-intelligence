"""EXP-JUPYTER: .ipynb = JSON. stdlib-парсинг + интеграция с CodeParser (H-JUPYTER).

Гипотеза: .ipynb разбирается stdlib json (nbformat опционален), code cells
подаются в существующий tree-sitter пайплайн CodeParser без новых движков.
"""
import sys
import json
import time
import statistics
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

SAMPLE = {
    "cells": [
        {"cell_type": "markdown", "source": ["# Data analysis\n", "EDA notebook"]},
        {"cell_type": "code", "source": [
            "import pandas as pd\n", "import numpy as np\n", "\n",
            "df = pd.read_csv('data.csv')\n",
        ]},
        {"cell_type": "code", "source": [
            "def transform(x):\n",
            "    \"\"\"z-score normalize\"\"\"\n",
            "    return (x - x.mean()) / x.std()\n",
            "\n",
            "df['z'] = transform(df['value'])\n",
        ]},
        {"cell_type": "markdown", "source": ["## Results"]},
        {"cell_type": "code", "source": ["print(df.head())\n"]},
    ],
    "metadata": {"language_info": {"name": "python"}},
    "nbformat": 4,
    "nbformat_minor": 5,
}

raw = json.dumps(SAMPLE).encode()

# 1) Скорость парсинга stdlib json (200 прогонов)
times = []
for _ in range(200):
    t0 = time.perf_counter()
    nb = json.loads(raw)
    times.append((time.perf_counter() - t0) * 1000)
print("json.loads 200x: median_ms =", round(statistics.median(times), 4))

# 2) Извлечение code cells
code_cells = [c for c in nb["cells"] if c.get("cell_type") == "code"]
sources = ["".join(c.get("source", [])) for c in code_cells]
print(f"cells={len(nb['cells'])} code_cells={len(code_cells)}")
for i, s in enumerate(sources):
    print(f"  cell {i}: {len(s)} chars / {s.count(chr(10)) + 1} lines")

# 3) Интеграция: cell -> временный .py -> существующий CodeParser.parse_file
try:
    from src.core.indexing.parser import CodeParser
    parser = CodeParser()
    print(f"CodeParser.parsers keys: {sorted(parser.parsers.keys())[:12]} ...")
    total_chunks = 0
    with tempfile.TemporaryDirectory() as td:
        for i, src in enumerate(sources):
            fp = Path(td) / f"cell_{i}.py"
            fp.write_text(src, encoding="utf-8")
            t0 = time.perf_counter()
            chunks, symbols = parser.parse_file(fp)
            ms = (time.perf_counter() - t0) * 1000
            total_chunks += len(chunks)
            print(f"  cell {i} -> parse_file: {len(chunks)} chunks, {len(symbols)} syms, {round(ms, 2)}ms")
    print("TOTAL chunks из 3 code cells:", total_chunks)
except Exception as e:
    import traceback
    traceback.print_exc()
    print("CodeParser integration failed:", e)
