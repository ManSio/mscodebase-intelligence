# Установка MSCodebase Intelligence для Zed IDE

> **MSCodebase Intelligence** — MCP-сервер для семантического поиска кода в Zed IDE.
> Работает полностью локально, без интернета после установки.

---

## 🔧 Системные требования

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| **OS** | Windows 10+, macOS 12+, Linux | Windows 11 |
| **Python** | 3.10+ | 3.11+ |
| **RAM** | 4 GB | 8+ GB |
| **Диск** | 500 MB | 2 GB (с моделью) |
| **Zed IDE** | v0.150+ | последняя версия |
| **Терминал** | Git Bash (Windows) / любой (macOS/Linux) | — |

---

## 📥 Быстрая установка (Windows)

### Шаг 1: Установка

```cmd
:: Откройте Git Bash или cmd в папке расширения
install.bat
```

Установщик сделает всё сам:
1. ✅ Проверит Python
2. ✅ Создаст виртуальное окружение
3. ✅ Установит все зависимости
4. ✅ Настроит MCP-сервер в `settings.json` Zed
5. ✅ Пропишет `PROJECT_PATH` — чтобы сервер знал, где ваш проект

### Шаг 2: Перезапуск Zed

Закройте и откройте Zed заново (`Ctrl+Shift+P` → `window: reload`).

### Шаг 3: Проверка

Откройте **Agent Panel** (`Ctrl+Shift+P` → `Agent Panel: Toggle`) и напишите:
```
get_index_status()
```

Должны увидеть:
```
📊 Статус базы данных MSCodebase:
  • Всего фрагментов кода в базе: ...
  • Режим эмбеддера: 🌐 LM Studio
```

> Если сервер не найден — см. раздел «Устранение проблем» ниже.

---

## 📦 Установка вручную (все платформы)

### Шаг 1: Создание venv

```bash
# Windows (Git Bash)
python -m venv venv
venv/Scripts/python -m pip install -r requirements.txt

# macOS/Linux
python3 -m venv venv
./venv/bin/python3 -m pip install -r requirements.txt
```

### Шаг 2: Настройка Zed

Добавьте в `settings.json`:

**Windows:** `%APPDATA%\Zed\settings.json`
**macOS:** `~/Library/Application Support/Zed/settings.json`
**Linux:** `~/.config/zed/settings.json`

```json
{
  "context_servers": {
    "mscodebase-intelligence": {
      "command": "C:\путь\к\расширению\venv\Scripts\python.exe",
      "args": ["-u", "-m", "src.main"],
      "current_dir": "$ZED_WORKTREE_ROOT",
      "env": {
        "PYTHONPATH": "C:\путь\к\расширению",
        "PROJECT_PATH": "C:\путь\к\вашему\проекту"
      }
    }
  },
  "context_servers_to_query": ["mscodebase-intelligence"]
}
```

> **💡 Важно для Windows:** В поле `env` пропишите `PROJECT_PATH` — абсолютный путь к вашему проекту.
> Иначе сервер не сможет определить корень проекта, и индексация будет пустой.
> 
> **Пример:** `"PROJECT_PATH": "D:\\Project\\MyProject"`

### Шаг 3: Первый запуск

```bash
# Запустите сервер вручную для проверки
python -u -m src.main
```

Должны увидеть:
```
MSCodebase Intelligence MCP Server запускается...
Запуск MCP сервера...
```

### Шаг 4: Первая индексация

В Agent Panel выполните:
```
index_project_dir(path="D:\Project\MSCodeBase")
```
(укажите путь к вашему проекту)

Индексация займёт **1-2 минуты**. После неё можно искать код.

---

## 🧠 ONNX-модель (офлайн-режим без LM Studio)

Для работы без LM Studio нужна embedding-модель:

```bash
python scripts/download_model.py
```

Модель загрузится в `.codebase_models/onnx/`. После этого сервер будет работать полностью офлайн.

---

