# Universal MCP Engine — Детальный план реализации

> Компаньон к ТЗ «MSCodeBase Intelligence → Universal MCP Engine» (L1-656,
> черновик владельца, имя файла: MSCODEBASE_UNIVERSAL_TOR.md). EN-оригинал:
> `docs/research/UNIVERSAL_ENGINE_PLAN.md`.
> Составлен 2026-08-18. Каждое утверждение о текущем коде проверено чтением
> кода в этой сессии; внешние факты — живой загрузкой (URL inline);
> локальные эксперименты E-01/E-02 прогнаны в этой сессии (raw output ниже).

> **СТАТУС 2026-08-18 (поздно):** Фаза 0 + Фаза 1 выполнены на
> `feat/universal-engine` (коммиты 7232a6e2, cb8f671f, 55a2af41, e661861f,
> 7a8e703b, c9800368). Раунд аудита (находки исследовательского агента): гейт
> слоёв подключён в pre-commit (инсталлятор + переустановка) и CI (шаг ci.yml);
> CI-матрица ОС (ubuntu+windows) уже была; дрейф KNOWN_ISSUES «Фаза 0»
> исправлен (финальный дом хелперов); дедлайн platform_utils.get_zed_* → Фаза 3
> (DI-инъекция резолва проекта); создана experiments/universal-engine/;
> ТЗ-черновик (MSCODEBASE_UNIVERSAL_TOR.md) остаётся untracked в корне — файл
> владельца, решение о размещении (docs/ru/ по §0.6) за владельцем.

---

## 0. Исполнительные решения (вопросы владельца: строить с 0 vs миграция; новая папка vs на месте)

### D-1. МИГРИРУЕМ на месте. С нуля НЕ строим. Доказательства:

| Утверждение ТЗ | Проверено в репо (эта сессия) | Следствие |
|---|---|---|
| `src/mcp/server.py` = «импорты + регистрация» | Да — тонкий фасад, реэкспорты, `create_mcp_server()` только регистрирует | Извлечение транспорта низкорисково |
| DI-контейнер есть | `src/core/di_container.py` — `ServiceCollection` (add_singleton/resolve) | ToolPlugin `register(container)` имеет дом |
| Инструменты — классы с constructor injection | ABC `MCPTool` в `src/mcp/tools/base.py` (name/execute/resolve_indexer), 47 `tool_name=` в `tools/*.py` | Протокол плагинов = обвязка, не переписывание |
| `verify_action` существует | `VerifyActionTool` в `lifecycle_tools.py` + `ExecutionContract` в `src/core/execution_contract.py` | Action Receipt (§11) строится на существующем |
| `before_hash`/`after_hash` есть | `ChangeIntent` (execution_contract.py:96-117) уже пишет оба + `base_commit` + `ChangeIntentLedger` (JSONL в data_root) | Фундамент §11 готов на 80% |
| `ProjectIndexerRegistry` LRU(5) | `src/core/indexing/project_indexer_registry.py` | Переиспользуем для remote-кэша (рекомендация 2) |
| Rate limiter + circuit breaker | `src/core/rate_limiter.py` — `SlidingWindowRateLimiter` + `CircuitBreaker` | Переиспользуем для remote-гейта (ТЗ §3.2) |
| Windows-специфика в путях | `src/utils/paths.py` (`SafePathManager`, `to_win_long_path`) — импортируется db_manager, intelligence tools | Цель Фазы 0; уже в `utils/`, не в core |
| Zed-специфика конфига | `src/utils/zed_config.py` (patch_zed_settings и др.), `extension.toml`, `src/main.py` (Zed-first entrypoint с `--install-global`) | Цель Фазы 0 |
| Тесты | `pytest tests/` = 1300 (эта сессия); live-check `scripts/smoke_e2e.py` есть | Страховка для поведенчески-безопасного рефакторинга существует |

Ценность движка — 47 tool-классов + 18 intel-тулов + Indexer/Searcher/SymbolIndex +
IntelligenceLayer: полтора года протестированного кода. Сам ТЗ говорит, что core
не меняется — меняется только окружение. Переписывание выбросило бы страховку
без выгоды.

### D-2. Один репозиторий, одна фича-ветка, новые пакеты ВНУТРИ дерева — не параллельная папка проекта.

- **Фазы 0-1** (поведенчески-безопасный рефакторинг): на месте, в `D:\Project\MSCodeBase`.
- **Фазы 2+** (новые подсистемы): новые пакетные каталоги В ТОМ ЖЕ репозитории,
  за существующим деревом, подключение через DI, верификация существующим набором
  из 1300 тестов + `smoke_e2e.py` на каждом merge:
  - `src/sources/` (WorkspaceSource: local, git_url, upload)
  - `src/mcp/transport/` (stdio остаётся, добавляется streamable_http)
  - `src/plugins/` (протокол ToolPlugin, гейт, загрузчик)
  - `adapters/` (zed/, vscode/, claude_code/, cli/) — конфиг + тонкий клей, в основном не код
- **Эксперименты** — только в `experiments/universal-engine/` (throwaway-пробы;
  `experiments` уже исключён из автоколлекции pytest через `norecursedirs`).
- Работа на ветке `feat/universal-engine`; каждая фаза — PR в main (§0.-3: main
  защищён, только PR).

Обоснование: полная параллельная копия удваивает поддержку и осиротит тестовый
каркас; чистый рефакторинг «всё на месте» рискует теми самыми регрессиями, о
которых предупреждает ТЗ. Новые каталоги внутри дерева дают свойство
«строить-и-проверять в новом месте», которое просил владелец, без форка ядра.

### D-3. Взаимодействия со всех сторон (проблема «multi-», расширение ТЗ §9б)

