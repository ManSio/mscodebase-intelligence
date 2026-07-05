# Zed на Windows: Подводные камни и архитектурные решения

[🇬🇧 English](ZED_WINDOWS_QUIRKS.en.md) • [🇷🇺 Русский](ZED_WINDOWS_QUIRKS.md) • [🇨🇳 中文](ZED_WINDOWS_QUIRKS.zh.md)


> Версия: 1.1 (2026-07-05) — обновлена секция «LSP не стартует»
> Актуально для: MSCodeBase Intelligence v2.4.4+
> Подробный отчёт: `docs/investigations/2026-07-05-lsp-zed-1.9.0.md`

## ⚠️ Критически важно: Restricted Mode (Безопасный режим)

При открытии **нового** проекта в Zed (который ещё не был открыт ранее) редактор
показывает диалог безопасности **"Restricted Mode"**. Это НЕ баг — это встроенная
защита Zed.

### Что блокирует Restricted Mode

| Механизм | Статус | Последствие |
|----------|--------|-------------|
| Языковые серверы (LSP) | 🔴 Полностью заблокированы | `lsp_main.py` не запускается → мост не пишет bridge-файл |
| Локальные `settings.json` (`.zed/settings.json`) | 🔴 Игнорируются | `current_dir` и `env` из настроек не применяются |
| MCP-серверы | 🔴 Не устанавливаются | Контекстные серверы не регистрируются |

### Как решить

1. **Нажми "Trust and Continue"** (или `Enter`)
2. **Поставь галочку "Trust all projects in D:\Project"** — чтобы больше
   не видеть это окно для всей рабочей директории
3. **Без этой галочки** каждый новый проект из `D:\Project` будет снова
   показывать диалог

### Почему MSCodeBase должен об этом знать

Если проект в Restricted Mode:
- `LSP Bridge` не пишет JSON-файлы → `resolve_project_root()` не получает
  проект от LSP
