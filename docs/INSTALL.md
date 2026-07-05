# Установка MSCodebase Intelligence для Zed IDE

> **MSCodebase Intelligence** — MCP-сервер для семантического поиска кода в Zed IDE.
> Разработка ведётся в [github.com/ManSio/mscodebase-intelligence](https://github.com/ManSio/mscodebase-intelligence)
> После установки работает полностью локально.

---

## 🔧 Системные требования

| Компонент | Требование |
|-----------|-----------|
| **OS** | Windows 10+ (основная поддержка), macOS 12+, Linux |
| **Python** | 3.10+ (рекомендуется 3.11+) |
| **RAM** | 4 GB (рекомендуется 8+ GB) |
| **Диск** | 500 MB (с моделью — до 2 GB) |
| **Zed IDE** | актуальная версия |
| **LM Studio** (опционально) | для векторного поиска через эмбеддинги |

---

## 📥 Быстрая установка

### Шаг 1: Установка расширения

Откройте терминал в **корне вашего проекта** (где находится `install.py`) и выполните:

```bash
python install.py
```

Установщик:
1. ✅ Проверит Python и совместимость
2. ✅ Создаст виртуальное окружение и установит зависимости
3. ✅ Настроит MCP-сервер в `settings.json` Zed
4. ✅ Скопирует исходники в установленное расширение
5. ✅ Создаст `uninstall.bat`

> **Важно:** Установщик копирует файлы из текущей директории в расширение.
> Все изменения в исходниках применяются только после `python install.py`.

### Шаг 2: Перезапуск Zed

**File → Quit**, затем откройте проект заново.
Простой `window: reload` **недостаточен** — MCP-сервер должен перезапуститься полностью.

### Шаг 3: Проверка

Откройте **Agent Panel** (`Ctrl+Shift+P` → `Agent Panel: Toggle`) и выполните:

```
get_index_status()
```

Должны увидеть:

```
📂 <корень-вашего-проекта>
🟢 **MSCodeBase** — active
📦 **Чанки:** `1603` | **Файлы:** `114` | **Символы:** `134`
🧠 **Эмбеддер:** 🌐 LM Studio
```

Если проект определён неверно (вместо вашего проекта показывается другой) — закройте
все окна Zed и откройте только нужный проект.

---

## 🧠 Особенности Windows

На Windows есть **критические особенности**, которые нужно знать:

| Проблема | Симптом | Решение |
|----------|---------|---------|
| **Restricted Mode** | LSP не стартует, MCP не видит проект | Нажмите «Trust and Continue» при открытии проекта |
| **CWD = директория Zed** | MCP-сервер запускается из папки, где установлен Zed, а не из проекта | Исправлено через SQLite fallback (проект берётся из базы Zed, а не из CWD) |
| **MCP не перезапускается** | После kill'а процесса инструменты не работают | Только полный рестарт Zed (File → Quit) |
| **Проект резолвится неверно** | Вместо MSCodeBase показывает gemma_agent | Закройте все окна Zed, откройте только нужный проект |

Подробнее: **[ZED_WINDOWS_QUIRKS.md](../ZED_WINDOWS_QUIRKS.md)**

### Как определяется проект (без LSP)

MCP-сервер определяет текущий проект в таком порядке:

1. **Явный `project_root`** из аргументов инструмента
2. **SQLite `active_workspace_id`** (НОВЫЙ, основной!) — читает `scoped_kv_store`
   в базе Zed, где хранится `active_workspace_id` — ЕДИНСТВЕННЫЙ механизм,
   работающий на Windows. Мгновенно переключается при смене проекта.
3. **SQLite `workspaces`** (старый fallback) — выбирает самый свежий проект
   из таблицы `workspaces`, если `active_workspace_id` не найден.
4. **LSP Bridge** (JSON-файл от LSP — **не работает на Windows**, LSP не стартует)
5. **`PROJECT_PATH`** из окружения
6. **CWD** — **всегда отклоняется** self-indexing guard
7. **ext_root** (директория расширения) — fallback

> На Windows шаги 1, 4-5 обычно недоступны, поэтому проект определяется
через SQLite `active_workspace_id` (шаг 2). Этот механизм автоматически
переключает проект при смене активного окна в Zed. Если определение
всё равно неверное — закройте лишние окна Zed.

---

## 🚀 Опционально: LM Studio

LM Studio даёт более качественный поиск за счёт векторных эмбеддингов.

1. Установите [LM Studio](https://lmstudio.ai/)
2. Загрузите модель для эмбеддингов (например, `BAAI/bge-m3`)
3. Запустите локальный сервер на порту `1234`
4. MCP-сервер подключится автоматически

Проверка:
```
intel_get_runtime_status()
```
В ответе должно быть `"embedding_provider": "lm_studio"` и `"lm_studio_at_1234": "online"`.

---

## 📄 Удаление

```cmd
:: Запустите деинсталлятор
uninstall.bat
```

Или вручную:
1. Удалите секцию `mscodebase-intelligence` из `%APPDATA%\Zed\settings.json`
2. Удалите папку расширения:
   ```
   %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence
   ```
3. Удалите `.codebase_indices` из корня вашего проекта (если есть)

---

## ❗ Устранение проблем

| Проблема | Причина | Решение |
|----------|---------|---------|
| **Инструменты не отвечают** | MCP-сервер не запущен | File → Quit → открыть проект заново. Логи: `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\` |
| **Неверный проект** | SQLite выбрал другой workspace | Закрыть все окна Zed, открыть только нужный проект |
| **0 чанков** | Индекс пуст | `intel_trigger_reindex()` — подождать 1-5 минут |
| **LM Studio offline** | Сервер не запущен | Запустить LM Studio, проверить порт 1234 |
| **settings.json варнинг** | Устаревшие ключи (`lsp`, `mscodebase`) | Запустить `python install.py` — он почистит |
| **ModuleNotFoundError** | PYTHONPATH не指向ет на расширение | `python install.py` — исправит автоматически |

**Где хранятся данные:**
- **Индекс (LanceDB):** `<проект>/.codebase_indices/lancedb_v2/` — векторная БД с чанками кода
- **Логи:** `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\`
- **Память проекта (ADR, known_issues):** `<проект>/.codebase_indices/intelligence/`

---

## 👨‍💻 Разработка (contributors)

```bash
# Склонировать
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence

# Установить в режиме разработки
pip install -e ".[dev]"

# Запустить тесты
pytest

# Установить в Zed (после изменений)
python install.py
```

Подробнее: **[CONTRIBUTING.md](../CONTRIBUTING.md)**

---

## 🔗 Связанные документы

| Документ | Описание |
|----------|----------|
| [README.md](../README.md) | Главная документация, карта всех доков, список инструментов |
| [ZED_WINDOWS_QUIRKS.md](../ZED_WINDOWS_QUIRKS.md) | **Windows-специфика:** Restricted Mode, CWD, MCP-рестарт |
| [docs/architecture.md](architecture.md) | Архитектура проекта, DI, слои |
| [docs/telemetry.md](telemetry.md) | Метрики, ETA, сбор данных |
| [docs/investigations/2026-07-05-lsp-zed-1.9.0.md](investigations/2026-07-05-lsp-zed-1.9.0.md) | Почему LSP не работает на Windows |
| [CHANGELOG.md](../CHANGELOG.md) | История версий |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Разработка, тесты, PR |