| Ось | Сценарий | Владелец | Решение |
|---|---|---|---|
| Multi-window (один редактор, один проект) | 2 окна Zed → 2 stdio-процесса | `adapters/zed/` | Уже решено (PID-lock, port-ready dedup, CWD-first резолв). Остаётся в адаптере. |
| Multi-project (разные проекты) | Zed на репо A + VS Code на репо B, или 2 remote-workspace | **core** | `ProjectIndexerRegistry` (LRU(5)) поднимается из «Zed-триггера» в core-абстракцию. Он никогда не был Zed-специфичным — только его триггер. |
| Multi-client, один remote HTTP-сервер | 2 клиента стучатся в один workspace по HTTP+SSE | **core (новое)** | Shared read (реюз кэша индекса). Конкурентный write → workspace-level lock (обобщить PID-lock self-healing с процесса на workspace). Write в remote = read-only по умолчанию (рекомендация 3). |
| Multi-editor на одном проекте (локально) | Zed-агент + VS Code-агент правят одни файлы | **core** | DebounceBatch `notify_change` дедуп per client; сериализация записи LanceDB уже через `DatabaseLock`; кросс-процессную гонку индекса покрывают существующие lock+guard; проверить новым E-10. |
| Multi-OS | Windows dev + Linux CI + macOS | adapters | Фаза 0 переносит `SafePathManager`/`to_win_long_path` в `adapters/local_fs/windows.py` (POSIX no-op); CI-матрица гоняет тесты на ≥2 ОС с ПЕРВОГО PR Фазы 0 (ТЗ §9б-8). Python 3.10 EOL 2026-10 → матрица 3.11/3.12/3.14. |
| Плагины | сторонний код внутри нашего процесса | **core (новое)** | Trust-гейт + hash-pin + subprocess-изоляция (см. §5). |

---

## 1. Пораздельный план (зеркалит ТЗ 0-12)

### §0 Проблема — вердикт
Подтверждено по всем трём пунктам: связка с ОС (Windows-код paths.py импортируется
поперёк core), с редактором (extension.toml + zed_config.py + main.py Zed-first),
только локальный источник (нет URL-пути; `resolve_project_root` завязан на диск).
Трёхосевое разделение (§1) — правильная декомпозиция. Изменений нет.

### §1 Три оси — архитектура
Принять диаграмму как есть. Конкретные контракты:
- `WorkspaceSource` (Protocol) — новый `src/sources/`; потребляется фабрикой Indexer
  и `resolve_indexer_for_request` (base.py:100), чтобы тулы работали без изменений.
- `Transport` — `src/mcp/transport/`; 47 tool-классов его не касаются (проверено:
  они принимают только `ServiceCollection`).
- `Adapter` — `adapters/`; extension.toml/settings/install split по редакторам.

**Атака R-1 (перетекание осей):** тул тянет за пределы слоя (например,
`read_live_file` импортирует `platform_utils.get_zed_*` после рефакторинга).
Guard: тест границ слоёв — `grep -rn "get_zed\|to_win_long_path\|platform.system"
src/mcp/tools/` обязан быть пустым; добавить CI-гейт (паттерн
`scripts/check_tool_names.py`).

### §2 SOURCE LAYER — WorkspaceSource

#### 2.1 LocalFsSource
Обёртка над текущей нормализацией путей (paths.py) БЕЗ изменения поведения.
Windows-обработка путей переезжает в `adapters/local_fs/windows.py` (Фаза 0);
Linux/macOS = no-op. DoD: `pytest tests/` = 1300 без изменений; smoke_e2e проходит.

#### 2.2 GitUrlSource — исследовано + измерено (E-02)
Проверенное живое prior art: bloop (bare-clone-to-cache через gitoxide,
pull-or-reclone при сбое, per-repo shallow depth — архив 2025, ближайший аналог
нашего дизайна); Sourcegraph gitserver (schedule/queue, `gitMaxConcurrentClones`,
`gitMaxCodehostRequestsPerSecond`, границы поллинга 45с–8ч); searchcode.com
(server-side fetch, SSH/token auth для приватных репо, политика кэша не
опубликована); Bazel disk-cache GC (max-size + max-age + idle sweep — единственная
опубликованная реализация наших точных ручек эвикции). OWASP SSRF cheat sheet +
GitLab webhook hardening (DNS-rebinding, блок RFC1918/IMDS) — база безопасности.

Дизайн (каждый пункт имеет E-эксперимент или цитату):
1. **Scheme allowlist до того, как git увидит URL:** только `https`. Отклонять
   `ssh://`, `git://`, `file://`, scp-подобный `host:path`, userinfo/credentials в URL.
   *Измерено:* `git clone file://...` завершается 128 по умолчанию (git ≥2.38,
   CVE-2022-39253) — но мы НЕ полагаемся на это; отклоняем на этапе парсинга. (E-02d)
2. **Domain allowlist** (github.com, gitlab.com, bitbucket.org + настраиваемые
   self-hosted). Не денайлист (OWASP: денайлисты обходятся).
3. **Защита от DNS-rebinding:** резолв хоста → собрать ВСЕ A/AAAA → отклонить,
   если ЛЮБОЙ не-global (127/8, ::1, 0.0.0.0/8, RFC1918, link-local, multicast,
   <!-- stale-ignore -->
   IMDS 169.254.169.254, metadata-хосты). Перепроверять после редиректов
   (git smart-HTTP следует редиректам) — финальный хост считать недоверенным.
   <!-- stale-ignore -->
4. **Харденинг clone-процесса:** `-c protocol.file.allow=never -c protocol.ext.allow=never`,
   без `--recurse-submodules` по умолчанию (submodules = вектор произвольного
   клонирования, класс CVE-2022-39253; storage GitHub их тоже не рекурсирует).
5. **Лимиты (жёсткие, на уровне процесса):** timeout клона (дефолт 120с),
   пост-clone проверка размера (`du`, дефолт ~500MB) + лимит числа файлов
   (~200k) → abort + evict; per-host лимит конкуренции (прецедент Sourcegraph).
   Одна ссылка на 50GB-монорепо не должна положить сервер (ТЗ §9б-4).
