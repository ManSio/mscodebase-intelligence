import json
from pathlib import Path

settings_path = Path.home() / "AppData" / "Roaming" / "Zed" / "settings.json"

print(f"Чтение: {settings_path}")

with open(settings_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Убираем лишние запятые перед }
import re
content = re.sub(r',\s*}', '}', content)
content = re.sub(r',\s*]', ']', content)

settings = json.loads(content)

# Исправляем пути
project_root = r"D:\Project\MSCodeBase"
python_exe = r"C:\Python314\python.exe"

if "context_servers" in settings:
    if "mscodebase-intelligence" in settings["context_servers"]:
        srv = settings["context_servers"]["mscodebase-intelligence"]
        srv["command"] = python_exe
        srv["args"] = ["-u", f"{project_root}\src\mcp\server.py"]
        srv["env"] = {
            "PROJECT_PATH": "$ZED_WORKTREE_ROOT",
            "PYTHONPATH": project_root
        }
        print("✅ context_servers.mscodebase-intelligence исправлен")

if "lsp" in settings:
    if "mscodebase-lsp" in settings["lsp"]:
        lsp = settings["lsp"]["mscodebase-lsp"]
        lsp["command"] = python_exe
        lsp["arguments"] = ["-u", f"{project_root}\src\lsp_main.py"]
        print("✅ lsp.mscodebase-lsp исправлен")

# Добавляем таймауты
if "mcp" not in settings:
    settings["mcp"] = {}
settings["mcp"]["timeout_ms"] = 60000
settings["mcp"]["initialization_timeout_ms"] = 120000
print("✅ Таймауты MCP увеличены")

with open(settings_path, 'w', encoding='utf-8') as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)

print(f"\n✅ settings.json успешно исправлен!")
print(f"   Файл: {settings_path}")
