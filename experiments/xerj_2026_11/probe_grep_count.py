import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.di_container import ServiceCollection  # noqa: E402
from src.mcp.tools.grep_tool import GrepCodeTool  # noqa: E402

tool = GrepCodeTool(ServiceCollection())
tool.resolve_parser = lambda: __import__("src.core.indexing.parser", fromlist=["CodeParser"]).CodeParser()
for pattern in ("ModificationGuard", "build_call_graph", "IndexStatusReporter"):
    res = tool._search(ROOT, None, re.compile(pattern.encode()), "code", 32, 0)
    print(f"{pattern}: total={res['total']} files={res['scanned']} "
          f"first={[m['file'] for m in res['matches'][:3]]}")
