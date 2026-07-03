import json
from pathlib import Path

settings_path = Path.home() / "AppData" / "Roaming" / "Zed" / "settings.json"

if settings_path.exists():
    with open(settings_path, 'r', encoding='utf-8') as f:
        settings = json.load(f)
    
    # Исправляем пути
    project_root = "D:\Project\MSCodeBase"
    python_exe = "C:\Python314\python.exe"  # или путь к вашему Python
    
    if "context_servers" in settings:
        if "mscodebase-intelligence" in settings["context_servers"]:
            settings["context_servers"]["mscodebase-intelligence"]["command"] = python_exe
            settings["context_servers"]["mscodebase-intelligence"]["args"] = [
                "-u",
                f"{project_root}\src\mcp\server.py"
            ]
            settings["context_servers"]["mscodebase-intelligence"]["env"] = {
                "PROJECT_PATH": "$ZED_WORKTREE_ROOT",
                "PYTHONPATH": project_root
            }
    
    if "lsp" in settings:
        if "mscodebase-lsp" in settings["lsp"]:
            settings["lsp"]["mscodebase-lsp"]["command"] = python_exe
            settings["lsp"]["mscodebase-lsp"]["arguments"] = [
                "-u",
                f"{project_root}\src\lsp_main.py"
            ]
    
    # Добавляем таймауты
    settings.setdefault("mcp", {})["timeout_ms"] = 60000
    settings.setdefault("mcp", {})["initialization_timeout_ms"] = 120000
    
    with open(settings_path, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    
    print(f"✅ settings.json исправлен: {settings_path}")
else:
    print(f"⚠️ Файл не найден: {settings_path}")