- `SQLite DB fallback` ВСЁ РАВНО работает (читает `workspaces` из базы Zed)
- Но `settings.json` игнорируется → `current_dir` не меняется → CWD
  всегда указывает на директорию установки Zed (например, `D:\AI\Zed`
  или `C:\Program Files\Zed\`)

---

## 🪟 Специфика Windows: ZED_WORKTREE_ROOT

**Статус:** ⚠️ Всегда `<unset>` на Windows (Zed bug #36019)

Переменная окружения `ZED_WORKTREE_ROOT` НЕ устанавливается на Windows.
Это известный баг Zed, закрытый без исправления.

### Что это означает

- В `settings.json` для `context_servers` нельзя использовать `$ZED_WORKTREE_ROOT`
  в `current_dir` или `env`
- Любые попытки полагаться на эту переменную приведут к `None`
- На Linux/macOS эта переменная устанавливается корректно

### Решение в MSCodeBase

Используется цепочка fallback (см. ниже), которая обходится без
`ZED_WORKTREE_ROOT`:

1. ~~`LSP Bridge` — LSP получает `root_uri` через LSP-протокол~~
   **НЕ РАБОТАЕТ на Windows** — LSP-сервер не стартует (см.
   `docs/investigations/2026-07-05-lsp-zed-1.9.0.md`).
2. `SQLite DB` — читает `workspaces` из базы данных Zed (основной рабочий путь)
3. `PROJECT_PATH` из `.env` — ручное указание проекта

---

## 🔧 Цепочка resolve_project_root (приоритет)

MCP-сервер определяет текущий проект в следующем порядке:

```
[Запрос от инструмента]
    │
    ▼
1. Передан явный project_root? ──(Да)──> Используем его
    │ (Нет)
    ▼
2. LSP Bridge файл существует? ──(НЕТ на Windows — LSP не стартует)──> Шаг 3
3. SQLite база Zed доступна? ──(Да)──> Читаем workspaces,
    │                                 фильтруем self-indexing,
    │                                 сортируем по .git + timestamp
    │ (Нет / база заблокирована)
    ▼
4. PROJECT_PATH из .env? ──(Да)──> Используем его
    │ (Нет)
    ▼
5. CWD (всегда директория установки Zed, напр. `D:\AI\Zed`) ──> self-indexing guard
    │                       ──> fallback на ext_root
    ▼
                ⚠️ Режим самодиагностики
```

### Multi-window: MCP не различает окна

**Проблема:** Все MCP-инструменты (кроме `intel_*`) работают с **одним проектом** —
тем, который `resolve_project_root()` выбрал как default. Если у вас открыто
несколько окон с разными проектами, `get_index_status()` покажет индекс default-проекта,
а не того окна, где вы сейчас.

**Почему:** MCP-сервер — один процесс на все окна Zed.
Он не знает, из какого окна пришёл запрос.
На macOS/Linux эту проблему решает `ZED_WORKTREE_ROOT`,
на Windows он всегда `<unset>`.

**Как обойти:**
- Для `intel_*` инструментов: они сами ищут первый non-self-indexing проект
- Для `get_index_status`: закрыть лишние окна, оставить только нужный проект
- Для `search_code`: передать явный `project_root` (если инструмент поддерживает)

---

### Шаг 3: SQLite DB (база Zed) — как это работает

**Это НЕ наша база.** Это база данных самого Zed, в которой хранятся
открытые проекты (workspaces). Мы её только читаем (read-only).
```
%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite
```

Читается таблица `workspaces`:
```sql
SELECT paths, timestamp FROM workspaces ORDER BY timestamp DESC
```

**Важно:** столбец называется `paths`, а не `absolute_path`.
Выбирается самый свежий workspace (по `timestamp`), который не является
self-indexing (reject, если path совпадает с директорией расширения или Zed).

**Наша база (LanceDB)** — векторный индекс кода, хранится ВНУТРИ проекта:

| Проект | Путь к индексу |
|--------|---------------|
| `MSCodeBase` | `D:\Project\MSCodeBase\.codebase_indices\lancedb_v2\` |
| `gemma_agent` | `D:\Project\gemma_agent\.codebase_indices\lancedb_v2\` |

Каждый проект имеет **свой изолированный индекс**. При удалении расширения
индекс остаётся в проекте. При удалении проекта — индекс теряется.

**Что ещё хранится в `.codebase_indices/`:** (внутри проекта)

| Директория | Назначение |
|-----------|-----------|
| `lancedb_v2/` | Векторная БД LanceDB (индекс кода: чанки + эмбеддинги) |
| `branches/` | Git-ветки: изолированные индексы per-branch |
| `commit_memory/` | История коммитов и семантический анализ |
| `intelligence/` | Память проекта (ADR, known_issues, tech_debt) |

**Логи** (после v2.4.6): централизованы в директории расширения, НЕ в проекте:
```
%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\
```

**Сама база Zed** (мы только читаем):
```
%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite
```

**Фильтрация self-indexing:** пути, совпадающие с `ext_root`, `Zed install dir`
или системными директориями, отбрасываются.

**Multi-window:** при нескольких открытых окнах выбирается проект с наивысшим
score (2 = есть `.git`, 1 = нет `.git`), затем по свежести `updated_at`.

### Шаг 2: LSP Bridge — почему может быть пуст

```
🌉 BRIDGE: НЕТ JSON-ФАЙЛОВ — LSP НЕ ЗАПИСАЛ project_root!
  Причины:
  1. Restricted Mode (не нажали "Trust and Continue")
  2. LSP падает при старте (проверь: intel_get_runtime_status)
  3. Файлы Python не открыты — LSP стартует ТОЛЬКО при
     открытии .py/.rs/... файла в редакторе
```

---

## 📁 CWD = откуда запущен Zed

**Важно:** CWD (рабочая директория) MCP-процесса наследуется от самого Zed.
На Windows `current_dir` в `settings.json` не резолвит `$ZED_WORKTREE_ROOT`,
поэтому CWD MCP-сервера = CWD процесса Zed.

Если Zed запущен из:
- `cmd` или `powershell` → CWD будет папка, откуда запустили
- Ярлыка / Пуск → CWD обычно директория с `zed.exe`
- `D:\AI\Zed` (как у тебя) → CWD = `D:\AI\Zed`

---

## 🔒 Дополнительные механизмы Zed

### Dynamic Sandbox

Zed запускает MCP-серверы с ограниченными правами Windows. Если процессу
потребуются повышенные привилегии (Win32 API, защищённые системные папки),
ОС выдаст `Access Denied`.

**Решение:** Весь индекс хранится внутри `.codebase_indices/` в корне проекта —
там у процесса всегда есть права на запись.

### LSP Init Timeout (~10-15 секунд)

Если `lsp_main.py` не отвечает на `initialize` быстрее 10-15 секунд, Zed
убивает LSP-процесс и БОЛЬШЕ НЕ ПЫТАЕТСЯ ЕГО ПЕРЕЗАПУСТИТЬ до перезагрузки окна.

**Решение:** LSP должен возвращать `READY` мгновенно (< 2 секунд).
Тяжёлую работу — в фоновый поток.

### File Watcher Sensitivity

Zed блокирует открытые файлы эксклюзивным локом. Если сторонний процесс
(индексатор, сборщик телеметрии) меняет файлы в корне воркспейса слишком
активно, Zed может временно заморозить вотчеры.

**Решение:** Кэширование соединений. Файлы индекса строго в `.codebase_indices/`.

### Windows UNC Path Normalization

Пути на Windows могут иметь префикс `\\?\` (UNC). При сравнении путей
`D:\Project` и `\\?\D:\Project` считаются РАЗНЫМИ строками, но
указывают на одну директорию.

**Решение:** Всегда использовать `Path(p).resolve()` при сравнении путей.
Это сбрасывает UNC-префиксы.

---

## 📋 Чек-лист при установке на новом ПК

1. ✅ Установить расширение через `install.py`
2. ✅ Открыть ЛЮБОЙ `.py` файл в проекте
3. ✅ Нажать "Trust and Continue" при появлении диалога
4. ✅ Поставить галочку "Trust all projects in ..."
5. ✅ Проверить `intel_get_runtime_status` — project_path должен быть
   путём к проекту, а НЕ к `ext_root`
6. Если `project_path` показывает ext_root — открыть файл и проверить шаг 3
7. ✅ Запустить `intel_get_telemetry` — проверить, что данные собираются

---

## 📊 Диагностика проблем

| Симптом | Смотреть | Команда |
|---------|----------|---------|
| MCP не знает проект | Логи: `resolve_project_root: fallback to ext_root` | `intel_get_runtime_status` |
| LSP не запускается | Логи: `BRIDGE: НЕТ JSON-ФАЙЛОВ` | См. секцию «LSP не стартует в Zed 1.9.0» ниже |
| Индекс пуст | Статус: 0 чанков | `get_index_status` |
| Инструменты не готовы | Статус: UNINITIALIZED | Открыть файл в проекте |
| База заблокирована | Логи: `database is locked` | Закрыть другие окна с проектом |

---

## 🚫 LSP не стартует в Zed 1.9.0 (WONTFIX)

**Статус:** ⚠️ Известное ограничение Zed 1.9.0 на Windows. Подробный отчёт
с цитатами исходного кода: `docs/investigations/2026-07-05-lsp-zed-1.9.0.md`.

### Что не работает

LSP-сервер `mscodebase-lsp` (Python, `src/lsp_main.py`, pygls-based) **не
может быть зарегистрирован** через `settings.json`. Независимо от того,
что мы пишем в `lsp.<id>.binary.path` или `languages.<lang>.language_servers`,
Zed не находит адаптер с именем `mscodebase-lsp` в своём `LanguageRegistry`
и падает в `lsp_store.rs:start_language_server` с панико
`expect("To find LSP adapter")`.

### Реальная причина (из исходников Zed)

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
   с зашитыми LSP-адаптерами.
2. **Загруженных WASM-расширений** — `extension.toml` + скомпилированный
   `extension.wasm` с `impl zed::Extension::language_server_command`.

`lsp.<id>.binary.path` в `settings.json` — это **override пути** для уже
зарегистрированного адаптера, а не регистрация нового. **Это by design, не баг.**

### Что это значит для MSCodeBase

- **LSP-фичи в редакторе (inlay-hints, code-actions, автокомплит через
  mscodebase-lsp) на Zed 1.9.0 Windows невозможны.**
- **Вся семантика и поиск продолжают работать через MCP** — 43 инструмента,
  фильтрация по `layer`, multi-granularity retrieval через
  `get_chunks_by_parent_id()`, telemetry, ETAPredictor. Этого достаточно
  для 95% сценариев код-ассистента.
- **LSP-мост (project_root из LSP)** остаётся пустым, но `resolve_project_root()`
  это компенсирует через SQLite fallback.

### Почему в settings.json появляется ошибка Serde

Из `crates/settings_content/src/language.rs`:

```rust
#[schemars(range(min = 1, max = 128))]
pub tab_size: Option<NonZeroU32>,
```

Ошибка `expected a nonzero u32` — это **не про `language_servers`**, а про
`tab_size` (или другое поле с `NonZeroU32`) в той же struct. Парсер с
`with_fallible_options` сбрасывает это поле в `None` и показывает плашку
`Invalid user settings file` в UI. **LSP из-за этого не падает — он
вообще не пытается стартовать, потому что имени адаптера нет в реестре.**

### Что делать

#### Сейчас (релиз v2.4.4+)

1. **Не регистрировать `mscodebase-lsp` в `settings.json`** — это создаёт
   ложные ошибки в UI и не даёт ничего полезного.
2. **Использовать MCP** для всех операций — он не зависит от LSP.
3. **Проверять состояние LSP** через `scripts/check_lsp_health.py` —
   скрипт напишет понятный отчёт «LSP не зарегистрирован / не стартует»
   вместо неинформативных ошибок Serde.

#### В перспективе (v3.0+)

- **Написать Rust-обёртку** (WASM через `wasm32-wasip2`) с
  `impl zed::Extension::language_server_command`, которая вызывает
  `python -m src.lsp_main`. Установить через `zed: install dev extension`.
  Это единственный путь завести LSP в Zed.
- **Или подменить `pyright`** через `lsp.pyright.binary.path` — минимум
  усилий, но наш LSP будет маскироваться под чужой. Работает для
  сценариев, где важна in-editor подсветка, а не уникальность адаптера.
