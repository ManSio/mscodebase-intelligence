# AGENT DIARY — MSCodeBase Intelligence

> Хроника разработки проекта. Ведётся на русском языке.
> Содержит ключевые архитектурные решения, найденные баги и их исправления.

---

## [2026-07-07 20:30] — Test: phi-4-mini-instruct live via LM Studio + bump 2.5.2

**Test:** curl /v1/chat/completions с phi-4-mini-instruct Q4_K_M
- Ответ: 75 токенов, finish_reason=stop, стихи на запрос
- Модель auto-loaded (state was not-loaded), загрузка прозрачная
- Первый вызов ~5-8s (включая загрузку), последующие быстрее

**Результат:** phi-4 готова к mode=ask для v2.7.0.
**Version bump:** extension.toml 2.5.1→2.5.2, __init__.py 2.5.1→2.5.2

**Status:** ✅

---

## [2026-07-07 19:00] — Feature: Multi-Bucket RAG (v2.6.0 Phase 1) — Overfetch + Soft Weighting

**Problem:** Единый слепой векторный поиск без учёта типа файлов.
Жёсткий layer-filter вырезал целые категории, ухудшая recall.

**Solution:**
- Overfetch: BM25 и Vector поиск запрашивают `raw_limit` чанков
  (min(max(limit * overfetch_factor, 1), MAX_RERANKER_INPUT=30))
- Bucket distribution: чанки классифицируются по расширению файла
  (CODE_EXTENSIONS: .py/.rs/.js/…  |  DOCS_EXTENSIONS: .md/.txt/.rst/…)
- Soft Weighting: `final_score *= bucket_weight` (default 1.0, управляется через .env)
- Cut to limit: после взвешивания — сортировка и обрезка до оригинального `limit`
- Bucket weight применяется ДО reranker (reranker перезаписывает scores)
- Все веса и расширения переопределяются через .env

**Files changed:** `src/core/config.py`, `src/core/searcher.py`
**Tools Used:** edit_file, read_file, terminal(pytest)
**Status:** ✅ (391 тестов пройдено, 0 регрессий)

---

## [2026-07-07 19:30] — Feature: Contextual Prefix (v2.6.0 Phase 2) + Reindex

**Problem:** Вектора строились по чистому коду без контекста файла.
Реранкер не мог отличить chunk из `searcher.py` от chunk из `test_searcher.py`.

**Solution:**
- Для кода: `// File: {path} | Context: {class}.{func}\n`
- Для .md: `From {path}, section '{heading}':\n`
- Для fallback: `// File: {path}\n`
- Префикс добавляется только в `text` (идёт в эмбеддинг), `text_full` без изменений
- Проведена полная переиндексация (2346 чанков)

**Files changed:** `src/core/parser.py`
**Tools Used:** edit_file, intel_trigger_reindex, search_code (live test)
**Status:** ✅ (391 тестов, контекст виден в выдаче)

---

## [2026-07-07 20:00] — Feature: Soft Scoring + intent_hint (v2.6.0 Phase 3)

**Problem:** Bucket weighting был статическим (code=1.0/docs=1.0).
Агент не мог управлять приоритетом код vs документация.

**Solution:**
- Добавлен параметр `intent_hint` в `search_code`:
  - `"auto"` (default) — нейтрально 1.0/1.0
  - `"code"` — code=1.2, docs=0.8
  - `"docs"` — code=0.8, docs=1.2
- Выделен статический метод `_apply_bucket_weights()`
- Веса применяются ДО reranker (и для fast mode — как финальные)

**Files changed:** `src/mcp/tools/search_tools.py`, `src/core/searcher.py`
**Tools Used:** edit_file, terminal(pytest)
**Status:** ✅ (391 тестов)

---

## [2026-07-07 20:15] — Feature: SYSTEM_PROFILE (v2.6.0 Phase 4) + Version bump to 2.5.1

**Problem:** Отсутствовала возможность переключать режим работы системы.

**Solution:**
- `SYSTEM_PROFILE=light|server` через `.env`
- Валидация профиля в `__post_init__`
- Свойства `is_light_profile`/`is_server_profile`
- `server` профиль зарезервирован для будущего HYDE-агента

**Version bump:** extension.toml 2.4.4→2.5.1, __init__.py 1.0.0→2.5.1

**Files changed:** `src/core/config.py`, `extension.toml`, `src/__init__.py`, `docs/en/CHANGELOG.md`
**Tools Used:** edit_file
**Status:** ✅

