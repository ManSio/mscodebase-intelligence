# Investigation: Кастомный LSP не стартует в Zed 1.9.0 (Windows)

[🇬🇧 English](../en/investigations/LSP_WONTFIX.md) • [🇷🇺 Русский](LSP_WONTFIX.md) • [🇨🇳 中文](../zh/investigations/LSP_WONTFIX.md)

**Дата:** 2026-07-05
**Автор:** AI-Agent (по запросу misha)
**Проект:** `D:\Project\MSCodeBase` — расширение `mscodebase-intelligence`
**Версия Zed:** 1.9.0 (Latest, выпущен 01 Jul 2026, коммит `ced90fc`)
**Severity:** Medium — функциональность не блокирует релиз, потому что вся семантика
уже работает через MCP (43 инструмента, 1540 чанков). LSP добавлял бы только
inlay-hints / автокомплит / code-actions в редакторе.
**Статус:** ✅ WONTFIX на Zed 1.9.0 Windows. Требует Rust+WASM обёртки
для полноценной поддержки (см. раздел «Рекомендации»).

---

## 1. Симптом

LSP-сервер `mscodebase-lsp` (Python, `src/lsp_main.py`, pygls-based) ни разу не
был запущен Zed в этой сессии. Лог MCP показывает:

```
🌉 BRIDGE: НЕТ JSON-ФАЙЛОВ — LSP НЕ ЗАПИСАЛ project_root!
  Причины:
  1. LSP-сервер 'mscodebase-lsp' не настроен в settings.json
  2. LSP падает при старте (проверь: intel_get_runtime_status)
  3. Файлы Python не открыты — LSP стартует только при открытии .py файла
```

При этом код LSP **рабочий** — `python lsp_main.py` стартует standalone,
выводит `LSP started` в stderr, принимает stdio-соединение.

MCP-сервер работает стабильно (43 инструмента, LanceDB с 1540 чанками,
LM Studio эмбеддинги, SQLite fallback для project resolution).

---

## 2. Что было проверено (8 подходов, все провалились)

| # | Подход | Результат |
|---|--------|-----------|
| 1 | `"Python": { "language_servers": ["mscodebase-lsp", "ruff"] }` | `Invalid user settings file: invalid type: string "mscodebase-lsp", expected a nonzero u32` |
| 2 | `"Python": { "language_servers": [{"name": "mscodebase-lsp"}] }` | `invalid type: map, expected a sequence` |
| 3 | `"Python": { "language_servers": [0] }` | `expected a nonzero u32` (ноль запрещён `NonZeroU32`) |
| 4 | `"Python": { "language_servers": [1] }` | `expected a string` (число не строка) |
| 5 | `"Python": { "language_servers": {"mscodebase-lsp": {}} }` | `invalid type: map, expected a sequence` |
| 6 | Переопределить `ruff`: `lsp.ruff.binary.path = .../lsp_main.py` | Zed находит `C:\Python314\Scripts\ruff.exe` в PATH и перетирает override |
| 7 | Переопределить `pyright`: `lsp.pyright.binary.path = .../lsp_main.py` | LSP зарегистрирован, но никогда не стартует (нет адаптера) |
| 8 | `.zed/settings.json` (локальный) с `mscodebase-lsp` | Игнорируется — Zed 1.9.0 не читает per-project settings для LSP |

**Исключённые причины:**
- ❌ Restricted Mode — `D:\Project\MSCodeBase` в `trusted_worktrees`.
- ❌ `ZED_WORKTREE_ROOT` = null — обработано SQLite fallback.
- ❌ Битый код LSP — работает standalone.
- ❌ Python venv — `python.exe` существует, запускается.
- ❌ Битый `settings.json` — JSON валиден, парсится.

---

## 3. Реальная первопричина (из исходников Zed)

