# Zed Deep Dive — ACP Registry, basedpyright, Threads.db

> Исследование внутренностей Zed Editor (июль 2026).
> Обнаружены: протокол ACP (38 агентов), форк basedpyright, база данных тредов.

---

## 1. 🏛 ACP — Agent Communication Protocol

**Файл:** `%LOCALAPPDATA%\Zed\external_agents\registry\registry.json`

Zed стандартизировал общение с внешними ИИ-агентами через ACP — надстройку над JSON-RPC.

### 38 зарегистрированных агентов

| # | ID | Версия | Распространение | ACP |
|---|----|--------|----------------|-----|
| 1 | agoragentic-acp | 1.3.0 | npx | `--acp` |
| 2 | amp-acp | 0.8.1 | binary | — |
| 3 | auggie | 0.32.0 | npx | `--acp` |
| 4 | autohand | 0.2.1 | npx | — |
| 5 | claude-acp | 0.58.1 | npx | — |
| 6 | cline | 3.0.39 | npx | `--acp` |
| 7 | codebuddy-code | 2.106.7 | npx | `--acp` |
| 8 | codex-acp | 1.1.2 | npx | — |
| 9 | cortex-code | 1.0.73 | npx | — |
| 10 | corust-agent | 0.6.0 | npx | — |
| 11 | crow-cli | 0.1.24 | npx | — |
| 12 | cursor | 2026.07.09 | binary | — |
| 13 | deepagents | 0.1.7 | binary | — |
| 14 | devin | 3000.1.27 | binary | — |
| 15 | dimcode | 0.2.27 | npx | `acp` |
| 16 | dirac | — | npx | `--acp` |
| 17 | factory-droid | — | npx | `exec --output-format acp-daemon` |
| 18 | fast-agent | — | npx | — |
| **19** | **gemini** | **0.50.0** | **npx** | **`--acp`** |
| 20 | github-copilot-cli | 1.0.70 | npx | `--acp` |
| 21 | glm-acp-agent | — | npx | — |
| 22 | goose | — | binary | — |
| 23 | grok-build | 0.2.97 | npx | — |
| 24 | harn | — | binary | — |
| 25 | junie | — | npx | — |
| 26 | kilo | 7.4.5 | binary + npx | `acp` |
| 27 | kimi | — | uvx | — |
| 28 | minion-code | — | npx | `acp` |
| 29 | mistral-vibe | 2.19.1 | binary | — |
| 30 | nova | — | npx | `acp` |
| 31 | opencode | 1.17.18 | binary | — |
| 32 | pi-acp | — | npx | — |
| 33 | poolside | — | npx | — |
| 34 | qoder | — | binary | — |
| 35 | qwen-code | — | npx | `--acp` |
| 36 | sigit | 1.4.1 | binary + npx | — |
| 37 | stakpak | — | uvx | — |
| 38 | vtcode | — | binary | — |

### Распространение (Distribution)

| Тип | Кол-во | Описание |
|-----|--------|----------|
| **npx** | 21 | npm-пакет, запуск через `npx <package>` |
| **binary** | 17 | Прямая загрузка бинарника под платформу |
| **uvx** | 2 | Python-пакет через uvx |

### Как запустить Gemini через ACP

```bash
npx @google/gemini-cli@0.50.0 --acp
```

---

## 2. 🎯 basedpyright LSP

**Путь:** `%LOCALAPPDATA%\Zed\languages\basedpyright\`

### Почему basedpyright лучше pyright

| Характеристика | pyright (Microsoft) | basedpyright (community) |
|---------------|-------------------|------------------------|
| Версия | 1.1.410 | 1.39.9 |
| PEP 695 (дженерики) | Базовая поддержка | **Полная поддержка** |
| Динамические импорты | Падает | **Стабильно** |
| Кэширование AST | Стандартное | **Агрессивное** |
| WorkspaceEdit | Пустые ответы | **Точные** |
| Совместимость | — | Полная (те же команды) |

### Команды (полностью совместимы с pyright)

```
basedpyright\node_modules\.bin\pyright-langserver.cmd   ✅
basedpyright\node_modules\.bin\pyright.cmd               ✅
basedpyright\node_modules\.bin\pyright-langserver        ✅
```

### Приоритет поиска в LspClient (обновлено)

```
1. PATH (быстрый поиск)
2. Zed/basedpyright/...    ← приоритет (community-форк, лучше)
3. Zed/pyright/...          ← fallback (оригинал)
4. sys.prefix/bin (venv)
5. .venv | venv | .env
```

---

## 3. 💾 Базы данных Zed

| Файл | Размер | Формат | Содержание |
|------|--------|--------|-----------|
| `db/0-global/db.sqlite` | 4 KB | SQLite | `kv_store` — глобальные настройки |
| `threads/threads.db` | **39 MB** | SQLite | История всех диалогов с ИИ |
| `prompts/prompts-library-db.0.mdb` | ~3 MB | LMDB | Библиотека промптов |

### threads.db — потенциальная фича

Zed хранит **все** диалоги с ИИ-ассистентами в SQLite. Это означает:
- Можно написать фоновый парсер для извлечения контекста
- Нарезать на чанки → LanceDB → семантический поиск по прошлым диалогам
- Агент получает долговременную память о всех обсуждениях

---

## 4. 📋 Все LSP серверы в Zed

| Язык | Сервер | Путь |
|------|--------|------|
| Python | **basedpyright** 1.39.9 (приоритет) | `languages/basedpyright/` |
| Python | pyright 1.1.410 (fallback) | `languages/pyright/` |
| Rust | rust-analyzer 2026-07-06 | `languages/rust-analyzer/` |
| Bash | bash-language-server | `languages/bash-language-server/` |
| JSON | json-language-server | `languages/json-language-server/` |
| YAML | yaml-language-server | `languages/yaml-language-server/` |

---

## 5. 🪵 Логи Zed

**Расположение:** `%LOCALAPPDATA%\Zed\logs\`

| Файл | Размер | Описание |
|------|--------|----------|
| `Zed.log` | 837 KB | Основной лог редактора |
| `Zed.log.old` | 1 MB | Предыдущий лог (ротация) |
| `telemetry.log` | 436 KB | Телеметрия |

### Найденные ошибки в логах

| Ошибка | Компонент | Severity |
|--------|-----------|----------|
| `Request failed with status: 403` | edit_prediction (Zed Copilot) | ⚠️ |
| `no snapshots found for buffer X and server 1` | lsp_store | ⚠️ |
| `window not found` / Invalid window handle | gpui_windows | 🟡 |
| `failed to resize alacritty pty` | terminal | 🟡 |

---

## 6. 🔧 Реализованные изменения

### LspClient._find_server() — приоритет basedpyright

**Файл:** `src/core/lsp_client.py` (строки 342-358)

```python
# До: pyright проверялся первым
zed_lsp_dirs = [
    Path(...) / "pyright" / ...,
    Path(...) / "basedpyright" / ...,  # fallback
]

# После: basedpyright в приоритете
lsp_dirs = []
if self.language == "python":
    lsp_dirs.append(Path(...) / "basedpyright" / ...)
lsp_dirs.append(Path(...) / "pyright" / ...)
```

---

*Исследование проведено: 2026-07-11*
*Автор: ManSio / MSCodeBase*
