# Настройка MSCodebase Intelligence в Zed

## Автоматическая настройка

При установке через `install.py` настройки (MCP + LSP) добавляются автоматически:

```bash
python install.py
```

Скрипт создаёт конфигурацию в `%APPDATA%\Zed\settings.json`:
- **MCP-сервер** (`mscodebase-intelligence`) — для AI-ассистента в чате Zed
- **LSP-сервер** (`mscodebase-lsp`) — для фоновой индексации файлов
- **Привязка к языкам** — Python, TypeScript, Rust, Go, JavaScript
- **Системные правила** (`agent.system_prompt`) — для AI-агента

## Ручная настройка

Добавьте в глобальные настройки Zed (`%APPDATA%\Zed\settings.json`):

```json
{
  // MCP Server (для AI-ассистента)
  "context_servers": {
    "mscodebase-intelligence": {
      "command": "<python.exe>",
      "args": ["-u", "-m", "src.main"],
      "current_dir": "<ext_install_dir>",
      "env": {
        "PROJECT_PATH": "$ZED_WORKTREE_ROOT",
        "PYTHONPATH": "<ext_install_dir>"
      }
    }
  },
  "context_servers_to_query": ["mscodebase-intelligence"],

  // LSP Server (для фоновой индексации)
  "lsp": {
    "mscodebase-lsp": {
      "command": "<python.exe>",
      "arguments": ["-u", "<ext_install_dir>/src/lsp_main.py"]
    }
  },

  // Привязка LSP к языкам
  "languages": {
    "Python": { "language_servers": ["pyright", "mscodebase-lsp"] },
    "TypeScript": { "language_servers": ["typescript-language-server", "mscodebase-lsp"] },
    "Rust": { "language_servers": ["rust-analyzer", "mscodebase-lsp"] },
    "Go": { "language_servers": ["gopls", "mscodebase-lsp"] },
    "JavaScript": { "language_servers": ["vtsls", "mscodebase-lsp"] }
  }
}
```

Где:
- `<python.exe>` — путь к Python в venv расширения (например, `C:\Users\...\mscodebase-intelligence\venv\Scripts\python.exe`)
- `<ext_install_dir>` — путь к установленному расширению (например, `C:\Users\...\mscodebase-intelligence`)

## Как это работает

1. **MCP-сервер** — запускается Zed-ом при открытии чата AI. Предоставляет 26 инструментов для анализа кода
2. **LSP-сервер** — запускается при открытии проекта. В реальном времени отслеживает изменения файлов и индексирует их в LanceDB
3. **Единый процесс** — оба сервера работают в одном процессе (через `hybrid_server.py`) и используют общую память

## Синхронизация после изменений

Если вы изменили исходный код расширения в директории разработки, синхронизируйте с установленным:

```bash
sync_to_installed.bat
```

Или вручную скопируйте:
```bash
xcopy /E /I /Y D:\Project\MSCodeBase\src %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\src
```

После синхронизации **обязательно перезапустите Zed**.