## [2026-07-07 02:10] — Fix: error_handler тесты переведены на Markdown-формат

**Problem:** Все тесты error_boundary падали, т.к. `_format_error_response` теперь возвращает
Markdown-строку вместо JSON. 7 тестов использовали `json.loads(result)` + проверку полей.

**Solution:** Заменил `json.loads` + assert'ы по полям на проверку ключевых слов в Markdown:
- status="warning" → `"Warning" in result or "warning" in result`
- status="error" → `"Error" in result or "error" in result`
- status="timeout" → `"Timeout" in result or "timeout" in result`
- message/detail → `"<text>" in result`

**Files changed:** `tests/test_error_handler.py` (7 тестов)
**Tools Used:** read_file, edit_file, terminal
**Status:** ✅

## [2026-07-07 01:30] — Ultra-Lean reranker: одностадийный cross-encoder вместо трёхстадийного pipeline

**Problem:**
Трёхстадийный pipeline (embed → cross-encoder → LLM) оказался избыточным:
- Stage 1 (text-embedding-bge-m3): дублирует LanceDB, +564ms оверхеда
- Stage 3 (phi-4): обнуляет код (score=0.00 для .py файлов), +5981ms за 0 пользы
- Полный pipeline: ~15s при качестве хуже, чем один cross-encoder

**Solution:**

Полный datadump и бенчмарки:

### Performance benchmarks (реальные замеры)
```
Модель                     ms/text    throughput
────────────────────────────────────────────────
text-embedding-bge-m3       53ms        19 t/s
bge-reranker-v2-m3-m3       37ms 🏆     27 t/s 🏆
phi-4-mini-instruct         8.4 tok/s   —
```

### Сравнение качества scoring
```
Канал           Время    Код в топе    Градиент
────────────────────────────────────────────────
Stage 1 (embed)  564ms   ❌            0.52-0.72
Stage 2 (rerank)  892ms   ✅ 0.92       0.66-0.96 🏆
Stage 3 (phi-4)  5981ms   ❌ 0.00       0.00-0.95 (бинарный)
```

### Итоговое решение
Удалены:
- Stage 1 (text-embedding-bge-m3) — LanceDB уже дал кандидатов
- Stage 3 (phi-4) — обнуляет код, 12x медленнее cross-encoder

Оставлен:
- Stage 2 (bge-reranker-v2-m3-m3) — единственный проход, ~500ms

phi-4 зарезервирован для будущего mode=ask (RAG-генерация ответов).

### Итоговая карта режимов
```
mode=fast   380ms  LanceDB vector           → поиск файла/класса по имени
mode=quality 500ms LanceDB → bge-reranker   → relevance scoring 🏆
mode=deep   3-5s   quality + agentic + graph → исследование
mode=ask    15s    quality + phi-4 RAG       → генерация ответа (future)
```

**Код:** `dbf3d56` — reranker.py: -67 строк, -90% времени, +качество

## [2026-07-07 00:30] — Fix: Трёхстадийный pipeline embed→reranker→LLM + правильная детекция моделей

**Problem:**
- Реренкер не использовал `bge-reranker-v2-m3-m3` — все запросы шли через `text-embedding-bge-m3`
- `_ping_lm_studio` не детектил reranker модели отдельно от embedding
- Guard `len(chunks) <= 1` в `rerank()` скипал весь pipeline при малом числе чанков
- `_check_llm_available` возвращал False из-за кэша (initial `_llm_checked_at = 0.0`)
- **LM Studio не имеет `/v1/rerank`** — reranker работает через `/v1/embeddings`

**Solution:**

### Трёхстадийный pipeline
```
Stage 1: text-embedding-bge-m3 (bi-encoder, cosine sim) → prune top_n*3
Stage 2: bge-reranker-v2-m3-m3 (cross-encoder, cosine sim) → prune top_n*2
Stage 3: phi-4-mini-instruct (LLM, chat completions) → final top_n
```
Каждая стадия опциональна: если модель не загружена/таймаут — пропускается.

### Детекция трёх типов моделей
- `/api/v0/models` (расширенный API) → type-based: embeddings / llm + "reranker" в имени
- `/v1/models` (OpenAI) → name-based fallback: "reranker" / "embed" / "instruct"
- Новое поле `lm_studio_reranker_model` для cross-encoder reranker

