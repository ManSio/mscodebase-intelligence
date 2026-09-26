# -*- coding: utf-8 -*-
"""Build TESTS edges for gemma_agent from trace_result.json."""
import sys
from pathlib import Path

sys.path.insert(0, r"D:\Project\MSCodeBase")
sys.stdout.reconfigure(encoding="utf-8")

from src.core.bootstrap_tests import build_from_trace_file

project_root = Path("D:/Project/gemma_agent")
trace_file = project_root / "trace_result.json"

print("=" * 80)
print("Building TESTS edges for gemma_agent")
print("=" * 80)

result = build_from_trace_file(trace_file, project_root)
print(f"\n✅ Result: {result}")
