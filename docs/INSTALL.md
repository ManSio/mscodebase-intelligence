# Установка MSCodebase Intelligence для Zed IDE

> **MSCodebase Intelligence** — MCP-сервер для семантического поиска кода в Zed IDE.
> Работает полностью локально (ONNX embedding на CPU), без внешних API.

---

## 🔧 Системные требования

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| **OS** | Windows 10+ / macOS 12+ / Linux | Windows 11 / macOS 14+ |
| **Python** | 3.10+ | 3.11+ |
| **RAM** | 4 GB | 8+ GB |
| **Диск** | 500 MB свободно | 2 GB (с моделью) |
| **Zed IDE** | v0.150+ | latest |

> **Windows:** Git Bash рекомендован для терминала (идёт с Git for Windows).
> **macOS/Linux:** Стандартный терминал.

---

## 📥 Быстрая установка (Windows)

```cmd
:: 1. Клонировать или распаковать расширение
:: 2. Запустить установщик
install.bat
```

Установщик автоматически:
1. ✅ Проверит Python 3.10+
2. ✅ Создаст виртуальное окружение (venv)
3. ✅ Установит зависимости
4. ✅ Настроит MCP-сервер в `settings.json` Zed
5. ✅ Предложит скачать ONNX-модель для офлайн-режима

---

## 📦 Установка вручную (все платформы)

### Шаг 1: Создание venv

```bash
# Windows
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt

# macOS/Linux
python3 -m venv venv
./venv/bin/python3 -m pip install -r requirements.txt
```

### Шаг 2: Настройка MCP-сервера в Zed

Добавь в `settings.json` Zed (`%APPDATA%\Zed\settings.json` на Windows,
`~/.config/zed/settings.json` на Linux, `~/Library/Application Support/Zed/settings.json` на macOS):

```json
{
  "context_servers": {
    "mscodebase-intelligence": {
      "command": "C:\\Users\\<USER>\\AppData\\Local\\Zed\\extensions\\mscodebase-intelligence\\venv\\Scripts\\python.exe",
      "args": ["-u", "-m", "src.main"],
      "current_dir": "$ZED_WORKTREE_ROOT",
      "env": {
        "PROJECT_PATH": "$ZED_WORKTREE_ROOT",
        "PYTHONPATH": "$ZED_WORKTREE_ROOT"
      }
    }
  },
  "context_servers_to_query": ["mscodebase-intelligence"]
}
```

> **Важно:** `current_dir` должен указывать на **проект**, а не на директорию расширения.
> Используй `$ZED_WORKTREE_ROOT` — Zed сам подставит путь к открытому проекту.

### Шаг 3: Запуск

Перезапусти Zed → открой `Agent Panel` (`Ctrl+Shift+P` → `Agent Panel: Toggle`) →
выбери модель и задай вопрос.

---

## 🧠 ONNX-модель (офлайн-режим)

Для работы без LM Studio/Ollama нужна embedding-модель в ONNX формате:

```bash
# Рекомендуемая (баланс качества/скорости)
python scripts/download_model.py

# Лёгкая (200 MB RAM)
python scripts/download_model.py --model intfloat/multilingual-e5-small

# Мощная (3 GB RAM, требует GPU)
python scripts/download_model.py --model Alibaba-NLP/gte-Qwen2-1.5B-instruct
```

Модель сохраняется в `.codebase_models/onnx/` и автоматически подхватывается
при старте сервера.

> **Фишка:** Кэш модели сохраняется в `~/.cache/mscodebase/hf_models/`.
> При повторном запуске модель не перекачивается. Для принудительного ре-экспорта: `--force`.

---

## 🔄 Обновление после изменений кода

```cmd
:: Быстрая синхронизация (только исходники, venv не трогается)
sync_to_installed.bat

:: Если добавились новые зависимости
sync_to_installed.bat
python -m pip install -r requirements.txt

:: Полная переустановка
install.bat
```

---

## 🚀 Опционально: LM Studio (рекомендуется)

MSCodebase Intelligence может использовать **LM Studio** для более мощных эмбеддингов:

1. Установи [LM Studio](https://lmstudio.ai/)
2. Загрузи модель: `nomic-ai/nomic-embed-text-v1.5` или `BAAI/bge-m3`
3. Запусти локальный сервер на порту `1234`
4. MCP-сервер подключится автоматически

Без LM Studio используется **встроенный ONNX-эмбеддер** — медленнее,
но работает полностью офлайн.

---

## 🐳 Не нужен Docker

Расширение работает **нативно** — никаких контейнеров, WSL или лишних слоёв абстракции.
Всё что нужно: Python + Pip.

---

## ❗ Устранение проблем

| Проблема | Решение |
|----------|---------|
| `MCP server not found` | Проверь `settings.json`, перезапусти Zed |
| `PROJECT_PATH not set` | Укажи `"current_dir": "$ZED_WORKTREE_ROOT"` |
| `0 chunks in index` | Вызови `index_project_dir(path)` |
| `ONNX model not found` | Запусти `python scripts/download_model.py` |
| `LM Studio connection refused` | Проверь что LM Studio запущен на порту 1234 |

---

## 📄 Лицензия

MIT — делай что хочешь, но без гарантий.
