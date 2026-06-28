"""
Скрипт для обновления глобальных настроек Zed.
Переводит со старой архитектуры (отдельные LSP + MCP) на новую (hybrid_server.py).

Запуск: python update_zed_settings.py
"""
import json
import sys
from pathlib import Path

def main():
    settings_path = Path.home() / "AppData" / "Roaming" / "Zed" / "settings.json"

    if not settings_path.exists():
        print(f"❌ Settings not found: {settings_path}")
        return

    with open(settings_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    print("Current config:")
    print(f"  LSP: {config.get('lsp', {}).get('mscodebase-lsp', {}).get('arguments', ['N/A'])[-1]}")
    print(f"  MCP: {list(config.get('context_servers', {}).keys())}")

    # Обновляем LSP на hybrid_server.py
    if 'lsp' in config and 'mscodebase-lsp' in config['lsp']:
        config['lsp']['mscodebase-lsp']['arguments'] = [
            "-u",
            str(Path(__file__).parent / "src" / "hybrid_server.py")
        ]
        print("\n✅ Updated LSP → hybrid_server.py")

    # Удаляем старый context_servers (stdio)
    removed = []
    if 'context_servers' in config:
        removed.append(('context_servers', config.pop('context_servers')))
    if 'context_servers_to_query' in config:
        removed.append(('context_servers_to_query', config.pop('context_servers_to_query')))

    for name, val in removed:
        print(f"🗑️ Removed old {name}: {list(val.keys()) if isinstance(val, dict) else val}")

    # Добавляем новый context_servers (HTTP/SSE)
    config['context_servers'] = {
        'mscodebase-mcp': {
            'url': 'http://127.0.0.1:8765/sse'
        }
    }
    print("✅ Added new context_servers → http://127.0.0.1:8765/sse")

    # Обновляем system_prompt
    config['agent']['system_prompt'] = (
        "MSCodeBase v2.0 Hybrid Architecture. "
        "Indexing is AUTOMATIC via LSP — do not call index_project_dir manually. "
        "Use search_code FIRST for all code queries. "
        "Use get_symbol_info for exact symbol lookups. "
        "Max 50 lines per read_file call."
    )
    print("✅ Updated system_prompt")

    # Сохраняем
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Settings saved to {settings_path}")
    print("\n⚠️  RESTART ZED for changes to take effect!")

if __name__ == "__main__":
    main()
