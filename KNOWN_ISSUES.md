# KNOWN ISSUES — MSCodeBase Intelligence

> Синхронизируется из `AGENT_DIARY.md` при каждом [🏁 ИТОГ].
> Формат: дата | что было | статус | fix

---
---
## 2026-11-24 — рантайм-метрики были трекнуты: каждый запуск сервера грязнил дерево — 🟢 закрыто

- **Симптом:** `M telemetry/tool_metrics.json` после любого запуска MCP из репо;
  в HEAD файл пустой (`{}`), в рабочем — 62 строки метрик.
- **Корень:** `server_factory.py:248` пишет `_ext_root/telemetry/tool_metrics.json`
  каждые 10 вызовов и на `atexit`; в dev `_ext_root` = репозиторий, файл трекнут.
- **Fix/Guard:** `git rm --cached` + `.gitignore` (`...json`, `.tmp`), runtime-путь
  не менялся; `test_runtime_metrics_file_is_not_tracked` красный до untrack.
- **Проверка:** 6/6 guard-тестов; `git status` файл больше не показывает.

## 2026-11-24 — тесты писали в CWD и в реальный data root — 🟢 закрыто

- **Симптом:** в корне репо и install-root — `MagicMock/mock.project_path/<id>/.mscodebase/chunks.db`
  (491 файл / 16.3 MB на дерево); один прогон suite добавил 672 строки `MagicMock`
  в реальный `D:\mscodebase-data\logs\mcp_global.log`.
- **Корень:** `Searcher.__init__` строил `SQLiteChunkStore(get_chunks_db_path(indexer.project_path))`
  без проверки типа; `MagicMock` проходит как `os.PathLike` (фейковый `__fspath__`).
  Лог-хендлер биндился один раз и не переезжал при смене `MSCODEBASE_DATA_DIR`.
- **Fix:** `engine.py` — только `str|PurePath` (пустая строка отклоняется);
  `log_manager.py` — ключ `project|log_file`, project-scoped снятие/закрытие
  старого хендлера под `threading.Lock`; `conftest.py` — session-temp data root
  до collection; `.gitignore` — `MagicMock/`.
- **Проверка/Guard:** 5 guard-тестов; 3 мутации (store целиком, без close,
  без A→B→A) красят; suite 2902 passed / 12 skipped (437 s), slow 88/4;
  5 «грязных» файлов из temp-CWD — 47 passed, 0 файлов в CWD, +0 строк в логе.
- **Открыто:** `scoring.py:300-302` (`CommitMemory`) и `engine.py:2345-2346`
  (`_Path(root)`) тоже доверяют `indexer.project_path` — проверки типа нет.

## 2026-11-18 — аудит ответов на чужом корпусе: 6 дефектов, 5 закрыто, 1 открыт

- **Как проверяли:** 5 вопросов к `engraphis` через MCP, каждый ответ сверен с
  исходниками на диске (не через индекс) — отчёт `audit_engraphis_2026_11_18.md`.
- **Найдено:** `get_symbol_info("intent_recall")` — «1 defs, 3 callers», реально
  3 определения и 4 вызова (вызов из `scripts/` отбрасывался молча); «15 callers» —
  это `min(total, 15)` без глубины (у `recall` 233); `_DESTRUCTIVE_PATTERNS`
  (переменная) — «0 callers», читается как «не используется»; `reweight` —
  «10 definitions» из подстрочного поиска при нуле точных; `investigate` выдавал
  4 строки `RecallEngine — name match` по чанкам методов (`// Context:`) и
   `SYMBOLS:`-шапке (54% чанков выборки совпадают только по шапке);
  `graph_query(action="related", target="intent_recall")` — `✅ Completed … []`.
- **Fix:** все одноимённые узлы в `definition` (первый — выбор ранжирования,
  остальные перечисляются как AMBIGUOUS); прямые/транзитивные счётчики раздельно
  и «скрыто N из scripts/»; для не-вызываемых видов — «граф вызовов не применим»;
  подстрочные совпадения — «похожие имена», не определения; канал `name` строит
  строку по определению (`symbol_name == variant`), контекст — ≤2 и только если
  определения нет; `related` валидирует файл и называет ожидаемый вид.
- **Замер после:** `intent_recall` → 3 defs + AMBIGUOUS + «скрыто 1»;
  `_DESTRUCTIVE_PATTERNS` → «не применимо»; `reweight` → «точного нет, похожие»;
  `investigate` → `verdict: answer`, `engraphis/engines/recall.py:77`;
  `related` → `VALIDATION_FAILED`. Символьные вызовы — 50 мс.
- **Guard:** `tests/test_symbol_info_honesty.py` (10), `tests/test_evidence_body_match.py`
  (9), мутации M67–M74 (M69 — контроль, зелёный намеренно).
- **Открыто 🟡:** один `impact:IndexError` (`graph.py:1080`, `row[neighbor_col]`,
  «tuple index out of range») после фиксов не воспроизводится; канал теперь
  изолирует имена, логирует трейсбек и имя символа, а не только класс ошибки.
- **Атака на фикс (закрыто в этом же PR):** `no.such.symbol` отвечал пятью
  определениями — `_find_nodes_flexible` для dotted-запроса добавляет узлы по
  голому хвосту («symbol»), и они попадали в `definition`. Теперь определения —
  только точное имя или суффикс «`.query`»; хвост остаётся для поиска вызовов.
  Guard: `test_dotted_unknown_name_is_not_resolved_by_its_tail`, мутация M74.
- **Закрыто замером (было 🟡):** 22.6 с на первом `get_symbol_info` не
  воспроизвелось. Один и тот же probe на дереве ДО фикса (`25648b3`) и на текущем:
  1224 мс против 1128 мс на том же запросе, тёплые — 40 мс; холодный старт сервера:
  initialize 3.4 с, health 2.7 с, первый поиск 0.7 с, первый `get_symbol_info`
  284 мс. Причина наблюдения — параллельная нагрузка (в той же сессии шёл полный
  suite), а не код. Тот же probe заодно подтвердил фиксы: `no.such.symbol` до —
  «1 defs, 15 callers» с определением из хвоста, после — `not found`; callees у
  `intent_recall` до — 10 (срез), после — 23.

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
- **Allowlist — то, что агенту нужно знать:** инвентаризация содержимого показала,
  что 90% объёма JSON — замороженные артефакты бенчмарка (`command/result/
  source_sha256`), а «код» в 40 файлах `families/*.json` — строковые фикстуры
  (их `.py`-оракулы уже в индексе). Полезны 8 файлов из 445: манифесты
  (`package.json`, `package-lock.json`, `npm-shrinkwrap.json`, `tsconfig.json`,
  `plugin.json`, `marketplace.json`) и контракт инструментов. Они индексируются
  всегда: по имени, либо по ключам `inputSchema`/`surfaces`/`annotations`
  (файл ≤512 KB). Цена allowlist — **+67 чанков** (18 747 → 18 814), выигрыш
  измерен: запрос `destructiveHint` → **top-1 `docs/MCP_CONTRACT.json`**.
- **Цена:** поиск по содержимому данных (`search_code`) их больше не видит; кому
  нужно — флаг + полная переиндексация после удаления `<проект>/.mscodebase/chunks.db*`
  (хеши не меняются, инкремент файл пропустит).
- **Guard:** `tests/test_data_files_not_indexed.py` (8 тестов), мутации M60–M66.

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