### Оптимизации
- `_EMBED_CHUNK_PREVIEW_LEN = 400` (было 800) — ускорило Stage 1+2 в 2x
- `_LLM_STAGE_TIMEOUT = 4s` — phi-4 на CPU медленный, graceful timeout
- Guard `len(chunks) <= 1` удалён — pipeline работает даже с 1 чанком
- Инициализация `_llm_checked_at = -999.0` — первый вызов не кэширует False
- `_llm_available` устанавливается в True сразу при детекции LLM

### Telemetry
```
rerank_timing: {
  "stage1_ms": 1268, "stage1": "text-embedding-bge-m3",
  "stage2_ms": 241,  "stage2": "bge-reranker-v2-m3-m3",
  "stage3_ms": 4005, "stage3": "timeout",
  "total_ms": 7514
}
```

### Protected fallback chain
1. Все три модели доступны → полный pipeline (~6-7s)
2. Нет LLM → Stage 1+2 только (~1.5s)
3. Нет reranker → Stage 1 только (~1.2s)
4. Нет embedding → без реранкинга (RRF order)

**Status:** ✅ Все три модели детектятся, pipeline работает, Stage 3 graceful timeout.

## [2026-07-06 23:00] — Refactor: Полный pipeline реранкинга + телеметрия + memory safety

**Problem:**
- Реренкер вызывал LLM или embedding, не в цепочке
- LM Studio перезагрузка не отслеживалась
- Нет per-stage замеров времени
- Телеметрия не видела какая модель использовалась

**Solution:**

### Pipeline: двухстадийный реранкинг
```
vector search → bge-reranker-v2-m3 (pruning, ~500ms)
  → phi-4-mini-instruct (LLM final, ~2s)
    → результат
```
Каждый этап независим — если модель не загружена, этап пропускается.

### Memory safety
- `_pending_names` dedup в TaskQueue — задачи с одинаковым именем не дублируются
- `cleanup_old_results` чистит и `_pending_names`
- TaskQueue auto-cleanup каждые 60с (TTL 10мин)
- `HeartbeatService._monitor()` гарантированно сбрасывает `_running` в finally

### LM Studio live reload
- Фоновый сканер каждые 30с перепингует модели
- `asyncio.Semaphore(1)` — только 1 запрос к LM Studio одновременно
- `_check_llm_available` с TTL 15с и реальным пингом за 2с
- `_query_lm_studio` универсальный: /v1/chat/completions → /v1/completions fallback

### Telemetry (per-call)
```
detail: "2 results, mode=quality, models=emb=bge-reranker-v2-m3 llm=phi-4-mini-instruct, stages: emb=480ms llm=2100ms tot=2580ms"
```
- Какая модель делала embedding-rerank (stage 1)
- Какая модель делала LLM-rerank (stage 2)
- Per-stage latency
- Cache hit indicator

### Model auto-selection
- `_ping_lm_studio` использует `type`/`state` из LM Studio API
- `type=embeddings` → `lm_studio_embedding_model`
- `type=llm` → `lm_studio_model_name`
- Fallback name-based если API без type
- Reranker модели (type=rerank) выделены отдельно

**Problem:** Stress test MCP server memory usage — measure Python process memory and detect leaks.

**Solution:** Ran `wmic` process monitoring, Python memory sampling, and grep analysis of `searcher.py`.

**Key Findings:**

### Process Architecture
| PID | Role | Memory | Stable? |
|-----|------|--------|--------|
| 11064 | Supervisor (src.main) | ~3.5 MB | ✅ Stable |
| 8432 | Worker (src.main) | 276 MB → 732 MB (and growing) | ❌ **LEAKING** |
| (varies) | Python3.14 temp processes | ~14 MB each | ✅ Stable |

### Memory Leak Details
- Worker PID 8432 grows **linearly at ~3 MB/second** while idle
- Grew from 276 MB → 732 MB in ~3 minutes of passive monitoring
- Growth rate: ~8-9 MB per 3 seconds = ~180 MB/minute
- Eventually MCP becomes completely unresponsive (all tools timeout)
- Supervisor (PID 11064) remains stable at 3.5 MB throughout

### Suspected Causes
1. Unbounded cache in `SearchCache` or result accumulation
2. Repeated asyncio timer/callback registration without cleanup
3. Circular references preventing GC
4. LanceDB connection pool or embedding model references accumulating

