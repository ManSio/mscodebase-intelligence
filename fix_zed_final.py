import json
from pathlib import Path

settings_path = Path.home() / "AppData" / "Roaming" / "Zed" / "settings.json"

with open(settings_path, 'r', encoding='utf-8') as f:
    content = f.read()

import re
content = re.sub(r',\s*}', '}', content)
content = re.sub(r',\s*]', ']', content)

settings = json.loads(content)

project_root = r"D:\Project\MSCodeBase"
python_exe = r"C:\Python314\python.exe"

# Обновляем context_servers
if "context_servers" in settings:
    if "mscodebase-intelligence" in settings["context_servers"]:
        srv = settings["context_servers"]["mscodebase-intelligence"]
        srv["command"] = python_exe
        srv["args"] = [
            "-u",
            f"{project_root}\src\mcp\server.py"
        ]
        srv["env"] = {
            "PYTHONPATH": project_root,
            "PROJECT_PATH": "$ZED_WORKTREE_ROOT"
        }
        print("✅ context_servers.mscodebase-intelligence OK")

# Обновляем lsp
if "lsp" in settings:
    if "mscodebase-lsp" in settings["lsp"]:
        lsp = settings["lsp"]["mscodebase-lsp"]
        lsp["command"] = python_exe
        lsp["arguments"] = [
            "-u",
            f"{project_root}\src\lsp_main.py"
        ]
        lsp["env"] = {"PYTHONPATH": project_root}
        print("✅ lsp.mscodebase-lsp OK")

# Таймауты
settings.setdefault("mcp", {})["timeout_ms"] = 60000
settings.setdefault("mcp", {})["initialization_timeout_ms"] = 120000

with open(settings_path, 'w', encoding='utf-8') as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)

print("\n✅ settings.json обновлен!")
print(f"   Python: {python_exe}")
print(f"   Проект: {project_root}")
