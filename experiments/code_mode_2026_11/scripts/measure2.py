import json
import tempfile
from pathlib import Path

import tiktoken

ENC = tiktoken.get_encoding("cl100k_base")
D = Path(tempfile.gettempdir()) / "opencode" / "codemode-exp"


def type_of(s):
    if "type" in s:
        t = s["type"]
        return f"{type_of(s.get('items', {}))}[]" if t == "array" else t
    for k in ("anyOf", "oneOf"):
        if k in s:
            return " | ".join(type_of(x) for x in s[k])
    return "any"


def sheet(tools, doc):
    out = ["declare const mscodebase: {"]
    for t in tools:
        sch = t.get("inputSchema") or {}
        props = sch.get("properties") or {}
        req = set(sch.get("required") or [])
        params = ", ".join(
            f"{n}{'' if n in req else '?'}: {type_of(m)}" for n, m in props.items()
        )
        if doc:
            desc = (t.get("description") or "").strip().replace("\n", " ")
            out.append(f"  /** {desc[:240]} */")
        out.append(f"  {t['name']}({params}): Promise<unknown>;")
    out.append("};")
    return "\n".join(out)


rows = []
for label, f in (("core", "tools_core.json"), ("full", "tools_full.json")):
    tools = json.load(open(D / f, encoding="utf-8"))
    for arm, text in (
        ("json", json.dumps(tools, ensure_ascii=False)),
        ("sheet", sheet(tools, False)),
        ("sheet+doc", sheet(tools, True)),
    ):
        rows.append((label, len(tools), arm, len(text), len(ENC.encode(text))))
for r in rows:
    print(f"{r[0]:5s} n={r[1]:3d} {r[2]:10s} chars={r[3]:6d} tokens={r[4]:6d}")

distilled = json.dumps(
    {
        "definition": "src/core/modification_guard.py:180",
        "callers": 11,
        "callees": 0,
        "risk": {"level": "medium", "score": 46},
        "affected_files": ["src/core/modification_guard.py"],
        "tests": ["tests/test_modification_guard.py"],
        "evidence": [
            "src/mcp/server_tools.py:88 (uses guard)",
            "src/mcp/tools/codebase_tool.py:69 (decorator)",
        ],
    },
    ensure_ascii=False,
    indent=1,
)
print("distilled chars=", len(distilled), "tokens=", len(ENC.encode(distilled)))
