# KNOWN ISSUES — MSCodeBase Intelligence

> Синхронизируется из `AGENT_DIARY.md` при каждом [🏁 ИТОГ].
> Формат: дата | что было | статус | fix

---
---
## 2026-11-17 — `.json` в индексе: 62.5% объёма и ноль пользы для кода — 🟢 закрыто

- **Вопрос:** нужны ли `.json` в индексе вообще. Замер: `.json` — 31 123 чанка из
  49 920 (**62.3%**), все из fallback-ветки (AST JSON не парсит: нет грамматики,
  `.json` нет в `PARSE_EXTENSIONS`, language-pack 53 языка JSON не содержит).
- **Ответ (замер на полном корпусе 2 134 файла):** без `.json` — `18 747` чанков
  (−62.5%), `143 MB` вместо `287 MB` (−50%), `6.0` мин вместо `6.8`, символы
  `36 589` без изменений. Код не тронут: `.py` 16 380 и `.js` 1 397 — те же числа,
  пропали ровно 375 `.json`-файлов. hit@1 `7/8` — как и при капе 20 (единственная
  «потеря» — запрос `coding_memory_v1`, нацеленный на сами данные датасета).
- **Решение:** `MSCODEBASE_INDEX_DATA=0` по умолчанию — данные не индексируются;
  `=1` возвращает их (с капом `MSCODEBASE_MAX_FALLBACK_CHUNKS`). `.ipynb` остаётся:
  это JSON, но чанки из разобранных code-cells. `grep_code` и `read_live_file`
  читают диск и `.json` находят при любом флаге.
- **Цена:** поиск по содержимому данных (`search_code`) их больше не видит; кому
  нужно — флаг + полная переиндексация после удаления `<проект>/.mscodebase/chunks.db*`
  (хеши не меняются, инкремент файл пропустит).
- **Guard:** `tests/test_data_files_not_indexed.py` (5 тестов), мутации M60–M62.

## 2026-11-17 — 62% индекса engraphis — данные, а не код: кап fallback-чанков — 🟢 закрыто

- **Симптом:** один `eval/datasets/coding_memory_v1/runtime.json` давал 1 146 чанков;
  `search_code` тащил датасеты в топ вместо кода.
- **Корень (замер по индексу):** `.json` = 31 123 чанка из 49 920 (**62.3%**) — все
  fallback-ветка (AST такие файлы не разбирает). Код (`21`) и docs — остальное.
- **Fix:** `MSCODEBASE_MAX_FALLBACK_CHUNKS` (default `20`) режет fallback-чанки на
  файл; AST-чанки кода не капаются никогда. В последний чанк пишется строка
  `// NOTE: fallback chunks truncated — N of ~M indexed` — обрезка видна в выдаче
  (metadata не годится: `db_writer` сохраняет только известные поля). Смена значения
  требует полной переиндексации: хеши файлов не меняются, инкремент файл пропустит.