6. **Форма клона:** `--depth=1 --single-branch` по умолчанию (быстрейший tip;
   re-clone при крупном дрейфе вместо вечного fetch — избегаем ловушки
   «shallow-fetch дорог»); `--filter=blob:none` как опция, когда нужен
   history-walkable индекс. *Измерено (E-02b):* requests full clone 19MB vs
   blobless 7.7MB, 2.9s, в дереве 130 файлов. Сервер может отказать в фильтре →
   пост-clone лимит размера держать в любом случае.
7. **Кэш:** clone в `<data_root>/repos/<hash8>/`; эвикция LRU(5) + TTL 24ч
   (рекомендация 2 — то же число, что уже проверено для multi-window),
   size-bound + idle sweep (паттерн Bazel disk-cache GC); никогда не эвиктить
   источник с идущим индекс-джобом; эвикция шардов + манифеста атомарно.
8. **Fingerprint / cold-start:** использовать собственное Merkle-дерево git —
   `git rev-parse HEAD` + `git ls-tree -r HEAD` = манифест (path → blob-oid) почти
   бесплатно. *Измерено (E-02):* 79ms на всё дерево, ноль повторного хэширования.
   Хранить `{last_indexed_oid, manifest}`; при повторной проверке diff манифестов
   → re-embed только изменённых путей (это реализует идею simhash cold-start из
   DEV_EXP §11 — корректно: точный Merkle для skip-логики; simhash/ssdeep ТОЛЬКО
   для near-duplicate решений вроде детекции форков, никогда для skip-логики).
9. **Инкрементальный пайплайн (TOCTOU-safe):** fetch → пиним OID дерева → diff
   против сохранённого манифеста → embed изменённого → обновить манифест+OID
   ПОСЛЕДНИМ. Работа против пина OID (прецедент Bazel
   `--experimental_guard_against_concurrent_changes`). При рассинхроне/повреждении
   → полный re-embed; при сбое pull → re-clone (паттерн bloop).
10. **INCONCLUSIVE, не crash:** несуществующий репо / приватный без токена /
    timeout / превышение размера → вердикт `INCONCLUSIVE` с reason, никогда не
    hard crash и не тихий успех. *Измерено (E-02c):* `git clone` несуществующего
    URL выходит 128 с чистым fatal-сообщением — маппим в INCONCLUSIVE.

**Атака R-2 (SSRF-редирект):** разрешённый домен редиректит на
<!-- stale-ignore -->
`http://169.254.169.254/`. Защита: ре-валидация редиректа (проверка финального
хоста) + второй слой через `http.*.extraheader`/env-ограничения. Тест: E-08
(редирект + rebinding-проба с локальным mitm или публичным редиректором на
приватный IP; гонять только против нашего тестового хоста).
<!-- stale-ignore -->

**Атака R-3 (tar/zip upload):** `UploadSource` — лимит размера архива до
распаковки, per-file и суммарные лимиты, защита от path-traversal (отклонять
`../` и абсолютные члены), защита от decompression bomb (zip-bomb / tar 9-петабайт
sparse). TTL-очистка (таблица ТЗ 2.1: прецедент KI-110 — 2481 мусорных папок,
нет GC). Fingerprint = content-hash архива → повторная загрузка идентичного
архива пропускает re-embedding.

#### 2.3 Remote file access
- **Read:** `read_live_file` — расширить на резолв через `WorkspaceSource.resolve()`
  (проверено: сейчас читает из локального пути проекта; сделать source-aware —
  маленькое, хорошо тестируемое изменение). Одинаково работает для local и
  cloned-remote.
- **Write:** remote = read-only по умолчанию (рекомендация 3: per-workspace флаг
  `--allow-remote-write`, не глобальный); каждый write через существующий гейт
  `verify_action` (ExecutionContract) + явное подтверждение первого write сессии
  для remote-источников.

### §3 TRANSPORT LAYER — решение: Streamable HTTP, SDK даёт его

Живые факты (загружены в этой сессии):
- Текущая ревизия спеки MCP 2026-07-28 определяет ровно два биндинга: stdio и
  **Streamable HTTP**. HTTP+SSE (2024-11-05) **deprecated** с 2025-03-26
  (SEP-2596), подлежит удалению. Новую работу над SSE НЕ ведём.
<!-- stale-ignore -->
- Наш пин `mcp==1.28.1` (pyproject проверен) — линия поддержки **v1.x**, в ней
  есть `streamable_http.py` (`StreamableHTTPServerTransport`,
  `StreamableHTTPSessionManager`), `transport_security.py` (Origin/DNS-rebinding
  middleware) и пакет `auth/` (хуки OAuth 2.1 resource server). Проверено в
  установленном venv: `mcp.server.sse` и `mcp.server.streamable_http` присутствуют.
<!-- stale-ignore -->
  FastMCP: `mcp.run(transport="streamable-http")` или `mcp.streamable_http_app()` →
  Starlette ASGI app (моунтится в наше FastAPI/Starlette-приложение рядом с `/healthz`).
- Клиентские конфиги remote-серверов решены и проверены: Claude Code
  (`"type": "http"`, headers/oauth), VS Code `.vscode/mcp.json` (`"type": "http"`,
  bearer или OAuth browser flow, fallback HTTP→SSE), Zed settings.json
  (`context_servers` с url + Authorization header или OAuth-промпт). Cursor
  (community bridge-конфиги; нативная страница client-rendered — помечено unverified).
- Стандартного health-эндпоинта в спеке нет; прецеденты ad-hoc (`/healthz` в
  supergateway, `/status` в mcp-proxy). Ставим свой `/healthz` + Docker
  HEALTHCHECK/systemd.

План:
1. `src/mcp/transport/stdio.py` — перенести текущую stdio-обвязку (поведенчески идентично).
2. `src/mcp/transport/streamable_http.py` — обернуть `StreamableHTTPServerTransport`
   вокруг того же результата `create_mcp_server()` (тот же набор тулов, тот же DI).
3. `src/remote_main.py` — entrypoint: FastAPI/Starlette app, моунт streamable HTTP
   + `/healthz` + auth-мидлварь. Auth v1: **Bearer token** (`MSCODEBASE_REMOTE_TOKEN`),
   простейший, поддерживается всеми четырьмя клиентами. OAuth 2.1 AS (метаданные
   RFC 9728, PKCE) — отложенный opt-in v2: хуки в SDK есть, реальная работа — AS-эндпоинты.
