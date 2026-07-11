# Zed на Windows: Подводные камни и архитектурные решения

[🇬🇧 English](../en/ZED_WINDOWS_QUIRKS.md) • [🇷🇺 Русский](ZED_WINDOWS_QUIRKS.md) • [🇨🇳 中文](../zh/ZED_WINDOWS_QUIRKS.md)

> Версия: 1.2 (2026-07-11) — обновлено для llama.cpp + Vulkan
> Применяется к: MSCodeBase Intelligence v2.7.0+
> Полный отчёт: [../en/investigations/LSP_WONTFIX.md](../en/investigations/LSP_WONTFIX.md)

## ⚠️ Критично: Restricted Mode

При открытии **нового** проекта в Zed (который ещё не открывался), редактор
показывает диалог безопасности **"Restricted Mode"**. Это НЕ баг — это встроенный
механизм защиты Zed.

### Что блокирует Restricted Mode

| Механизм | Статус | Последствие |
|-----------|--------|-------------|
| Language servers (LSP) | 🔴 Полностью заблокирован | `lsp_main.py` не запускается → bridge не записывает bridge-файл |
| Локальный `settings.json` (`.zed/settings.json`) | 🔴 Игнорируется | `current_dir` и `env` из настроек не применяются |
| MCP-серверы | 🔴 Не установлены | Контекстные серверы не регистрируются |

### Как исправить

1. **Нажмите "Trust and Continue"** (или `Enter`)
2. **Отметьте "Trust all projects in D:\Project"** — чтобы больше не
   видеть этот диалог для всей рабочей директории
3. **Без этой отметки** каждый новый проект из `D:\Project` будет
   показывать диалог заново

### Почему MSCodeBase нужно это знать

Если проект в Restricted Mode:
- `LSP Bridge` не записывает JSON-файлы → `resolve_project_root()` не получает
  проект от LSP