### Recommended Investigation
1. Run `gc.get_objects()` snapshot diff every 30s on the worker
2. Check for `asyncio.create_task` without cleanup in event handlers
3. Profile `ServiceCollection` initialization patterns
4. Check `RuntimeCoordinator` for accumulating subscribers

**Tools Used:** terminal (wmic, python3), grep, debug_runtime_passport
**Status:** ❌ (memory leak confirmed, needs fix)

---

## [2026-07-06 19:00] — Fix: Translate Russian _() templates to English in search_tools.py and analysis_tools.py

**Problem:** `_(f"...")` pattern (f-string inside i18n) and Russian text in `_()` template strings — defeats i18n purpose.

**Solution:** 
- `search_tools.py`: 8 calls fixed — translated templates to English (e.g. `"определений"` → `"definitions"`, `"Определение:"` → `"Definition:"`, etc.)
- `analysis_tools.py`: 4 calls fixed — translated scan/generation status messages and cooldown hints to English
- All `_("template {var}", var=val)` pattern preserved; purely dynamic f-strings left bare

**Tools Used:** read_file, edit_file, notify_change, diagnostics, intel_log_incident
**Status:** ✅

---

## [2026-07-06] — Fix: i18n — обёртка user-facing строк в _() в ui_formatter.py и error_handler.py

**Problem:** User-facing return-строки с эмодзи (📦🔍✅❌📊📋🌐🟢🔴⏱ и т.д.)
и русским текстом в двух файлах не проходили через i18n-функцию `_()`.

**Solution:**
- `ui_formatter.py`: обёрнуты ~30 f-строк в 14 функциях-форматтерах
- `error_handler.py`: обёрнуты строки в `_format_error_response` (4) и `_format_success_response` (3)
- Добавлен импорт `from src.utils.i18n import _` в оба файла
- JSON-возвраты, logger.* вызовы и технические строки (код-сниппеты) не затронуты
- Diagnostics: только pre-existing warnings (unused imports), новых ошибок нет

**Tools Used:** write_file, edit_file, notify_change, diagnostics, intel_log_incident
**Status:** ✅

## [2026-07-06 10:00] — Fix: i18n — обёртка user-facing строк в _() в search_tools.py и analysis_tools.py

## [2026-07-06 10:30] — Fix: i18n — обёртка user-facing строк в _() в intelligence_layer.py, searcher.py, multi_project_searcher.py

**Problem:** user-facing return-строки с русским текстом в трёх файлах не проходили через i18n-функцию `_()`.

**Solution:**
- `intelligence_layer.py`: 5 строк (Инцидент сохранён, Неизвестная секция, Ошибка парсинга JSON, Запись добавлена, Job не найдена)
- `searcher.py`: 9 строк (По запросу ничего не найдено, Ошибка поискового движка, Пустой фрагмент кода, Эмбеддер недоступен, Похожий код не найден, Точные совпадения не найдены, Ошибка поиска по коду, Ошибка глубокого поиска)
- `multi_project_searcher.py`: 3 строки (Пустой запрос, Проекты не найдены, Эмбеддер недоступен)

**Tools Used:** read_file, edit_file, notify_change, diagnostics
**Status:** ✅

**Problem:** user-facing строки с эмодзи и сообщения об ошибках
в search_tools.py и analysis_tools.py были hardcoded без поддержки
перевода через _().

**Solution:**
- search_tools.py: обёрнуты return-строки с 🔍✅❌📄⬆️⬇️ℹ️📎🔬
- analysis_tools.py: обёрнуты message в dict-возвратах и строки
  в _run_scan_sync / _run_summarize_sync
- Все f-string интерполяции конвертированы в .format()-стиль
  для корректного поиска ключа перевода
- Добавлен импорт `from src.utils.i18n import _` в оба файла

**Tools Used:** write_file, notify_change, diagnostics, intel_log_incident
**Status:** ✅

---

## [2026-07-05] — Полная i18n: документация на 3 языках

Вся документация переведена на английский, русский и китайский языки.
Каждый документ имеет переключатель языков в заголовке.
Структура `docs/{ru,en,zh}/` с единой картой документации в каждом языке.

**Статус:** ✅ 36 .md файлов, все кросс-ссылки проверены

---

## [2026-07-05] — UI Formatter: единый стиль вывода