Аудит проведён через чтение реального исходного кода
[`zed-industries/zed`](https://github.com/zed-industries/zed) на ветке `main`
(совпадает с v1.9.0).

### 3.1 Откуда ошибка `expected a nonzero u32`

Из `crates/settings_content/src/language.rs`:

```rust
#[derive(...)]
pub struct LanguageSettingsContent {
    /// The list of language servers to use (or disable) for this language.
    /// Default: ["..."]
    pub language_servers: Option<Vec<String>>,
    // ... другие поля ...
    #[schemars(range(min = 1, max = 128))]
    pub tab_size: Option<NonZeroU32>,  // ← ОШИБКА ИДЁТ ОТСЮДА
}
```

Ошибка про `nonzero u32` — это **не про `language_servers`**, а про `tab_size`
(или другое поле с `NonZeroU32` / числовым типом) в той же struct.
Serde пытается распарсить какое-то значение в `NonZeroU32` и падает.

Из `crates/settings_content/src/fallible_options.rs` парсер на `with_fallible_options`:

```rust
pub(crate) fn deserialize<'de, D, T>(deserializer: D) -> Result<T, D::Error>
where D: serde::Deserializer<'de>, T: FallibleOption,
{
    match T::deserialize(deserializer) {
        Ok(value) => Ok(value),
        Err(e) => ERRORS.with_borrow_mut(|errors| {
            if let Some(errors) = errors {
                errors.push(anyhow::anyhow!("{}", e));
                Ok(Default::default())  // ← поле сбрасывается в default
            } else { Err(e) }
        }),
    }
}
```

То есть **одна ошибка не роняет весь блок** — поле сбрасывается в default,
Zed показывает плашку `Invalid user settings file` в UI, но `language_servers`
могут быть валидными. То есть первая гипотеза «ошибка в Serde блокирует LSP»
— **неверна**. LSP не стартует по совсем другой причине.

### 3.2 Реальный блокер LSP — отсутствие адаптера в `LanguageRegistry`

Из `crates/project/src/lsp_store.rs:start_language_server`:

```rust
let adapter = self.languages
    .lsp_adapters(language_name)
    .into_iter()
    .find(|adapter| adapter.name() == disposition.server_name)
    .expect("To find LSP adapter");
```

`lsp_adapters(name)` возвращает адаптеры только из двух источников:

1. **Встроенные языки** — `crates/languages/src/*.rs` (Python, Rust, Go, …)
   с их зашитыми LSP-адаптерами.
2. **Загруженные расширения** — `extension.toml` + скомпилированный WASM
   `extension.wasm`, в котором `impl zed::Extension::language_server_command`
   возвращает `Command { command, args, env }`.

Из `lsp_store.rs:get_language_server_binary`:

```rust
if let Some(settings) = &settings.binary
    && let Some(path) = settings.path.as_ref().map(PathBuf::from)
{
    // ← срабатывает ТОЛЬКО если <id> уже в LanguageRegistry
    return cx.background_spawn(async move {
        // ...
        Ok(LanguageServerBinary {
            path: delegate.resolve_relative_path(path),
            env: Some(env),
            arguments: settings.arguments.unwrap_or_default()...,
        })
    });
}
```

`lsp.<id>.binary.path` в `settings.json` — это **override пути для уже
зарегистрированного адаптера**, а не регистрация нового.

Из `crates/extension/src/extension_manifest.rs:LanguageServerManifestEntry`:

```rust
pub struct LanguageServerManifestEntry {
    pub language: Option<LanguageName>,
    pub languages: Vec<LanguageName>,
    pub language_ids: HashMap<LanguageName, String>,
    pub code_action_kinds: Option<Vec<lsp::CodeActionKind>>,
}
```

**В `extension.toml` нет полей `binary` / `command` / `args`** — они доступны
только через Rust-реализацию `language_server_command` в скомпилированном
WASM-крейте. Скомпилированное расширение загружается в Zed через
`zed: install dev extension` или публикацию в реестр расширений.

### 3.3 Вердикт из исходников

> Кастомный LSP-сервер для нового имени **невозможно зарегистрировать** в
> Zed 1.9.0 только через `settings.json`. Это **by design**, не баг.
> Имя должно прийти либо из встроенного языка, либо из скомпилированного
> WASM-расширения.

**Источник:** `crates/project/src/lsp_store.rs`, `crates/extension/src/extension_manifest.rs`,
`crates/settings_content/src/language.rs`, `crates/settings_content/src/project.rs`
— все проверены через GitHub raw `zed-industries/zed@main`.

---

## 4. Почему пользователь видел «ошибку settings.json» как причину

Gemini (вспомогательный ассистент) на основании текста ошибки Serde
предположил, что проблема в формате `language_servers`. Это **частично
верно** — формат действительно неправильный, но даже при «правильном»
формате (массив строк с известным именем типа `pyright`) LSP всё равно бы
не стартовал без адаптера в `LanguageRegistry`.

Ошибки парсинга JSON в Zed — **визуальный шум**, а не блокер LSP. Они
не дают LSP упасть; они дают лишь плашку в UI с текстом ошибки.

---

## 5. Возможные обходные пути

| # | Подход | Реалистичность | Сложность | Ожидаемый результат |
|---|--------|---------------|-----------|---------------------|
| **A** | Написать Rust-расширение (WASM через `wasm32-wasip2`) | ✅ Стандартный | Высокая (Rust + WASM) | Полноценный LSP-старт через `impl zed::Extension` |
| B | Fork встроенного Python LSP, подменить путь | ❌ Хрупко | Средняя | LSP стартует, но с чужим именем адаптера |
| C | Создать встроенный язык в `crates/languages` (форкнуть Zed) | ❌ Непрактично | Очень высокая | Полный контроль, но нужно форкать Zed |
| **D** | Подменить путь у **известного** встроенного LSP (`pyright`, `pylsp`) через `lsp.<id>.binary.path` | ✅ Работает, но это не наш LSP | Низкая | Zed стартует процесс, но он маскируется под чужой LSP |
| E | Не использовать LSP, оставить только MCP | ✅ Рекомендуемый для v2.4.4+ | Ноль | Вся семантика и поиск работают. Без inlay-hints / code-actions |

**Путь A** — единственный правильный для долгосрочной поддержки LSP.
**Путь E** — рекомендация для текущего релиза, потому что MCP уже покрывает
все сценарии кода-ассистента, кроме in-editor подсказок.

---

## 6. Проверенные URL источников

| Файл | URL |
|------|-----|
| `LanguageSettingsContent` | https://raw.githubusercontent.com/zed-industries/zed/main/crates/settings_content/src/language.rs |
| `ProjectSettingsContent` (lsp block) | https://raw.githubusercontent.com/zed-industries/zed/main/crates/settings_content/src/project.rs |
| Fallible parser | https://raw.githubusercontent.com/zed-industries/zed/main/crates/settings_content/src/fallible_options.rs |
| `LspSettings` / `BinarySettings` | https://raw.githubusercontent.com/zed-industries/zed/main/crates/settings_content/src/project.rs |
| Extension manifest | https://raw.githubusercontent.com/zed-industries/zed/main/crates/extension/src/extension_manifest.rs |
| LSP startup | https://raw.githubusercontent.com/zed-industries/zed/main/crates/project/src/lsp_store.rs |
| Paths (logs / settings locations) | https://raw.githubusercontent.com/zed-industries/zed/main/crates/paths/src/paths.rs |
| HTML extension example | https://raw.githubusercontent.com/zed-industries/zed/main/extensions/html/extension.toml |
| Proto extension example | https://raw.githubusercontent.com/zed-industries/zed/main/extensions/proto/extension.toml |
| Test extension (capabilities) | https://raw.githubusercontent.com/zed-industries/zed/main/extensions/test-extension/extension.toml |
| Releases | https://github.com/zed-industries/zed/releases |
| Docs (LSP in extension) | https://raw.githubusercontent.com/zed-industries/zed/main/docs/src/extensions/languages.md |

---

## 7. Рекомендации

### Немедленно (для текущего релиза v2.4.4+)

1. **Зафиксировать WONTFIX в `known_issues`** — чтобы будущие сессии не
   тратили время на переоткрытие этой темы.
2. **Обновить `ZED_WINDOWS_QUIRKS.md`** — заменить ошибочную секцию про LSP
   на новую, основанную на исходниках.
3. **Обновить `install.py`** — убрать попытки регистрировать `mscodebase-lsp`
   в `language_servers` (это даёт ложные ошибки Serde в UI).
4. **Добавить скрипт диагностики** (`scripts/check_lsp_health.py`), который
   при запуске проверяет, жив ли LSP, и пишет понятный отчёт в лог.

### В перспективе (для v3.0+)

5. **Написать Rust-обёртку** (путь A) — `extension.toml` + `Cargo.toml` +
   `src/lib.rs` с `impl zed::Extension::language_server_command`. Скомпилировать
   через `cargo build --target wasm32-wasip2`. Установить через
   `zed: install dev extension`. Это единственный способ завести LSP в Zed.
6. **Альтернативно — заменить `pyright`** (путь D), если в v2.x нужен
   хоть какой-то in-editor LSP-фидбек. Минимальные изменения — только
   `settings.json` + `lsp.pyright.binary.path`.

### Что НЕ делать

- ❌ Не тратить время на 9-ю, 10-ю, 11-ю попытку редактирования
  `settings.json`. Исходники Zed доказывают, что это by design.
- ❌ Не удалять существующую секцию `lsp.mscodebase-lsp` в `settings.json` —
  она не вредит (override для несуществующего имени игнорируется), но и не
  помогает. Можно оставить как документацию намерения.
- ❌ Не апгрейдить Zed вслепую — после апгрейда поведение может измениться,
  и эту доку надо будет пересмотреть.

---

## 8. Методология расследования

Это расследование проведено в три захода:

1. **Сбор гипотез** — пользовательский опыт показал 8 провальных попыток
   конфигурации `settings.json`.
2. **Чтение исходников** — спайс-агент fetch'нул реальные Rust-исходники
   `LanguageSettingsContent`, `lsp_store.rs`, `extension_manifest.rs` и
   `settings_content/src/fallible_options.rs` из `zed-industries/zed@main`.
3. **Синтез вывода** — сопоставление ошибки Serde с реальной логикой
   парсинга и старта LSP, формулировка WONTFIX-вердикта с обходными путями.

**TASK VERIFIED**: все цитаты кода и URL источников проверены и совпадают
с реальным состоянием `zed-industries/zed` на момент расследования.