4. Переиспользовать `SlidingWindowRateLimiter` + `CircuitBreaker` на гейте
   (per-token + per-IP), не писать новое (ТЗ §3.2). Замечание: лимитер на
   `threading.Lock` loop-agnostic (WISDOM: asyncio.Lock дедлочит кросс-loop) —
   держать threading-примитивы.
5. Наблюдаемость: structured logging в `data_root/logs` (уже паттерн) +
   `/healthz` для uptime-мониторов (ТЗ §9б-6). Опционально OTel trace-context
   (SEP-414) — позже.
6. Деплой: Docker image + compose по образцу официального `example-remote-server`
   (паттерн отдельного AS, Redis-сессии — Redis пропускаем, пока нет
   multi-instance); история обновления = stop→update→start для v1, rolling restart
   задокументировать позже (ТЗ §9б-7).

**DoD (§7 Фаза 3):** тест-сьют эквивалентности транспортов — один и тот же
запрос через stdio и HTTP возвращает идентичный JSON для репрезентативного
подмножества тулов (E-07).

**Известный риск (обязательно протестировать, E-07b):** спека толкает stateless
JSON-response режим для масштабируемости, но наш движок stateful (индексы,
фоновые задачи, сессии). Проверить, что ломается (нотификации
`notifications/message`, прогресс фоновых задач) до фиксации stateless-режима.

### §4 ADAPTER LAYER

Подтверждено: DI-контейнер, 47 tool-классов, Indexer/Searcher/SymbolIndex,
IntelligenceLayer ничего не знают про Zed (проверено чтением base.py + tools).
Zed-специфичное к переносу (Фаза 0): `src/utils/zed_config.py` →
`adapters/zed/zed_config.py`; `extension.toml` → `adapters/zed/` (ОТЛОЖЕНО до
Фазы 4 — см. статус-блок); `src/main.py` install/configure-режимы →
`adapters/zed/install.py`; `core-install` (venv, deps, модели) остаётся на уровне движка.

Новые адаптеры — конфиг-first (таблица ТЗ §4.3 подтверждена клиентскими
конфигами):
- VS Code/Cursor: `.vscode/mcp.json` с stdio-командой (и `"type": "http"` для
  remote) — конфиг + док.
- Claude Code/Desktop: `.mcp.json` (`"type": "http"` или stdio `command`) — конфиг + док.
- CLI: тонкий wrapper `mscodebase-cli <tool> [args]`, вызывающий tool-классы
  напрямую (без MCP-протокола) — для CI/скриптов; ~1 файл.
- Remote: `remote_main.py` + Docker (см. §3).

### §5 PLUGIN MODEL — RCE главный риск; дизайн = trust-гейт + изоляция

**Атака E-01 (прогнана в этой сессии, raw output в журнале экспериментов):**
наивная загрузка внешнего `.py`-плагина (буквальное предложение ТЗ §5.2) =
**произвольное исполнение кода в процессе сервера при старте** — продемонстрировано:
плагин записал маркер-файл со своим pid. Митциированный поток (trust-гейт до
импорта + sha256-pin на плагин+версию) заблокировал его; детект дрейфа хэша
переспрашивает при модификации. Также важно: наша собственная песочница
`validate_code` (execute_script) уже блокирует `importlib.util.module_from_spec` —
намёк на то, что может AST-гейт, но MCP-процесс не должен на это полагаться.

Исследовательская база (загружено live): trust-промпт издателя при установке
VS Code 1.97 + верификация подписи (marketplace-signed; сбой блокирует установку);
VS Code Workspace Trust (Restricted Mode отключает extensions/agents/terminal;
запись доверия **per extension version**); расширения Zed sandbox-ованы Wasm по
конструкции, а MCP-серверы запускаются **вне процесса**; RestrictedPython явно
«не песочница»; Home Assistant требует `version` в манифесте custom-компонентов;
npm engines/os/cpu поля + `--ignore-scripts`; WordPress `Requires at least`;
официальный MCP registry — будущий путь дистрибуции (Zed деприкейтит свой формат
MCP-server-расширений в его пользу).

Дизайн:
1. **Манифест** (`ToolPlugin`): добавить к протоколу ТЗ:
   - `requires_engine_version` (семантика npm/VS Code `engines` — enforce при
     загрузке, block с сообщением при несовпадении; закрывает ТЗ §9б-5)
   - `schema_version` (паттерн Zed — эволюция манифеста ≠ несовместимость движка)
   - `version` ОБЯЗАТЕЛЬНА для внешних плагинов (правило HA)
   - `platform` (прецедент npm os/cpu — падать громко, не тихо)
   - `dependencies` (пины; скрытая RCE-поверхность — `import requests` в плагине
     исполняет и код requests тоже; сканировать pip-audit-стилем при установке)
   - Манифест маппится 1:1 на запись официального MCP registry позже; НЕ
     изобретать параллельный формат дистрибуции (research: схема mcp-get/Smithery).
2. **Load-гейт (строгий порядок, TOCTOU-guard):** парс манифеста (без исполнения) →
   валидация schema/version/platform → проверка пина sha256 → запись доверия есть?
   (нет: ПРОМПТ пользователя с name/version/publisher/sha256/source, сохранить
   per plugin+version; да: дальше) → импорт. Любое изменение файла между гейтом и
   импортом перегоняет гейт заново (хэшировать файл прямо перед импортом).
3. **Default-deny:** плагины не авто-загружаются при первом запуске (паттерн
   worktree-trust Zed); новый плагин = явное решение пользователя; состояние
   «загружен, но отключён» (паттерн Restricted Mode VS Code).
4. **Граница изоляции:** сторонние плагины работают в **subprocess** (JSON-RPC
   или mini-MCP через stdio — экосистемно-нативная модель; даже Zed запускает
   MCP-серверы вне процесса). In-process — только для first-party /
   vendor-reviewed плагинов. RestrictedPython — только как харденинг для
   почти-доверенного кода, никогда как граница. `wasmtime` — настоящая песочница,
   но авторы должны компилировать в Wasm + ежемесячные ломающие мажоры — отложить.
