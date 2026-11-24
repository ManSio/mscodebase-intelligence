"""Measure context cost of MCP tool definitions vs a compact signature sheet.

Arm A: JSON tool definitions as served by tools/list (what every MCP client puts
       into the model's context).
Arm B: the same tools expressed as a TypeScript-like signature sheet (one
       `run(code)` tool + typed API), the shape Cloudflare's Code Mode generates.

Tokens: cl100k_base (BPE proxy for a modern chat model; method stated in report).
"""
from __future__ import annotations

import json
import sys

import tiktoken

ENC = tiktoken.get_encoding("cl100k_base")


def toks(text: str) -> int:
    return len(ENC.encode(text))


def type_of(schema: dict) -> str:
    if "type" in schema:
        t = schema["type"]
        if t == "array":
            return f"{type_of(schema.get('items', {}))}[]"
        return t
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return " | ".join(type_of(s) for s in schema[key])
    return "any"


def signature(tool: dict) -> str:
    schema = tool.get("inputSchema") or {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    params = ", ".join(
        f"{name}{'' if name in required else '?'}: {type_of(meta)}"
        for name, meta in props.items()
    )
    return f"  {tool['name']}({params}): Promise<unknown>;"


def main() -> int:
    arm_files = [("core", sys.argv[1]), ("full", sys.argv[2])]
    rows = []
    for label, path in arm_files:
        tools = json.load(open(path, encoding="utf-8"))
        raw = json.dumps(tools, ensure_ascii=False)
        per_tool = sorted(
            ((toks(json.dumps(t, ensure_ascii=False)), t["name"]) for t in tools),
            reverse=True,
        )
        sheet = "declare const mscodebase: {\n" + "\n".join(signature(t) for t in tools) + "\n};"
        rows.append({
            "arm": label,
            "tools": len(tools),
            "json_chars": len(raw),
            "json_tokens": toks(raw),
            "sheet_chars": len(sheet),
            "sheet_tokens": toks(sheet),
            "top": per_tool[:8],
            "desc_share": sum(toks(t.get("description", "")) for t in tools),
        })
        with open(path.replace(".json", "_sheet.d.ts"), "w", encoding="utf-8") as fh:
            fh.write(sheet)

    for r in rows:
        print(f"== {r['arm']}: {r['tools']} tools")
        print(f"   JSON defs : {r['json_chars']:>7} chars  {r['json_tokens']:>6} tokens")
        print(f"   signatures: {r['sheet_chars']:>7} chars  {r['sheet_tokens']:>6} tokens")
        print(f"   descriptions alone: {r['desc_share']:>6} tokens")
        print(f"   ratio (signatures/JSON): {r['sheet_tokens']/r['json_tokens']:.2f}")
        print("   heaviest tools (tokens): " + ", ".join(f"{n}={c}" for c, n in r["top"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