- `SQLite DB fallback` ВСЁ ЕЩЁ РАБОТАЕТ (читает `workspaces` из базы Zed)
- Но `settings.json` игнорируется → `current_dir` не меняется → CWD
  всегда указывает на директорию установки Zed (например, `D:\AI\Zed`
  или `C:\Program Files\Zed\`)

---

## 🪟 Особенности Windows: ZED_WORKTREE_ROOT

**Статус:** ⚠️ Всегда `<unset>` на Windows (баг Zed #36019)

Переменная окружения `ZED_WORKTREE_ROOT` НЕ УСТАНОВЛЕНА на Windows.
Это известный баг Zed, закрытый без исправления.

### Что это значит

- В `settings.json` для `context_servers` нельзя использовать `$ZED_WORKTREE_ROOT`
  в `current_dir` или `env`
- Любая попытка полагаться на эту переменную даст `None`
- На Linux/macOS эта переменная устанавливается корректно

### Решение в MSCodeBase

Используется цепочка fallback'ов (см. ниже), которая работает без
`ZED_WORKTREE_ROOT`:

1. ~~`LSP Bridge` — LSP получает `root_uri` через LSP-протокол~~
   **НЕ РАБОТАЕТ на Windows** — LSP-сервер не запускается (см.
   [../en/investigations/LSP_WONTFIX.md](../en/investigations/LSP_WONTFIX.md)).
2. `SQLite DB` — читает `workspaces` из базы Zed (основной рабочий путь)
3. `PROJECT_PATH` из `.env` — ручное указание проекта

---

## 🔧 Цепочка resolve_project_root (приоритет)

MCP-сервер определяет текущий проект в следующем порядке:

```
[Запрос от инструмента]
    │
    ▼
1. Передан явный project_root? ──(Да)──> Использовать его
    │ (Нет)
    ▼
2. Существует LSP Bridge файл? ──(НЕТ на Windows — LSP не запускается)──> Шаг 3
3. Доступна SQLite база Zed? ──(Да)──> Прочитать workspaces,
    │                                  отфильтровать self-indexing,
    │                                  отсортировать по .git + timestamp
    │ (Нет / БД заблокирована)
    ▼
4. PROJECT_PATH из .env? ──(Да)──> Использовать его
    │ (Нет)
    ▼
5. CWD (всегда директория установки Zed, напр. `D:\AI\Zed`) ──> защита от self-indexing
    │                       ──> fallback на ext_root
    ▼
                ⚠️ Режим самодиагностики
```

### Multi-window: MCP не различает окна

**Проблема:** Все MCP-инструменты (кроме `intel_*`) работают с **одним проектом** —
тем, который `resolve_project_root()` выбрал по умолчанию. Если у вас открыто
несколько окон с разными проектами, `get_index_status()` покажет индекс проекта
по умолчанию, а не того окна, в котором вы сейчас находитесь.

**Причина:** MCP-сервер — это единый процесс для всех окон Zed.
Он не знает, из какого окна пришёл запрос.
На macOS/Linux `ZED_WORKTREE_ROOT` решает эту проблему,
на Windows он всегда `<unset>`.

**Обход:**
- Для `intel_*` инструментов: они сами находят первый не-self-indexing проект
- Для `get_index_status`: закройте лишние окна, оставьте только нужный проект
- Для `search_code`: передавайте явный `project_root` (если инструмент поддерживает)

---

### Шаг 3: SQLite DB (база Zed) — как это работает

**Это НЕ наша база данных.** Это собственная база Zed, которая хранит
открытые проекты (workspaces). Мы только читаем из неё (read-only).
```
%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite
```

Читается таблица `workspaces`:
```sql
SELECT paths, timestamp FROM workspaces ORDER BY timestamp DESC
```

**Важно:** колонка называется `paths`, а не `absolute_path`.
Выбирается самый свежий workspace (по `timestamp`), который
не является self-indexing (отбрасывается, если путь совпадает с директорией
расширения или Zed).

**Наша база данных (LanceDB)** — векторный индекс кода, хранится ВНУТРИ проекта:

| Проект | Путь к индексу |
|---------|---------------|
| `MSCodeBase` | `D:\Project\MSCodeBase\.codebase_indices\lancedb_v2\` |
| `gemma_agent` | `D:\Project\gemma_agent\.codebase_indices\lancedb_v2\` |

Каждый проект имеет **свой изолированный индекс**. Когда расширение удаляется,
индекс остаётся в проекте. Когда проект удаляется — индекс теряется.

**Что ещё хранится в `.codebase_indices/`:** (внутри проекта)

| Директория | Назначение |
|-----------|---------|
| `lancedb_v2/` | Векторная БД LanceDB (индекс кода: чанки + эмбеддинги) |
| `branches/` | Git-ветки: изолированные индексы по веткам |
| `commit_memory/` | История коммитов и семантический анализ |
| `intelligence/` | Память проекта (ADR, known_issues, tech_debt) |

**Логи** (после v2.4.6): централизованы в директории расширения, НЕ в проекте:
```
%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\
```

**База данных Zed** (мы только читаем):
```
%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite
```

**Фильтрация self-indexing:** пути, совпадающие с `ext_root`, `Zed install dir`,
или системными директориями, отбрасываются.

**Multi-window:** при нескольких открытых окнах выбирается проект с наивысшим
score (2 = есть `.git`, 1 = нет `.git`), затем по самому свежему `updated_at`.

### Шаг 2: LSP Bridge — почему он может быть пуст

```
🌉 BRIDGE: НЕТ JSON-ФАЙЛОВ — LSP НЕ ЗАПИСАЛ project_root!
  Причины:
  1. Restricted Mode (не нажали "Trust and Continue")
  2. LSP падает при запуске (проверьте: intel_get_runtime_status)
  3. Файлы Python не открыты — LSP запускается ТОЛЬКО когда
     в редакторе открыт .py/.rs/... файл
```

---

## 📁 CWD = откуда был запущен Zed

**Важно:** CWD (рабочая директория) MCP-процесса наследуется от самого Zed.
На Windows `current_dir` в `settings.json` не резолвит `$ZED_WORKTREE_ROOT`,
поэтому CWD MCP-сервера = CWD процесса Zed.

Если Zed был запущен из:
- `cmd` или `powershell` → CWD будет папка, из которой запустили
- Ярлык / меню Пуск → CWD обычно директория с `zed.exe`
- `D:\AI\Zed` (как у вас) → CWD = `D:\AI\Zed`

---

## 🔒 Дополнительные механизмы Zed

### Dynamic Sandbox

Zed запускает MCP-серверы с ограниченными правами Windows. Если процесс
требует повышенных привилегий (Win32 API, защищённые системные папки),
ОС вернёт `Access Denied`.

**Решение:** Весь индекс хранится внутри `.codebase_indices/` в корне проекта —
процесс всегда имеет права на запись туда.

### Таймаут инициализации LSP (~10-15 секунд)

Если `lsp_main.py` не отвечает на `initialize` в течение 10-15 секунд, Zed
убивает LSP-процесс и НЕ БУДЕТ ПЫТАТЬСЯ ПЕРЕЗАПУСТИТЬ его до перезагрузки окна.

**Решение:** LSP должен возвращать `READY` мгновенно (< 2 секунд).
Тяжёлая работа выносится в фоновый поток.

### Чувствительность File Watcher

Zed блокирует открытые файлы эксклюзивной блокировкой. Если сторонний процесс
(индексатор, сборщик телеметрии) слишком агрессивно изменяет файлы в корне
рабочей области, Zed может временно заморозить свои вотчеры.

**Решение:** Кеширование соединений. Индексируйте файлы строго в `.codebase_indices/`.

### Нормализация UNC-путей Windows

Пути Windows могут иметь префикс `\\?\` (UNC). При сравнении путей
`D:\Project` и `\\?\D:\Project` считаются РАЗНЫМИ строками, но
они указывают на одну и ту же директорию.

**Решение:** Всегда используйте `Path(p).resolve()` при сравнении путей.
Это удаляет UNC-префиксы.

---

## 📋 Чек-лист настройки на новом ПК

1. ✅ Установите расширение через `install.py`
2. ✅ Откройте ЛЮБОЙ `.py` файл в проекте
3. ✅ Нажмите "Trust and Continue" при появлении диалога
4. ✅ Отметьте "Trust all projects in ..."
5. ✅ Проверьте `intel_get_runtime_status` — project_path должен быть
   путём к проекту, а НЕ к `ext_root`
6. Если `project_path` показывает ext_root — откройте файл и проверьте шаг 3
7. ✅ Запустите `intel_get_telemetry` — убедитесь, что данные собираются

---

## 📊 Поиск неисправностей

| Симптом | Смотреть | Команда |
|---------|---------|---------|
| MCP не знает проект | Логи: `resolve_project_root: fallback to ext_root` | `intel_get_runtime_status` |
| LSP не запускается | Логи: `BRIDGE: NO JSON FILES` | См. раздел "LSP не запускается в Zed 1.9.0" ниже |
| Индекс пуст | Статус: 0 chunks | `get_index_status` |
| Инструменты не готовы | Статус: UNINITIALIZED | Откройте файл в проекте |
| База данных заблокирована | Логи: `database is locked` | Закройте другие окна с этим проектом |

---

## 🚫 LSP не запускается в Zed 1.9.0 (WONTFIX)

**Статус:** ⚠️ Известное ограничение Zed 1.9.0 на Windows. Полный отчёт
с цитатами исходного кода: [../en/investigations/LSP_WONTFIX.md](../en/investigations/LSP_WONTFIX.md).

### Что не работает

LSP-сервер `mscodebase-lsp` (Python, `src/lsp_main.py`, на базе pygls) **не может
быть зарегистрирован** через `settings.json`. Независимо от того, что
мы пишем в `lsp.<id>.binary.path` или `languages.<lang>.language_servers`,
Zed не может найти адаптер с именем `mscodebase-lsp` в своём `LanguageRegistry`
и падает в `lsp_store.rs:start_language_server` с паникой
`expect("To find LSP adapter")`.

### Настоящая причина (из исходного кода Zed)

Из `crates/project/src/lsp_store.rs`:

```rust
let adapter = self.languages
    .lsp_adapters(language_name)
    .into_iter()
    .find(|adapter| adapter.name() == disposition.server_name)
    .expect("To find LSP adapter");
```

`lsp_adapters(name)` возвращает адаптеры только из:
1. **Встроенных языков** — `crates/languages/src/*.rs` (Python, Rust, Go)
   с жёстко заданными LSP-адаптерами.
2. **Загруженных WASM-расширений** — `extension.toml` + скомпилированный
   `extension.wasm` с `impl zed::Extension::language_server_command`.

`lsp.<id>.binary.path` в `settings.json` — это **переопределение пути** для уже
зарегистрированного адаптера, а не регистрация нового. **Это сделано намеренно, а не баг.**

### Что это значит для MSCodeBase

- **LSP-возможности в редакторе (inlay-hints, code-actions, автодополнение через
  mscodebase-lsp) невозможны на Zed 1.9.0 Windows.**
- **Вся семантика и поиск продолжают работать через MCP** — 50 инструментов,
  фильтрация по `layer`, многогранулярный поиск через
  `get_chunks_by_parent_id()`, телеметрия, ETAPredictor. Этого достаточно
  для 95% сценариев ассистента кода.
- **LSP bridge (project_root от LSP)** остаётся пустым, но `resolve_project_root()`
  компенсирует это через SQLite fallback.

### Почему в settings.json появляется ошибка Serde

Из `crates/settings_content/src/language.rs`:

```rust
#[schemars(range(min = 1, max = 128))]
pub tab_size: Option<NonZeroU32>,
```

Ошибка `expected a nonzero u32` — это **не про `language_servers`**, а про
`tab_size` (или другое поле с `NonZeroU32`) в той же структуре. Парсер
с `with_failible_options` сбрасывает это поле в `None` и показывает
предупреждение `Invalid user settings file` в UI. **LSP падает не из-за этого — он
даже не пытается запуститься, потому что имя адаптера отсутствует в реестре.**

### Что делать

#### Сейчас (релиз v2.4.4+)

1. **Не регистрируйте `mscodebase-lsp` в `settings.json`** — это создаёт
   ложные ошибки в UI и не даёт ничего полезного.
2. **Используйте MCP** для всех операций — он не зависит от LSP.
3. **Проверяйте состояние LSP** через `scripts/check_lsp_health.py` —
   скрипт напишет понятный отчёт "LSP not registered / not starting"
   вместо неинформативных ошибок Serde.

#### Будущее (v3.0+)

- **Напишите Rust-обёртку** (WASM через `wasm32-wasip2`) с
  `impl zed::Extension::language_server_command`, которая вызывает
  `python -m src.lsp_main`. Установка через `zed: install dev extension`.
  Это единственный способ заставить LSP работать в Zed.
- **Или замените `pyright`** через `lsp.pyright.binary.path` — минимальные
  усилия, но наш LSP будет маскироваться под чужой. Работает для
  сценариев, где важна подсветка в редакторе, а не уникальность адаптера.