- **Замер A/B, полный корпус 2 134 файла (зеркало на hardlink'ах):**
  `49 920 → 25 209` чанков (−49.5%), `287 → 172 MB` (−40%), символы
  `36 589 → 36 589` (AST-слой цел), время `6.8 → 6.5 мин` (−4%: парсинг, а не объём
  записи, — узкое место), hit@1 `8/8 → 7/8`.
- **Цена (измерена):** единственная потерянная выдача — запрос `coding_memory_v1`
  (нацелен на сами данные датасета): вернул пусто вместо `oracles/*.py`. Строка из
  глубины файла (`forbidden:atlas-north:sibling`) была в 27 чанках живого индекса и
  **в 0 чанках** с капом — данные за 20-м чанком из индекса исчезают. `grep_code` и
  `read_live_file` работают по диску и файл находят; это и есть замена для таких
  запросов. Обрезано 291 файл.
- **Guard:** `tests/test_fallback_chunk_cap.py` (5 тестов), мутации M56–M59.

## 2026-11-17 — индексация engraphis 27 минут: commit на каждую запись графа — 🟢 закрыто

- **Симптом:** полный text-only индекс 2 138 файлов шёл 26.9 мин (49 920 чанков).
- **Корень (замер):** граф писался по одной записи: `add_node/add_edge` делают
  BEGIN/commit на каждую, `graph.db` — `synchronous=FULL`. Замер: **288 записей/с**
  → 214 804 записи = **12.4 мин** только граф. `PropertyGraph.batch()` (одна
  транзакция, ~67k/с) существовал с 2026-09-25, но text-only путь его не вызывал.
  Плюс `DELETE ... WHERE file_path` без индекса (SCAN) — исправлено отдельно (PR #152).
- **Fix:** text-only оборачивает файл в `graph.batch()` (`MSCODEBASE_GRAPH_BATCH=0`
  возвращает старое поведение). Если все файлы упали — прогон падает, а не
  рапортует «done: 0 files».
- **Замер после:** 300 файлов engraphis — **195.1 с → 28.8 с (6.8x)** при
  идентичных чанках/символах; экстраполяция на корпус ~3.5 мин.
- **Guard:** `tests/test_text_index_batch.py` (3 теста), мутации M53–M55.

## 2026-11-17 — read-only второго сервера был невидим — 🟢 закрыто

- **Симптом:** 621 строка `База занята другим процессом MCP — работаю read-only`
  и 280 `PID lock held`, при этом `get_health_report` отдавал `issues: []`,
  `write_capable` не существовало. Агент не понимал, почему запись/индексация
  не работают.
- **Корень:** `_startup_issue` жил только в `db_manager` и попадал лишь в
  человеческий startup-отчёт; health его не читал, автоиндексация запускалась
  и падала на `begin_write` (RuntimeError без кода).
- **Fix:** `ErrorCode.DATABASE_LOCKED` + `DatabaseLockedError` (status=warning,
  recoverable, detail с действием); health добавляет issue `database_lock`,
  `metrics.write_capable=false` и `auto_index: skipped: <причина>`;
  `auto_index_block_reason()` не даёт запускать индексацию в read-only.
- **Guard:** `tests/test_write_capability.py` (5 тестов), мутации M43–M46.

## 2026-11-16 — старт сервера и символьный слой JS — 🟢 закрыто

- **PID-lock:** второй сервер того же проекта ждал живого держателя 8 с
  (`initialize` 10–15 с). Fix: `DatabaseLock.acquire(wait=False)` на старте (read-only
  сразу, запись берёт лок с ожиданием). `create_mcp_server` 10.5 → 2.2 с,
  `initialize` p50 6365 → 2521 мс. Guard: `tests/test_pid_lock_no_wait.py`.
- **«В JS мало символов» — не дефект (измерено):** 665/49 файлов в `chunks.db` — это
  доки/JSON/картинки. Кодовых: MSPortfolio 82 → 425 узлов (113 Function, 66 Interface),
  ghost-rovers 8 → 327 (114 Function); свежий JS-проект (7 файлов) → 68 узлов.
  Guard: `tests/test_js_symbols.py` (мутация «не извлекать JS/TS» → 2 failed).

---
---
## 2026-11-15 — `C:\Windows\.mscodebase`: индекс ОС на 105 МБ — 🟢

- **Симптом:** в `C:\Windows` появился `.mscodebase\chunks.db` (105 МБ, 10 264
  чанка системных файлов), в профиле — ещё 376 МБ; каталоги не удалялись
  обычными средствами, пока сервер держал БД.
- **Корень (по логам, `RUN_ID e77c87a6e138`):** хост запустил MCP-сервер с
  `cwd=C:\Windows` и `PROJECT_PATH='${workspaceRoot}'` (неразвёрнутый
  плейсхолдер). Плейсхолдер не отличили от пути → fallback на CWD →
  CWD-first резолвер вернул `C:\Windows` → автоиндексация пошла по системе →
  `get_chunks_db_path()` положил БД внутрь корня.
- **Fix:** `is_forbidden_root()` (системные корни, корни дисков, профиль, temp)
  режет резолвер и `get_chunks_db_path`; `is_project_root()` (`.git`,
  `pyproject.toml`, `package.json`, …) обязателен для автоиндексации; env со
  `${…}`/`%…%` теперь WARNING и `None`.
- **Guard:** `tests/test_root_guards.py` — 20 тестов; мутации
  (`if False` вместо трёх проверок) красят по одному тесту каждая.
- **Уборка:** удалены `C:\Windows\.mscodebase` (105 МБ), каталог индекса в
  профиле (376 МБ), `<repo>\.mscodebase` и temp-пробы.

---

---
## 2026-11-15 — консольные окна: 135 вызовов subprocess без флага — 🟢

- **Симптом:** на Windows при работе сервера/тестов мигают окна `cmd`.
- **Корень (измерено):** у процесса-родителя нет консоли, поэтому каждый bare
  `subprocess.*` создаёт СВОЮ консоль. В `src/ tests/ scripts/` таких вызовов
  было **135 в 57 файлах**; `src/core/silent_subprocess.apply()` патчил только
  процессы, которые его импортировали, а импортировал ровно один entry-point
  (`src/main.py`).
- **Fix:** `creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)` во всех 135
  местах; `src/remote_main.py` и `src/cli.py` тоже применяют `silent_subprocess`;
  guard `tests/test_no_console_windows.py` (AST-скан каталогов) краснеет на
  любом новом bare-вызове.
- **Отдельно (вне репозитория):** MCP `mobile-mcp` в конфиге OpenCode запускается
  как `npx -y @mobilenext/mobile-mcp@latest` → `cmd.exe` на каждый старт сессии.
- **Открыто:** `scripts/live_search_audit.py` не парсится (битый отступ, было до
  этой задачи) — исключён из скана явным allowlist, чинить отдельно.

---

## 2026-11-13 — slow-тесты прятали смену хранилища: 5 красных в `test_freshness_checker` — 🟢

- **Измерено:** на `main` (`a6524d6`, `801621d`) `pytest tests/test_freshness_checker.py -m "not benchmark"` → `5 failed, 2 passed`; в дефолтном гейте файл не виден (`pytestmark = pytest.mark.slow`).
- **Корень:** тесты читали `indexer.table` (LanceDB), а дефолт — SQLite (`src/core/indexing/indexer.py:146-154`, `SearchConfig.sqlite_chunks=true`); запись шла в `SQLiteChunkStore`, таблица LanceDB пустая.
- **Не регресс Цели 1/2:** те же 5 падают на до-мержевом `main` `a6524d6`.
- **Fix (PR #126):** чтение через `_file_rows()` (слой, который реально используется) + `test_store_is_the_default_one` пиннит дефолт; `slow`-маркер снят (файл 4.2 s). Проверка: `8 passed` 3× подряд; мутация `verify_index_freshness → return 0` даёт `4 failed`; гейт `2518 passed, 0 failed`.

---
## 2026-11-11 — E73: что осталось открытым после снятия ложного отказа — 🟡

- **Измерено на `sqlalchemy` (40 решаемых коммитов, база `8b62343`):** до фикса
  пустых ответов 13; после — 6 восстановлены, 2 отказа законны, 4 промаха
  ранжирования, 0 потерь от гейта доказательств.
- **Законные отказы (2):** `749086adb0cc`, `049ed1db162a` — у обоих все
  идентификаторы по нулям (`mapped_column.default_factory=0`,
  `mapped_column.default=0`); это политика C (E69), не дефект.
- **Промахи ранжирования (4):** `65ea6bee8214`, `98ad157d6334`, `975ffa7d77ee`,
  `956a0235027e` — в ответе 8 строк, gold вне top-5.
- **Заявленные «2 дропа evidence-gate» не воспроизвелись:** разница
  bypass-прогона (8/13) против фикса (6/13) — это ровно те два случая с нулями.
  Чтобы поймать отбрасывание строки самим гейтом, нужен замер с
  инструментированием `kept` — он не делался.
- **Перевывод:** `python experiments/false_abstain_2026_11/verify.py --corpus <bench>/sa-B
  --repo <bench>/sqlalchemy --base 8b62343 --panel experiments/scale_2026_11/tasks.jsonl`
  печатает per-task `hit@5` и список пустых; все id выше — его вывод
  (`<bench>` — каталог с клонами, команды клонирования в
  `experiments/bench_2026_11/REPORT.md`).

---
## 2026-11-09 — pre-commit: `gate_cli.py --selftest` правит трекнутый манифест — 🟡

- **Симптом:** после `git hook run pre-commit` изменён `tools/verification/denominator_manifest.json`
  (9 строк `n_sig1`/`n_sig2`), хотя коммита не было.
- **Root cause:** `scripts/gate_cli.py --selftest` прогоняет heldout-дефекты на РЕАЛЬНОМ
  манифесте и сохраняет пересчитанные счётчики; `.githooks/pre-commit` вызывает его на каждом коммите.
- **Следствие:** рабочее дерево грязное после каждого коммита; сгенерированные числа можно
  закоммитить как ручные.
- **Fix (сейчас):** изменения откатаны (`git checkout -- tools/verification/denominator_manifest.json`).
- **Guard (нужно):** selftest на `tempfile`-копии манифеста + тест «после selftest
  `git status --porcelain` по манифесту пуст».

---
## 2026-11-08 — `investigate`: пять причин, почему E1 был отрицательным — 🟡 (четыре закрыты)
Разбор сырых ответов (`experiments/xerj_2026_11/WHY.md`) вместо пересказа балла.

**Закрыто:**
- **Семантический канал не доходил до ответа.** `hybrid_search_async` отдаёт
  `{text, metadata, final_score}`, путь лежит в `metadata`, код читал
  `file_path`; `_merge` молча выбрасывает строки без файла. 0 хитов `search`
  против 129 от остальных каналов на 24 задачах, без `degraded`.
- **Сортировка по числу каналов** (`(len(channels), rank)`) — согласие как
  первичный ключ; противоречило нашему же E3-правилу D. Теперь `(rank, channels)`.
- **Несравнимые шкалы:** `final_score` 10.32 против веса определения 2.5 —
  чанк, где символ лишь упомянут, обгонял его определение в 4 раза. Оценка стала
  ранговой `1/(idx+1)`.
- **Точное имя не искалось точным индексом:** `search_symbols("Signer")` на
  itsdangerous возвращал `HMACAlgorithm`. Теперь первым идёт
  `find_definitions` (def-first, как correct-file@1 у XERJ).
- **Мелочи:** PascalCase не считался кодом (`token[1:]`), абсолютные и
  относительные пути не схлопывались в одну строку, `defined`/`Who` тратили слоты.

**Замер:** внешний корпус (2 пина, 12 задач) — definition rank-1: grep 0.222 →
investigate 1.000; callers 0.000 у обоих (B ведёт самовызовом в файле определения,
gold такие исключал). Свой E1: positive 0.438 → 0.786 (только починка канала) →
0.625 (полная настройка); overall 0.522 → 0.545 → 0.500.

**Открыто:**
- Нужны два профиля весов по интенту (definition vs exploratory): def-first
  выигрывает precision на внешнем корпусе и теряет recall на нашем. Решение не
  принято — нужен прогон на обоих корпусах.
- `find_definitions` иногда помечает место вызова как определение (P02:
  `graph_rag.py:93`) — шум для `exact:` и callers-демоции.
- При `exact: 0` инструмент всё равно печатает 8 «соседей»: по замороженному
  правилу это ложное «нашёл». Кандидат — не печатать соседей без явного флага.

---
## 2026-11-08 — CI `clean-state` иногда идёт 13m30s — 🟡
Замер (не «по ощущениям»): job `128772053549` — 13m29s, job `128797932683` — 13m31s,
остальные прогоны той же джобы — 2m10s. В логе второго прогона — **743.7 s тишины**
внутри шага «Running full test suite (no filters, parallel)» (`--durations` там не
печатался, поэтому какой тест — неизвестно). Причина не установлена; версия «медленный
runner» не объясняет двух прогонов с точностью до 2 s.
Сделано: `--durations=15` в `scripts/verify_clean_state.sh` (следующее повторение
назовёт тест) и `timeout-minutes: 15 → 25` — иначе 13m31s при медленном раннере
превращается в красный `main` без падения теста.

---
## 2026-11-08 — XERJ-пакет: run по протоколу (research / эксперимент / внедрение) — 🟡
Пакет `experiments/xerj_2026_11/`: добавлены `DECISION.md`, `RESEARCH.md`,
`baseline_raw.txt` + `run_baseline.py`, `tests/test_no_silent_success.py`.
P0-5 (`pyproject.toml`) проверен командой — уже исправлен ранее (`check_metadata.py`, 6/6).

Закрыто в этом прогоне:
- `investigate` терял grep-канал на своём же репозитории: `_search` парсил tree-sitter'ом
  каждый файл даже при нуле совпадений → 23.0 s и `degraded: grep:timeout` на каждом
  запросе. Добавлен prefilter по regex до парсинга (`grep_tool.py`); набор совпадений не
  изменился (P01: 30 matches до и после). In-process: 7.2–8.1 s, канал живой.
- `investigate` больше не выдаёт «соседей» за ответ: в шапке `exact: <ident>=N`, а при
  нуле совпадений по субъекту — предупреждение «results below are neighbours, not
  matches». Guard: `tests/test_no_silent_success.py` (5 из 8 падали на коде до правки).

Открыто (новое, из этого прогона):
- **Таймаут канала не отменяет поток.** `asyncio.wait_for(asyncio.to_thread(...))`
  снимает ожидание, но работа продолжается. В долгоживущем процессе (MCP-хост) каждый
  таймаут оставляет живой парсер: следующие вызовы идут медленнее, и замер после
  нескольких таймаутов недействителен. Наблюдено: 24 задачи в одном процессе,
  `grep:timeout` → 22–30 s на последующих. Нужен либо cooperative-cancel в каналах,
  либо отдельный executor с учётом зомби. 🟡
- **CLI-мост не умеет project-scoped инструменты.** `python -m src.cli investigate …`
  всегда отдаёт `project_not_ready (state=UNINITIALIZED)` за ~5 s: реестр проектов
  инициализируется только в MCP-хосте. Поэтому бенчмарк гоняется in-process с
  примированием реестра; `investigate` в allowlist не добавлен, чтобы не публиковать
  заведомо нерабочий путь. 🟡
- **E1 вердикт отрицательный:** plain grep 0.667 vs investigate 0.500 на 24 frozen
  задачах (N=1, in-process, valid-rate указан в `baseline.json`). Фальсификатор из
  `PLAN.md` сработал: заявлять «investigate лучше» нельзя. 🟡

---
## 2026-11-08 — Аудит планов: что реализовано, что осталось — 🟡
Проверены все планы (`ISSUE.md`, `docs/research/*PLAN|patterns|chain*`, `docs/ISSUES/*`).
Реализовано и подтверждено кодом: Universal Engine Ф1–Ф4 (sources, plugins, transport-e2e,
manifest-parity), `TrustBoundary`, modification-guard (HMAC `ack_impact` + `bind_partial`),
`run_bounded`/IVF-guard, `blocked`-пути индексатора.

Открыто (каждое — отдельная задача, не «шум»):
- docs-канал: hit@1 0.000 при same-basename 0.750 (E47/E51/E52/E55/E56) — единственный
  открытый пользовательский дефект поиска.
- Multi-client write (R-8/E-10): workspace-lock в `src/remote_main.py` нет.
- `scripts/audit_protocol_guards.py` не в CI; `--cov-fail-under=38`; mypy/bandit нет.
- ADR-0006: `call_hierarchy`/`semantic_tokens` без потребителей (0 вызовов в `src/`).
- `tools/factory/` — прототип «фабрики задач» (2026-10-25): 18 тестов зелёные,
  `tests/test_factory.py`; в продукт **не** встроен (не MCP-тул, не импортируется из
  `src/`). Судьба — за владельцем: встроить как отдельный инструмент или перенести в
  `experiments/`.

Архивировано 2026-11-08 (не удалено): `docs/ISSUES/*`, `docs/research/2026-07-*`,
`docs/{en,ru,zh}/{HANDFOFF,ARCHITECTURE_LAYERS,ARCHITECTURE_DEEP}.md` — см.
`docs/archive/README.md`. `pyproject.toml` метаданные (57 tools, classifiers 3.10–3.12)
исправлены там же.

---
## 2026-10-25 — E55/E56: chain modes; docs gold-language bottleneck — 🟡
- **E55:** hybrid/quality/deep 0.688/0.771 (p50 45–48 ms); fast 0.542/0.729
  (p50 19 ms); `nodemote/intent/ru/p3` — 0 эффекта на hit@1.
- **E56:** exact-path docs_only 0.021/0.062; **translation-normalized docs_only
  0.750**, oracle **0.812/0.917**; p50 131 ms. BM25 отдаёт `docs/ru/X.md` при
  gold `docs/en/X.md` — это **gold canonicalization**, не слабый docs-канал.
- **Дешёвый путь:** explicit `intent="docs"` + docs-only FTS (без LLM-router).
  Параметры `demote/intent/ru/p3` на панели не помогают.
- **Реализовано:** `Searcher.search_docs()` + `search_code(intent="docs")`;
  exact 1/8, same-basename **6/8**; тест `tests/test_search_docs.py`.
- **Добавлено:** language-dedupe (ru/en/zh → один документ, prefer query lang)
  + `delete_files()`/prune в `scripts/reindex_text_only.py`.
- Production: graph 12,753 nodes; index 7,314 chunks (0 experiments); tests 32 pass.

---
## 2026-10-25 — E52: clean baseline — hit@1 0.688, hit@5 0.750; docs=0 — 🟡
- Clean index: 7,258 chunks (удалено 9,089 experiments); leakage 0/48.
- **clean production 0.688/0.750** (p50 72ms); contaminated 0.688/0.771.
  **Supersede:** hit@5 0.771 → 0.750; hit@1 не изменился.
- Subsets clean: code 0.825/0.900, docs 0.000/0.000.
- **Oracle router** (code 0.825 + docs-only BM25 0.75) = **0.8125 hit@1 /
  ~0.9167 hit@5**. 95% требует усиления code-канала или LLM-агента.

---
