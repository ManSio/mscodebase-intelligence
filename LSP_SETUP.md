# Настройка LSP-сервера в Zed

## Автоматическая настройка

При установке через `install.py` LSP-сервер автоматически добавляется в настройки Zed.

## Ручная настройка

Добавьте в глобальные настройки Zed (`%APPDATA%\Zed\settings.json`):

```json
{
  "lsp": {
    "mscodebase-lsp": {
      "command": "python",
      "args": ["-u", "D:/Path/To/MSCodeBase/src/lsp_main.py"]
    }
  },

  "languages": {
    "Python": {
      "language_servers": ["mscodebase-lsp"]
    },
    "TypeScript": {
      "language_servers": ["mscodebase-lsp"]
    },
    "Rust": {
      "language_servers": ["mscodebase-lsp"]
    },
    "Go": {
      "language_servers": ["mscodebase-lsp"]
    },
    "JavaScript": {
      "language_servers": ["mscodebase-lsp"]
    }
  }
}
```

## Как это работает

1. Zed запускает LSP-сервер при открытии проекта
2. При каждом `Ctrl+S` сервер получает уведомление `textDocument/didSave`
3. Файл автоматически индексируется в фоне
4. MCP-сервер может сразу использовать свежие эмбеддинги

## Преимущества

- **Нет конфликтов файлов** — Zed гарантирует, что файл записан и готов к чтению
- **Нет отдельных процессов-вотчеров** — используется встроенный механизм Zed
- **Мгновенный отклик** — индекс всегда актуелен