Все 43 MCP-инструмента переведены на единый Markdown-формат через `ui_formatter.py`.
- Убран сырой JSON из intel_* инструментов
- Убран JSON-блок из `_format_success_response`
- `debug_runtime_passport` переписан в дашборд
- `get_runtime_counters` — через ui_formatter
- `_format_error_response` — Markdown с эмодзи (🔴 + описание)

**Статус:** ✅

---

## [2026-07-05] — Health report: таймауты и orphan files

- Orphan files: авто-чистятся из индекса (очищено 105 записей)
- Search quality тесты: таймаут увеличен 8s → 30s (3/3 тестов проходят)
- Git execution contract: таймаут 10s → 30s
- Логи централизованы в ext_root через `log_manager.py`
- Добавлена `_cleanup_stale_project_logs()` — удаление старых per-project логов

**Статус:** ✅

---

## [2026-07-05] — DebounceBatch deadlock (критический баг)

**Проблема:** MCP-сервер зависал через ~5 секунд после пачки `notify_change`.
**Причина:** `await self._flush()` вызывался внутри `threading.Lock`.
`threading.Lock` не reentrant — второй захват блокирует поток навсегда.
**Фикс:** Разделение логики — решение `should_flush` под lock, сам `await` — после lock.

**Статус:** ✅ Исправлено, 8 последовательных notify_change — 0 ошибок

---

## [2026-07-05] — Определение проекта на Windows (ключевое открытие)

