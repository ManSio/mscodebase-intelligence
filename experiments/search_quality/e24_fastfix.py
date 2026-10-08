#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E24-FASTFIX proof: fast-панель без эмбеддера после обёртки (E24 дал 10/10 ERR).
Ожидание: ERR_ROWS=0 (деградация на FTS5+граф вместо исключений).
USAGE: убить :8080, $env:DISABLE_ONNX_FALLBACK="true"; python experiments/search_quality/e24_fastfix.py
"""
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import e2e_quality_search as H

searcher = H.build_searcher(ROOT)
rows = H.run_mode(searcher, "fast")
H.report("mode=fast [POSTFIX no-vector]", rows)
errs = sum(1 for r in rows if r[2] < 0)
print(f"ERR_ROWS={errs}/10")
sys.exit(2 if errs else 0)