5. **Self-check регистрация (P-001, ТЗ §6.7):** после `container.register()` для
   плагина проверить, что тул реально появился в DI со своими заявленными
   `requires`; плагин, который «импортировался без exception», но не
   зарегистрировался = сбой загрузки с reason, не тишина.
6. **Подписи:** hash-pinning сейчас (PyPI не поставляет per-file подписи —
   проверено `has_sig: false`); sigstore/DSSE позже, если/когда выйдем в registry
   (прецедент npm `audit signatures`).

**DoD (§7 Фаза 4):** минимум один сторонний плагин как PoC — например, VOR
`verify_claim`-инструмент из экспериментов 1-L/2E, вынесенный как плагин.
Регресс-тесты: E-01-стиль негативные контроли в `tests/test_plugins.py`
(наивная загрузка блокируется, trust-гейт работает, дрейф переспрашивает,
несовпадение версии отказывается грузиться).

### §6 Уроки экспериментов → архитектура (каждое — правило кода, не совет)

| ТЗ ref | Правило | Реализация |
|---|---|---|
| 6.1 | LLM-вызовы возвращают evidence (реальный фрагмент кода вокруг anchor), никогда голый токен | Расширить `intel_predict_root_cause`/`generate_chunk_summaries`: всегда `evidence` (file:lines + фрагмент). Recall 0.08→0.88 — наши числа (Exp 1-L). |
| 6.2 | Manifest anchoring — закрытый мир, не grep | Тип anchor `pkg:` резолвит pyproject.toml/package.json/lockfile через парсер, не свободный grep (ADR-0005, exp-3: 7 false REFUTED → 0). |
| 6.3 | Subject-identity check (present-trap, KI-103) | Verify-тулы обязаны резолвить anchor → AST-сущность через SymbolIndex/Call Graph, затем ограничивать evidence реальными рёбрами сущности. `graph_context_first` формализован. |
| 6.4 | Каждый новый evidence-формат → слепой контроль | DoD-пункт для любого PR, трогающего evidence-слой: blind-проба (с подсказкой vs без) до дефолта. Внедрить чек-лист PR в CONTRIBUTING. |
| 6.5 | INCONCLUSIVE как first-class вердикт | Расширить GRACEFUL_DEGRADATION 4 уровня на source/transport/adapter слои (проверено: существует для embedder). Сбой source/plugin → degraded-статус с reason, не crash/тишина. |
| 6.6 | Детерминизм роутинга | Только при появлении внешнего LLM-провайдера: `pin_provider` + `allow_fallbacks:false` + K≥3 (из CSV-аудита OpenRouter). Не сейчас. |
| 6.7 | Guard P-001 для plugin-загрузки | См. §5.5 self-check регистрация. |

### §7 Фазы 0-5 — разбивка задач с DoD

**Фаза 0 — Разделение без смены поведения.** ✅ **ВЫПОЛНЕНО 2026-08-18 (локально).**
- `SafePathManager`/`to_win_long_path` → `adapters/local_fs/windows.py` (POSIX no-op). ✅
- `zed_config.py` → `adapters/zed/zed_config.py`. ✅
- Импортеры обновлены (9 сайтов), старый paths.py удалён. ✅
- Гейт `scripts/check_layer_boundaries.py` (3 transitional, 0 нарушений). ✅
- DoD: 1300 passed / 10 skipped. ✅ (smoke_e2e и CI ≥2 OS — остаток.)
- ОТЛОЖЕНО с дедлайнами: extension.toml → Фаза 4; install.py split → Фаза 4/5;
  platform_utils.get_zed_* → Фаза 1.

**Фаза 1 — WorkspaceSource абстракция.** ✅ **ВЫПОЛНЕНО 2026-08-18 (ветка feat/universal-engine).**
- Протокол `WorkspaceSource` + `FileChangeEvent` → `src/core/interfaces/workspace_source.py`
  (core-owned, паттерн IEmbedder). ✅
- `src/sources/local_fs/` — `LocalFsSource` (resolve/watch/fingerprint); финальный дом
  хелперов `src/sources/local_fs/windows.py`; `adapters/local_fs/` удалён. ✅
- Indexer принимает `source: WorkspaceSource` и берёт `path_manager` из него
  (дефолт LocalFsSource; конструкция дефолта переедет в DI/registry в Фазе 2). ✅
- Гейт: transitional core→src.sources.* = 3 (db_manager, indexer, tools_reg),
  цель — 0 к концу Фазы 2. ✅
- Тесты: tests/test_local_fs_source.py (8) + полный pytest 1308 passed / 10 skipped. ✅
- DoD: сервер ведёт себя идентично через новый интерфейс (1308 зелёные).

**Фаза 2 — GitUrlSource.** ✅ **core готов (2026-08-18, feat/universal-engine).**
- `src/sources/git_url/`: GitUrlSource (WorkspaceSource) + GitRepoCache (LRU(5)+TTL 24ч)
  + SSRF-валидация. ✅
- Защита R-2: scheme allowlist (https-only дефолт), domain allowlist, все A/AAAA
  обязаны быть global (IMDS/RFC1918/loopback → отказ), post-clone origin-check
  (редирект), лимиты размера/файлов/таймаут, protocol.file.allow=never. ✅