## 🚀 Опционально: LM Studio (рекомендуется)

LM Studio даёт более качественный поиск:

1. Установите [LM Studio](https://lmstudio.ai/)
2. Загрузите модель: `BAAI/bge-m3` (эмбеддинги) и `phi-4-mini-instruct` (реранкинг)
3. Запустите локальный сервер на порту `1234`
4. MCP-сервер подключится автоматически

---

## ❗ Устранение проблем

### 🔴 «MCP server not found» в Agent Panel

**Причина:** Сервер не запустился, или `settings.json` настроен неверно.

**Решение:**
1. Проверьте `settings.json` — корректный ли путь к `python.exe`?
2. Есть ли `PROJECT_PATH` в `env`? (на Windows — обязательно!)
3. Запустите вручную: `python -u -m src.main` — видны ли ошибки?
4. `Ctrl+Shift+P` → `window: reload`

### 🔴 «PROJECT_PATH не установлен» в логах

**Причина:** На Windows `$ZED_WORKTREE_ROOT` не резолвится.

**Решение:** Добавьте в `settings.json`:
```json
"env": {
  "PROJECT_PATH": "D:\\Ваш\\Проект"
}
```

### 🔴 «0 chunks» в get_index_status()

**Причина:** Индекс ещё не построен.

**Решение:** Выполните `index_project_dir(path="D:\путь\к\проекту")` и подождите 1-2 минуты.

### 🔴 «int32 is not JSON serializable»

**Причина:** Старая версия сервера. Обновитесь до v2.2.0+.

**Решение:** Запустите `install.bat` заново.

### 🔴 LM Studio «Connection refused»

**Причина:** LM Studio не запущен или занят другой порт.

**Решение:** Запустите LM Studio, проверьте что сервер активен на порту 1234.

---

## 📄 Удаление

```cmd
:: Запустите деинсталлятор в папке расширения
uninstall.bat
```

Или вручную:
1. Удалите секцию `mscodebase-intelligence` из `settings.json` Zed
2. Удалите папку расширения: `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`
3. Удалите `.codebase_indices` из корня вашего проекта

---

## 📄 Лицензия

MIT — делайте что хотите, но без гарантий.

---

## Частые проблемы (FAQ)

### MCP server not responding / Context server request timeout
**Cause:** MCP process failed to start or hung.
**Fix:**
1. Check python.exe exists: `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligenceenv\Scripts\python.exe`
2. Kill python.exe processes - Zed will restart MCP automatically
3. Check logs: `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\`

### Self-indexing blocked: target path is not a user project
**Cause:** MCP resolved project root to extension dir or Zed install dir.
**Fix:**
1. Open your project explicitly: Cmd+Shift+P -> Open Project -> select folder
2. Or set PROJECT_PATH in settings.json: `"PROJECT_PATH": "$ZED_WORKTREE_ROOT"`
3. Running install.py fixes this automatically

### Index is empty (0 chunks)
**Cause:** Index has not been built yet.
**Fix:**
1. Call `intel_trigger_reindex()` in chat - indexing starts in background
2. Check status: `intel_get_job_status(job_id=...)`
3. Full indexing takes 3-10 minutes depending on project size

### LM Studio not detected
**Cause:** Extension is running in fallback mode (local ONNX embedder).
**Fix:** This is normal. Vector search works slower but fully offline.
For speed: install LM Studio, run on port 1234.

### notify_change does not update index
**Cause:** Index needs to be built first.
**Fix:**
1. notify_change is incremental - works after initial index exists
2. If index is empty, call `intel_trigger_reindex()` first
3. Check: `get_index_status()` - total_chunks should grow

### Console encoding issues (Windows)
**Cause:** Windows console uses CP866, Python uses UTF-8.
**Fix:**
```
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
python install.py
```

### ModuleNotFoundError: No module named src.*
**Cause:** PYTHONPATH does not point to extension root.
**Fix:** Run install.py again - it sets PYTHONPATH automatically.
