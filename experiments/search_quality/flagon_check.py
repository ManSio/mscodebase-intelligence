#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase-2 wiring proof: E5-панель с MSCODEBASE_ONDEMAND_RERANK=true.
Тот же измерительный код, что experiments/search_quality/e24_driver.py (PR #72).
USAGE: $env:MSCODEBASE_ONDEMAND_RERANK="true"; python experiments/search_quality/flagon_check.py
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
import e2e_quality_search as H  # noqa: E402

searcher = H.build_searcher(ROOT)
print(f"ondemand_flag={searcher._ondemand_rerank} top_n={searcher._ondemand_rerank_top_n}")
assert searcher._ondemand_rerank is True, "flag did not reach Searcher"
for mode in ("fast", "quality"):
    rows = H.run_mode(searcher, mode)
    H.report(f"mode={mode} [FLAGON]", rows)