- Ошибки → GitUrlSourceError с kind (INCONCLUSIVE-контракт, ТЗ §6.5). ✅
- `get_repos_cache_dir()` в artifact_paths. ✅
- Тесты: tests/test_git_url_source.py (12) + pytest 1320 passed / 10 skipped. ✅
- **Остаток Фазы 2:** E-03 ✅ ВЫПОЛНЕНО 2026-08-18 (4/4 репо, реальный embed 8080:
  httpx 1812 / flask 1605 / rich 2808 чанков; fingerprint 89-123ms; cache-hit
  ~200-400ms; несуществующий URL → INCONCLUSIVE; **находка**: Windows rename-lock
  на свежих клонах → clone-in-place + атомарность через манифест; rich: 3 длинных
  файла — graceful embed-деградация). MCP-тул-обвязка ✅ (index_git_url через
  DI-фабрику; hub: index(action=git_url), codebase(action=index, sub=git_url);
  INCONCLUSIVE-обработка; read-only). E-08 ✅ ВЫПОЛНЕНО (9/9 live SSRF: scheme/domain/
  creds/port/DNS localhost→loopback отклонён, happy-path github.com ок). UploadSource
  ✅ (src/sources/upload/: zip/tar.gz, R-3 path-traversal+symlink+bomb guards,
  TTL-кэш, content-hash fingerprint; 9 тестов). DNS-rebinding-пиннинг (Фаза 2.5).

**Фаза 2.5 — приватные репо** (рекомендация 1: после ~2 недель чистоты
публичного пути): SSH-ключи/токены только в OS keychain или `.env` (никогда в
URL/дисковом кэше), те же allowlist + лимиты. Secrets-leak review-гейт (прецедент
shadow-canary: 5/5 атак прошли до фикса — новый код систематически дыряв, пока не
доказано обратное).

**Фаза 3 — Streamable HTTP транспорт** по §3. DoD: сьют эквивалентности
транспортов (E-07), auth (Bearer), реюз rate limiting, `/healthz`, Docker image.

**Фаза 4 — Plugin-манифест** по §5. DoD: PoC-плагин (VOR `verify_claim`
вынесенный), RCE-негативные контроли, тесты несовпадения версий, trust-гейт UX.

**Фаза 5 — Адаптеры** по §4. DoD: ручная проверка на реальном VS Code/Cursor с
реальным репо; CLI wrapper; доки для Claude Code.

### §8 Что осознанно НЕ делать — подтверждено
- Не переписывать Indexer/Searcher/SymbolIndex (проверено: чисто — DI, тесты, разделение).
- Не делать multi-tenant SaaS (auth per-user, изоляция, биллинг — отдельный проект).
- Не делать параллельный не-MCP формат плагинов; MCP — стандарт (research: даже
  собственный формат MCP-server-расширений Zed деприкейтится в пользу официального registry).
<!-- stale-ignore -->
- ДОБАВЛЕНО: миграция на mcp SDK v2 — не в критическом пути этого проекта;
  1.28.1 работает со всеми текущими клиентами (конфиги проверены); запланировать
  отдельно (§Temporal).
<!-- stale-ignore -->

### §9 Открытые вопросы — решения (рекомендации подтверждены исследованием)
1. **Приватные репо: сначала только публичные HTTPS.** (Проверенный факт: git
   делает retry с credentials при 401; SSH-путь добавляет поверхность управления
   ключами до того, как публичный путь обкатан. Прецедент shadow-canary.) → Фаза 2.5.
2. **Remote-кэш: LRU(5) + TTL 24ч** — переиспользовать число `ProjectIndexerRegistry`
   (нет known issue по нему); TTL 24ч обоснован: remote-клоны должны протухать сами;
   механизм эвикции — Bazel disk-cache GC (size+age+idle).
3. **Write в remote: read-only по умолчанию, per-workspace opt-in флаг, гейт
   verify_action.** (Прямое продолжение позиции владельца «Verify is 80% of the
   work» для Mikatoshi.)

### Раздел о языке — Python остаётся; доказательства
- Core (DI, тулы, IntelligenceLayer, Indexer/Searcher/SymbolIndex): Python,
  протестирован, не переписывать (проверено в этой сессии: 47 tool-классов + 1300 тестов).
- Tree-sitter, LanceDB, BM25, эмбеддинги: Python-first экосистемы, паритета в
  других языках нет (проверено WISDOM).
- Streamable HTTP транспорт: официальный Python SDK даёт (проверено в venv).
- `GitUrlSource` I/O-бутылочное горлышко: ТОЛЬКО если профилирование (py-spy)
  покажет, что GIL — предел; не превентивно (правило ТЗ; §1.20 соразмерность).

### §10 Reranker и «тяжёлые» слои — дефолты (из наших чисел, WISDOM)
| Слой | Решение | Цена (задокументирована) |
|---|---|---|
| BM25/FTS5 + SymbolIndex/Call Graph | **ON всегда** (носитель recall: fts5_only 0.825 > full 0.775) | дёшево, без внешних вызовов |
| Reranker | флаг `--reranker` (precision +0.147, recall −0.019) | ~1200ms vs 300ms |
| Vector (e5-small) | флаг `--vector-search`, только гибрид-дополнение (recall 0.083-0.167 — слабейший для symbol-задач) | embed runtime |
| CoT/reasoning | флаг `--cot`, точечно (выигрыш recall ×30-65 токенов; glm теряет 16-26% на EMPTY_CONTENT) | токены ×30-65 |
| Late enrichment | OFF (KI-106: 0.0% покрытия на search chunks) | — |
Правило нового тяжёлого слоя: rung evidence-ladder + слепой контроль до дефолта (§6.4/12.2).

### §11 Action Receipt — строить на ChangeIntent + in-toto envelope (без крипто)

Проверенное текущее состояние: `ExecutionContract` (verify_file_write/git_commit/
git_push/index_sync) + `ChangeIntent{before_hash, after_hash, base_commit, timestamp}` +
`ChangeIntentLedger` (JSONL в data_root) — скелет receipt уже есть. Исследование
(загружено): in-toto link = оригинальный «action receipt» (materials/products =
before/after хэши; `MODIFY` = before ≠ after; `expected_command` mismatch — только
WARNING — команды подделываются через PATH, не считать точное совпадение
критерием); SLSA Provenance (split externalParameters/internalParameters;
рекомендация: предпочитать именованные verify-процедуры инлайн-спискам команд —
параметризованный список команд непрактично верифицировать, он меняется каждый
прогон); SLSA L1 допускает unsigned provenance; VSA записывает РЕЗУЛЬТАТЫ
верификации (бинарно); OpenWorkProof (dengyier, 2026-07) — ближайший протокол
(WorkOrder→ActionReceipt→AcceptanceReceipt, офлайн детерминированный реплей
верификатора, tri-state VERIFIED/REFUTED/UNKNOWN с машинными reason-кодами,
«UNKNOWN — безопасный вывод, не crash», scope-bound верификация) — совсем новый,
4 звезды, трактовать как прецедент, не как обкатанную реализацию. SWE-bench:
верификация повторным прогоном работает в масштабе, когда окружение запинено и
выборка тестов заморожена. CloudWatch/K8s/Tekton все резервируют третье состояние
для «не удалось проверить» (INSUFFICIENT_DATA / Unknown).

