"""Patch Zed settings.json: добавить MSCODEBASE_ALLOW_SELF_INDEX=1 в env MCP и LSP."""
import json
import os
import sys

path = r"C:\Users\misha\AppData\Roaming\Zed\settings.json"
with open(path, "r", encoding="utf-8") as f:
    s = json.load(f)

ext_install = "C:\\Users\\misha\\AppData\\Local\\Zed\\extensions\\mscodebase-intelligence"

# Update MCP env
srv = "mscodebase-intelligence"
if srv in s.get("context_servers", {}):
    env = s["context_servers"][srv].setdefault("env", {})
    env["MSCODEBASE_ALLOW_SELF_INDEX"] = "1"
    env["PYTHONPATH"] = env.get("PYTHONPATH", ext_install)
    env["PROJECT_PATH"] = env.get("PROJECT_PATH", "$ZED_WORKTREE_ROOT")

# Update LSP env
if "mscodebase-lsp" in s.get("lsp", {}):
    env = s["lsp"]["mscodebase-lsp"].setdefault("env", {})
    env["MSCODEBASE_ALLOW_SELF_INDEX"] = "1"
    env["PYTHONPATH"] = env.get("PYTHONPATH", ext_install)
    env["PROJECT_PATH"] = env.get("PROJECT_PATH", "$ZED_WORKTREE_ROOT")

with open(path, "w", encoding="utf-8") as f:
    json.dump(s, f, indent=2, ensure_ascii=False)
print("patched OK")
print(f"mscodebase-intelligence env: {s['context_servers']['mscodebase-intelligence']['env']}")
print(f"mscodebase-lsp env: {s['lsp']['mscodebase-lsp']['env']}")