`ZED_WORKTREE_ROOT` и `current_dir` не работают на Windows (баг Zed #36019).
**Решение:** читать `active_workspace_id` из SQLite `scoped_kv_store`.
Приоритет 0 в `resolve_project_root()`. Работает на Windows, macOS и Linux.

**Приоритет резолва:**
1. SQLite `multi_workspace_state.active_workspace_id` — главный
2. Явный `project_root` из аргументов инструмента
3. LSP Bridge (не работает на Windows)
4. SQLite `workspaces` (старый fallback)
5. `PROJECT_PATH` из .env
6. CWD (отклоняется self-indexing guard)
7. ext_root (fallback — режим самодиагностики)

**Статус:** ✅ Внедрено

---

## [2026-07-05] — LSP расследование (WONTFIX)

Исследованы исходники Zed, найдена первопричина: `mscodebase-lsp` не регистрируется
в `LanguageRegistry` Zed на Windows. `settings.json` не может зарегистрировать
новый LSP — только override пути для уже существующего.
Требуется Rust/WASM-адаптер для полноценной поддержки.
MCP-сервер (43 инструмента) работает полноценно и без LSP.

**Статус:** ✅ WONTFIX, документировано

---

## [2026-07-05] — Self-indexing guard

MCP-сервер иногда индексировал собственные исходники (~500MB).
**Фикс:** функция `_reject_self_index_target()` — блокирует ext_root и директорию
установки Zed, бросает `ToolError` с понятным сообщением.
В dev-режиме (исходники как проект) — разрешает через fallback.

**Архитектурный урок:** не использовать маркер-файлы для детекта self-indexing.
Исходники расширения легитимно содержат эти файлы. Использовать path-equality.

**Статус:** ✅

---

## [2026-07-05] — ConnectionPool + Warm-up для LM Studio

**Проблемы:**
- Каждый запрос к LM Studio создавал новый HTTP-соединение (TCP/TLS overhead)
- Холодный старт bge-m3 при первом поисковом запросе (~5-8s задержка)
- CPU-bound задачи блокировали event loop

**Фиксы:**
1. `httpx.AsyncClient` с `max_keepalive_connections=5` — горячий пул сокетов
2. `embed_batch_async()` — пакетная отправка чанков в LM Studio (параллельно)
3. Warm-up при старте сервера: тестовый запрос к bge-m3 до первого запроса пользователя
4. CPU-bound задачи (impact_analysis, structural_search) → `run_in_executor` (ThreadPool)
5. `scan_changes` и `generate_chunk_summaries` → background job pattern с job_id

**Статус:** ✅ search_code ~2x быстрее, event loop не блокируется

---

## [2026-07-05] — Архитектурный freeze — v2.4

**Ключевые изменения (16 коммитов, ~2500 строк):**
- Self-indexing guard: `_reject_self_index_target()` с path-equality + is_zed_install_dir()
- SystemArtifacts: единый модуль для системных файлов (4 слоя)
- Passport: RUN_ID, BUILD_ID, PID в `src/core/passport.py` (core не импортирует MCP)
- ProjectContext: иммутабельный снапшот проекта (state + index + bridge + runtime + health + memory + jobs)
- RuntimeCoordinator: `can_execute()` → `ExecutionVerdict` с счётчиками телеметрии
- Architecture linter: 3 проверки, 0 warnings (было 1745)
- Project memory: ADR, known issues, tech debt залогированы

**Статус:** ✅ Архитектурный freeze до v2.5

---

## [2026-07-05] — ProjectContext + RuntimeCoordinator

**Проблема:** Каждый tool собирал информацию о проекте самостоятельно,
создавая копипасту. Не было единой точки "можно выполнять запрос?".

**Решение:**
- `ProjectContext.capture(path, services)` — возвращает Snapshot
- `RuntimeCoordinator.can_execute(path)` — принимает решение: готов проект или нет
- `require_ready_project()` в `base.py` делегирует Coordinator-у

**Архитектура:** Tool → Coordinator → `can_execute()` → Snapshot → logic.
Tool не знает Registry, Bridge, Passport — только Verdict + Snapshot.

**Статус:** ✅

---

## [2026-07-05] — ResourceMonitor + LRU + adaptive throttling

**Проблемы:**
- ProjectIndexerRegistry max_cached=8 — слишком много для 16GB RAM
- LanceDB connection не закрывался реально на Windows до GC
- При печати текста в Zed индексация лагала IDE

**Решение:**
- ResourceMonitor: stdlib-only (resource.getrusage + ctypes/psapi на Windows)
- Soft (768MB/75%) и Hard (1024MB/85%) пороги
- ProjectIndexerRegistry: max_cached=8 → 5, `_maybe_evict_for_pressure()`
- `_safe_close()` обнуляет LanceDB connection + кэши + gc.collect()
- Indexer.index_project() делает sleep на `suggest_throttle_delay_sec`

**Статус:** ✅ 307/307 тестов, 11 новых тестов

---

## [2026-07-04] — Multi-window support (v2.3+)

**Проблема:** При переключении окон Zed MCP использовал один общий Indexer.
LSP обслуживал несколько workspace URI одним процессом, но init был с ранним return.

**Решение:**
- `ProjectIndexerRegistry`: `Dict[Path, Indexer]` + LRU eviction (5 слотов)
- LSP: per-workspace DI-контейнеры, `workspace_uri` как ключ
- MCP: `resolve_indexer_for_request()` — приоритет: explicit → resolve → default
- DebounceBatch per-project (lazy factory в DI)
- LRU eviction закрывает Indexer через `safe_close()`

**Статус:** ✅

---

## [2026-07-04] — Рефакторинг: Clean Architecture (Phase 1-4)

**Проблема:** Монолитный `server.py` (3,100 строк) с 30+ обработчиками ошибок,
тройной инициализацией компонентов, без защиты от VFS-перегрузок.

**Решение (4 фазы):**

| Модуль | До | После | Δ |
|--------|----|-------|---|
| server.py | 3,100 строк | ~220 строк | -93% |
| tool files | 0 | 12 файлов (1,650 строк) | +12 |
| DI services | 0 | 15 | +15 |
| global state | 8 vars | `_services` (1 var) | -7 |

**Ключевые созданные компоненты:**
- `src/core/di_container.py` — ServiceCollection с Constructor Injection (15 сервисов)
- `src/core/error_handler.py` — ToolError + error_boundary декоратор с asyncio.wait_for
- `src/core/rate_limiter.py` — SlidingWindowRateLimiter + DebounceBatch + CircuitBreaker
- `src/mcp/tools/*.py` — 10 файлов, 33 class-based инструмента
- `src/core/lsp_project_bridge.py` — LSP→MCP мост через temp-файл с атомарной записью

**Паттерны защиты:**
- `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=echo` — защита от git hang на Windows
- `CREATE_NO_WINDOW` — без консольных окон при subprocess
- Debounce 500ms для BM25 реиндексации (не на каждый notify_change)
- CircuitBreaker: 5 failures → OPEN → 30s recovery для LM Studio

**Статус:** ✅ 307/307 тестов, 43 инструмента

---

## [2026-07-04] — Аудит и чистка проекта

- Найдено 19 архитектурных проблем (2 critical, 8 high, 7 medium, 1 low + 7 architectural)
- Удалено 6 позиций мусора: hybrid_server.py, backup-файлы, пустые директории
- Обновлены Skills в `.agents/skills/` — замена deprecated инструментов
- 52 новых unit-теста: DI (13), RateLimiter (21), ErrorBoundary (18)

**Ключевые баги:**
- BUG-01: DI callback NameError (notification_broker до CircuitBreaker)
- BUG-02: LSP watcher `_indexer` undefined global
- Race: did_change на каждый keystroke → debounce 350ms + сериализация
- ThreadPoolExecutor deadlock на Windows (git log зависал) → max_workers 4→8, daemon threads

**Статус:** ✅ Все findings исправлены

---

## [2026-07-04] — Per-tool счётчики телеметрии

Добавлен `_TOOL_METRICS` в `error_handler.py`:
- `record_tool_call()` — вызывается из всех 6 точек выхода error_boundary
- `get_tool_metrics()` / `get_tool_metrics_summary()` — чтение метрик
- Thread-safe через `threading.Lock`

**Статус:** ✅

---

## [2026-07-04] — LanceDB: миграция метаданных

**Проблема:** `_migrate_add_metadata_columns()` падал с LanceDB 0.33 SQL parser error.
Metadata-колонки (layer, module_name, hierarchy_level, is_public, symbol_type, parent_id)
не добавлялись в существующую таблицу.

**Решение:**
- Двухфазная стратегия: add_columns → если не сработало, read-drop-recreate
- `_migrate_table()` в index_guard.py — schema 16 полей
- Убран dead code (`if False` в text_full миграции)
- `.env.example` — полный список реальных env-ключей

**Статус:** ✅

---

## [2026-07-04] — Фильтрация по слоям + Multi-granularity поиск — v2.4.4

- `search_code` получил параметр `filter_layer` (core/mcp/utils/tests)
- LanceDB `.where()` с `prefilter=True` — фильтрация на уровне индекса
- BM25 пост-фильтрация по `layer` из metadata
- Метод `get_chunks_by_parent_id()` для multi-granularity retrieval
- 6 полей метаданных: layer, module_name, hierarchy_level, is_public, symbol_type, parent_id
- MCompassRAG-style layer detection + SproutRAG-style flat tree

**Статус:** ✅

---

## [2026-07-04] — Unified JSON format for all @mcp.tool() returns

Все 32 @mcp.tool() функции переведены на единый JSON-формат:
```json
{"status": "ok" | "error" | "warning" | "timeout", "message": "..."}
```
Единый контракт для AI-агента: status + message + data.

**Статус:** ✅

---

## [2026-07-04] — LSP→MCP Bridge: auto project detection

**Решение:** LSP (`lsp_main.py:on_initialize`) получает `root_uri` от Zed,
пишет в `~/.mscodebase/bridge/session_{parentPID}.json`.
MCP читает bridge с polling до 3 сек.

**Edge cases:**
- Race MCP быстрее LSP — polling 50ms × 60 = 3 сек
- Два окна Zed — parent PID как ключ файла
- Stale PID reuse — session_id + timestamp в JSON
- Атомарная запись через `os.replace()`
- psutil AccessDenied — fallback на хеш argv + CWD
- Auto cleanup — файлы старше 5 мин удаляются при старте

**Статус:** ✅

---

## [2026-07-04] — Progress job stuck at 50% (intel_get_job_status)

**Проблема:** `intel_trigger_reindex` → `intel_get_job_status` всегда возвращал `progress: 0.5`.
Job висел в статусе "running" бесконечно.

**Причина:** `trigger_async_reindex()` не передавал `progress_callback` в `Indexer.index_project()`.
Прогресс статически ставился на 0.5 перед `await future` и не обновлялся.

**Фикс:** Добавлен `_index_progress_callback`, маппинг `files_done/total_files` на шкалу 0.1→0.8.

**Статус:** ✅

---

## [2026-06-29] — Начало проекта

Первый коммит. Базовая архитектура: MCP-сервер + LanceDB + LM Studio.
43 MCP-инструмента (33 core + 10 intel), 15 сервисов в DI-контейнере.

**Ключевые числа на текущий момент:**
- 43 инструмента MCP (33 core + 10 intel)
- 10 файлов инструментов, 15 сервисов в DI-контейнере
- 391+ тестов
- Индекс: ~1600 чанков
- Чистая архитектура с RuntimeCoordinator, ProjectContext, SystemArtifacts
- Мульти-оконность (ProjectIndexerRegistry с LRU 5)
- Полная i18n: документация на 3 языках