Дизайн:
1. **Envelope:** in-toto Statement v1 (`_type`, `subject: [{name, digest}]` с tree-дигестом
   workspace, `predicateType: "https://mscodebase.dev/action-receipt/v1"`).
2. **Слои предиката:** claim (action_type, заявление агента, per-file before/after
   из ChangeIntent, base_commit) | verification (именованные процедуры — pytest
   marker/путь скрипта как `buildType`-URI + дигест репо покрывает процедуру;
   записанный argv — адвизорный) | verdict (чистая функция перезапущенных проверок).
3. **Tri-state + reason-коды:** VERIFIED (шаги перезапущены, результат совпал с
   claim) / REFUTED (проверка выполнилась и дала определённый негатив) /
   INCONCLUSIVE (всё остальное: timeout, нет окружения, нет базлайна) — с машинным
   `reason` (`TEST_FAILED`, `HASH_MISMATCH`, `BASELINE_MISSING`, `CHECK_TIMEOUT`, …)
   + человеческим `message` (паттерн K8s conditions). Scope pinning: точная выборка
   тестов + ревизия на каждом «tests passed»; receipt говорит «эти N тестов прошли
   на дереве X», никогда «фикс работает».
4. **Шаги (§11.5):** (1) расширить `verify_action` полями receipt — в основном
   реюз ChangeIntent; (2) новый `get_action_receipt(action_id)` — хранить receipts
   в ТОМ ЖЕ сторе, что project memory (intel_add_memory_node, section="receipts"
   по ТЗ) — НО с оговоркой: memory store для маленьких JSON-узлов; receipts несут
   evidence-рефы (hash + path), evidence-блобы живут в data_root, в памяти — envelope;
   (3) тест воспроизводимости: для каждого типа verification_steps сгенерировать
   `reproducible_by`, выполнить в чистом окружении, убедиться что вердикт совпал
   (E-05 на 10-20 реальных действиях); (4) retention: INCONCLUSIVE протухает быстро,
   VERIFIED/REFUTED пока на них ссылаются, GC evidence по max-age/size (прецедент
   Bazel disk-cache); receipts иммутабельны — пере-верификация, перевернувшая
   вердикт, = НОВЫЙ receipt, суперседящий старый (никогда не мутировать).
5. **Env-fingerprint = только адвизорный** (роль SLSA internalParameters):
   несовпадение → INCONCLUSIVE + warning, никогда REFUTED («окружение отличается»
   не фальсифицирует claim).
6. **E-05 — гейт до дефолта §11** (ТЗ §12.3 явно помечает §11 как экстраполяцию):
   подозрение в том, что `reproducible_by` может не воспроизводиться 1:1 (флейки,
   дрейф окружения — задокументированные Bazel failure modes). Если на реальных
   действиях провалится — §11 деградирует до «информативного лога», не верификации.

### §12 Research-driven build process
Принять 4-шаговый протокол для каждой новой подсистемы (гипотеза с числом →
минимальный эксперимент → вердикт записан, включая «do not repeat» → слепой
контроль до дефолта). Пометить в этом плане, что проверено владельцем vs
экстраполяция (ТЗ §12.3 принято). Ежеквартальный ре-тест одного прошлого вывода
(прецедент E4/E4b). Сам этот документ следует формату: каждое дизайн-решение выше
цитирует эксперимент или загруженный источник.

---

## 2. Журнал экспериментов (эта сессия)

### E-01 — RED TEAM: внешняя загрузка плагина = RCE (прогнано 2026-08-18)
Команда: temp `.py` в `%TEMP%`, загрузка через
`importlib.util.spec_from_file_location` + `exec_module`.
Raw output (venv python):
```
=== ATTACK: naive external plugin load (ТЗ 5.2) ===
plugin: C:\Users\...\Temp\plugin_attack_cm6wzpng\evil_plugin.py
sha256[:12]: 74d6c0dc7b14
marker exists after import: True
marker content: plugin executed with pid: 6888
>>> RCE CONFIRMED: code ran inside the loading process on startup
=== MITIGATION: trust gate (hash-pin per plugin+version) ===
BLOCKED before import — prompt user (name/version/sha256/source)
=== DRIFT: plugin modified after trust -> hash changed -> re-prompt ===
old: 74d6c0dc7b14 new: 430431f87a55 re-prompt needed: True
```
Вердикт: **атака подтверждена; митигация (hash-pin + trust-гейт) подтверждена;
детект дрейфа подтверждён.** Побочная находка: наш AST-гейт `validate_code` уже
блокирует `importlib.util.module_from_spec` — полезный прецедент для дизайна
plugin-гейта, но MCP-процесс не должен на него полагаться.

### E-02 — Feasibility GitUrlSource (прогнано 2026-08-18)
| Проба | Результат |
|---|---|
| `git clone --depth 1` Hello-World | 1.2s, 80KB |
| `git clone --depth 1 --filter=blob:none` psf/requests | 2.9s, 7.7MB, 130 файлов в дереве; full clone = 19MB (~60% экономии) |
| Fingerprint: `git rev-parse HEAD` + `git ls-tree -r HEAD` | 79ms, ноль повторного хэширования |
| Несуществующий URL | exit 128, чистый fatal → маппинг в INCONCLUSIVE |
| Схема `file://` | exit 128 (git ≥2.38 блокирует по умолчанию) — но мы отклоняем на парсе, не полагаясь на это |

Также измерено/отмечено: пайп через `tail` маскирует exit-код git (`$?` = 0) —
контракт subprocess обязан использовать `Popen` + `communicate` (WISDOM §5.16),
никогда `capture_output` в daemon-тредах, никогда не доверять `$?` через пайп.

### Очередные эксперименты (по фазам, из пробелов исследования)
- E-03: полный пайплайн clone→index на 5-10 публичных репо (DoD Фазы 2; включая
  пробу лимитов на больших репо).
- E-04: слепой контроль evidence-форматов в remote/plugin-контексте (rung-стиль).
- E-05: воспроизводимость `reproducible_by` Action Receipt на 10-20 РЕАЛЬНЫХ
  действиях (гейт §11; собственное подозрение ТЗ §12.3).
- E-06: сравнение изоляции плагинов — subprocess/JSON-RPC vs in-process vs
  RestrictedPython vs wasmtime (оверхед, поломки).
- E-07: эквивалентность транспортов stdio vs HTTP (один запрос → один JSON);
  E-07b: влияние stateless-режима на нотификации/фоновые задачи.
- E-08: SSRF-сьют — редирект-на-приватный-IP, DNS-rebinding-проба, отклонение
  file://, блок localhost/metadata, только против нашего тестового хоста.
- E-09: decompression bomb + path-traversal тесты распаковки upload.
- E-10: multi-client HTTP конкуренция — 2 клиента, 1 workspace: корректность
  результатов (не только «без исключений», правило §5.13) + write-исключительный лок.

---

## 3. Реестр атак (по фазам)

| # | Вектор | Фаза | Защита | Статус |
|---|---|---|---|---|
| R-1 | Перетекание слоёв (тул импортирует platform/zed после рефакторинга) | 0 | CI-grep-гейт на `src/mcp/tools/` + `src/sources/` | планируется |
| R-2 | SSRF через git-URL (редирект/rebinding/IMDS) | 2 | scheme+domain allowlist, проверка всех A/AAAA, ре-валидация редиректа, protocol.file.allow=never | планируется (E-08) |
| R-3 | Upload-бомбы / path traversal | 2 | лимиты размера, guard распаковки, TTL GC | планируется (E-09) |
| R-4 | Плагин RCE | 4 | trust-гейт + hash-pin + subprocess-изоляция + self-check регистрация | **продемонстрирована (E-01)** |
| R-5 | Обход remote-аутентификации / абьюз rate limit | 3 | Bearer token, SlidingWindowRateLimiter + CircuitBreaker per token/IP, /healthz | планируется |
| R-6 | Утечка секретов в GitUrlSource (токен в URL/кэше) | 2.5 | токены только в `.env`/keychain, никогда в кэш-пути, userinfo в URL отклоняется | планируется |
| R-7 | Лицензионное загрязнение (GPL-код в подсказках агента) | 2 | документированное ограничение в README/KNOWN_ISSUES (ТЗ §9б-3) | планируется |
| R-8 | Multi-client write-гонка на общем workspace | 3 | workspace-level lock (обобщённый PID-lock), read-shared/write-exclusive | планируется (E-10) |

---

## 4. Матрица взаимодействий (см. D-3) — риски по слоям

| Забота | Слой | Решение |
|---|---|---|
| Zed-специфичный multi-window (2 процесса) | adapter/zed | существующий PID-lock + port-ready + CWD-first резолв (оставить) |
| Multi-project поперёк редакторов | core | ProjectIndexerRegistry LRU(5) поднят в core |
| HTTP multi-client shared read | core | реюз кэша индекса; read-only до opt-in |
| HTTP multi-client конкурентный write | core | workspace lock; гейт verify_action; INCONCLUSIVE при контеншене |
| Дедуп notify_change поперёк процессов | core | per-client DebounceBatch; DatabaseLock сериализует записи LanceDB; E-10 проверяет корректность содержимого |
| Паритет Windows/Linux/macOS | adapters | экстракция Фазы 0; CI ≥2 ОС с первого PR |
| Trust плагинов поперёк машин | plugins | per-machine запись доверия (hash-pin), НЕ синкается |

---

## 5. Temporal

<!-- stale-ignore -->
- **T+0:** фазы 0-1 на месте, безопасно. mcp==1.28.1 ок для всех текущих клиентов.
- **T+30d:** Python 3.10 EOL 2026-10 → CI-матрица обязана его дропнуть (пин
  3.11/3.12/3.14); миграция mcp SDK v2 обязана быть запланирована (1.28.1 = провод
  эпохи 2025; спека ушла на 2026-07-28 — клиенты пока договариваются, но v1.x
  только в поддержке); схема официального MCP registry обязана быть проверена до
<!-- stale-ignore -->
  проектирования дистрибуции (docs-страница 404 сегодня — проверить llms.txt +
  registry API).
- **T+180d:** если remote-режим пойдёт в multi-tenant, нынешнюю границу «один
  движок, много клиентов» придётся пересматривать (auth, изоляция); дрейф
  plugin-API — митигируется `requires_engine_version` + `schema_version` +
  ежеквартальные слепые ре-тесты (§12).

---

## 6. Следующий шаг (рекомендованное начало)

1. Открыть ветку `feat/universal-engine`.
2. Фаза 0 первый PR: экстракция `adapters/local_fs/windows.py` + `adapters/zed/`
   с grep-гейтами; прогнать 1300 тестов + smoke_e2e на Windows; добавить Linux-джобу
   в CI-матрицу в ТОМ ЖЕ PR (§9б-8).
   → **ВЫПОЛНЕНО локально 2026-08-18** (переносы + `scripts/check_layer_boundaries.py` +
   1300 тестов зелёные; не закоммичено). Остаток Фазы 0: CI-матрица ≥2 ОС;
   повторный smoke_e2e; commit/PR владельцем.
3. Параллельно E-03 (clone→index на 5-10 репо) и E-05 (воспроизводимость receipt)
   можно гонять в `experiments/universal-engine/` без блокировки Фазы 0.
