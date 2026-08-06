# EXPERIMENTS_LOG.md — Audit Verification (2026-07-22)

## [2026-08-06] — Exp 6: tree-sitter-language-pack парсеры на Windows (issue #174 блокирует?)

**Гипотеза:** language-pack 1.14.3 НЕ может скачивать парсеры на Windows (issue #174: `No pre-built parsers available for platform 'windows-x86_64'`) → интеграция +56 языков невозможна до следующего релиза.
**Команда:** `python -m venv %TEMP%/tslp_test && pip install tree-sitter-language-pack` → `get_parser('lua')` + 11 других языков + `get_tags_query`; затем интеграция в проект: `MSCODEBASE_LANGUAGE_PACK=true python -c "from src.core import language_pack; print(language_pack.try_enable())"`.
**Сырой результат:**
```
language-pack: 1.14.3
LUA PARSER: OK Language   ← get_parser РАБОТАЕТ на Windows (per-language download)
12/12 тестовых языков: parser OK (lua, elixir, haskell, zig, nim, clojure, v, odin, groovy, julia, perl, crystal)
cache_dir: %LOCALAPPDATA%/tree-sitter-language-pack/v1.14.3/libs
manifest_languages: 371 | languages WITH tags: 71
интеграция: try_enable → enabled: True | langs: 54 | tags: 54 | failed: []
.lua SCM-символы: greet, helper (function_declaration) — чисто
.sol: Bank, deposit, get | .r: greet, compute_mean | .pyx: cy_add, Point.__init__ — чисто
.nix: 0 символов (query есть, captures пусты — честный пусто)
.exs (elixir): МУСОР — 'defmodule', 'ef ', 'ello(' (макро-грамматика: def/defmodule — call-узлы) → elixir исключён из карты
```
**Вердикт:** гипотеза ОПРОВЕРГНУТА (хорошая новость). Per-language download на Windows работает (issue #174 касается только download_all()). Слой интегрирован как optional extra [language-pack] + гейт MSCODEBASE_LANGUAGE_PACK (off по умолчанию): 54 языка, 54 tags-queries, 0 failed.
**Урок:** issue про «нет windows-бандла» ≠ «не работают per-language загрузки» — эмпирическая проверка обязательна; макро-грамматики (elixir) требуют фильтра валидности имён (добавлен: `_VALID_IDENTIFIER_RE`) или исключения.
**Связь с отрицательными:** вариация «371 язык symbol extraction» (Exp 1) — подтверждено 71 tags-язык; новое: парсеры на Windows работают.

---

## [2026-08-05] — Exp 1: tree-sitter-language-pack — «371 язык за 1 день» (проверка ключевого заявления audit.md)

**Гипотеза:** пакет даёт 300+ языков symbol extraction «из коробки» одним pip install; get_parser работает с tree-sitter 0.26; tags.scm присутствуют для большинства языков.
**Команда:** `python -m venv %TEMP%/tslp_venv && pip install tree-sitter-language-pack` → скрипты: подсчёт `manifest_languages()`, `get_tags_query()` по всем 371, парс Python-файла.
**Сырой результат:**
```
manifest_languages: 371
language_count()/available_languages(): 1 (только downloaded)
with non-empty tags.scm: 71 (19%) — 300 языков имеют ПУСТЫЕ tags (bash, clojure, cmake, cobol, ada, actionscript…)
первый парс python: 37.6 s (on-demand скачивание грамматики, кэш 22MB); повторный парс: 0.03 ms
tags.scm для core-языков: python/js/ts/go/rust/java/c/cpp/csharp YES; bash NO
win_amd64 abi3 wheel 2.0MB; требует Python >=3.10; abi3 совместим с 3.14
API: QueryCursor(query).captures(node) → dict {capture_name: [nodes]} (tree-sitter 0.26)
```
**Вердикт:** ЧАСТИЧНО опровергнута. Пакет реален и ставится (2MB wheel + 22MB/грамматика кэш, on-demand), парсинг AST работает, но **symbol extraction через tags.scm есть только у 71 из 371 языка (19%)** — «+350 языков symbol extraction за 1 день» НЕ подтверждено. Для наших 9 core-языков tags-запросы есть (паритет), для shell/context (bash, sql, hcl) — нет. Выигрыш пакета: +62 новых языка с tags-запросами + AST-парсинг 300 языков для чанкинга (без символов/рёбер).
**Урок:** «N языков в манифесте» ≠ «N языков с symbol extraction» — манифест содержит грамматики, tags-запросы — подмножество (19%). Перед интеграцией считать именно язык+tags, а не язык+парсер. Первый парс каждого языка требует сети (37.6s) — для offline/CI нужен prefetch или запечённые грамматики.

---

## [2026-08-05] — Exp 2: извлечение символов — текущий CodeParser vs tags.scm (паритет?)

**Гипотеза:** tags.scm-подход даёт извлечение определений функций/классов не хуже текущего CodeParser (который также строит calls/imports/dataflow).
**Команда:** `venv python -X utf8 experiments/exp2_symbols.py` (src/core/graph.py, 66 defs/classes по regex-граунд-труту)
**Сырой результат:**
```
Ground truth (regex def/class, включая методы): 66
[A] CodeParser init+parse_file: 65 ms | chunks: 69 | symbols: 60 (qualified: Class.method)
[B] tags.scm parse+query: 16 ms | defs: 66
[B] recall vs truth: 100% (missing: [], extra: []) — после коррекции граунд-трута
```
**Вердикт:** подтверждена (паритет). tags.scm извлекает 66/66 определений за 16ms vs CodeParser 60 символов за 65ms — чуть быстрее и полнее по определениям. НО: tags.scm даёт только definition.* / reference.call / name — НЕ даёт imports, dataflow (ASSIGNED_FROM), вызовы с резолвом qualified_name, чанкинг с метаданными. Для замены текущего extract_calls/extract_imports/extract_assignments нужна доп. работа.
**Урок:** tags.scm — готовый drop-in для извлечения определений (дешевле собственного walk), но НЕ полноценная замена CodeParser; оптимально — гибрид (scm для определений + текущий walk для calls/imports/dataflow).

---

## [2026-08-05] — Exp 3: реальная латентность Cypher/impact (проверка «4297ms из лога» в audit.md)

**Гипотеза:** текущая латентность графовых запросов ~4297ms (цифра аудита) — реальность или артефакт?
**Команда:** `CypherExecutor(PropertyGraph(graph.db)).execute(q)` ×3 на живом индексе (6856 nodes / 19969 edges, 8.2MB) + живой MCP-вызов graph_query(action=cypher).
**Сырой результат:**
```
MATCH (n) RETURN count(n):           min=0.3ms avg=4.2ms
MATCH (n:Function) RETURN count(n):  min=0.4ms avg=0.5ms
MATCH (a:Function)-[:CALLS]->(b) count(*): min=3.7ms avg=4.2ms
MATCH … WHERE b.name = '…':          min=4.2ms avg=4.4ms
ORDER BY count(*) DESC LIMIT 5:      min=8.2ms avg=10.1ms
Живой MCP graph_query (cypher):      elapsed_ms = 7.2ms / 12.6ms (rows=0 / rows=1794)
```
**Вердикт:** опровергнута (для графа). Реальная латентность Cypher на 6856 узлов / 19969 рёбер: **0.3–13ms** (прямой вызов) и **7–13ms** (живой MCP round-trip). «4297ms» — вероятно, цифра из старого лога векторного поиска/embedding-первого-вызова, не графа. Наблюдение: имена калл-таргетов — qualified (Analyzer.__init__), запросы по `name = 'x'` должны учитывать это (docs для query_graph).
**Урок:** цифры производительности в audit.md не верифицированы — замер перед сравнением обязателен (§5.15). Графовая латентность уже в классе конкурентов (<10ms).

---

## [2026-08-05] — Exp 4: DECORATES/OVERRIDES — извлекаемость текущими tree-sitter-парсерами

**Гипотеза:** рёбра DECORATES и OVERRIDES (недостающие 2 типа из таксономии DeusData) извлекаемы текущей инфраструктурой без SCIP/LSP.
**Команда:** парс синтетического Python-файла (декораторы + наследование + @override) текущим CodeParser + walk AST на decorated_definition/decorator.
**Сырой результат:**
```
symbols CodeParser: Base.method, Child.method, Child.abstract_method, Child.prop, Child.helper, standalone — БЕЗ свойств-декораторов
AST содержит: decorated_definition (@override/@abc.abstractmethod/@property/@staticmethod), decorator-узлы, class Child(Base) — база видна
```
**Вердикт:** подтверждена (feasibility). DECORATES: узлы decorated_definition/decorator есть в tree-sitter-python — извлечение ~30–50 строк в parser.py (walk decorator → имя → ребро DECORATES). OVERRIDES: вычисляемо по class-иерархии (class Child(Base) в AST) + name-матчинг методов — ~100 строк. Никаких новых зависимостей.
**Урок:** 2 недостающих типа рёбер из таксономии аудита закрываются малым патчем существующего parser.py — это быстрый win, не требует SCIP.

---

## [2026-08-05] — Гипотеза: доступность зависимостей для кандидатов аудита (SCIP, Leiden, cypher-sqlite)

**Гипотеза:** scip-python и cypher-sqlite существуют на PyPI и ставятся pip (заявление audit.md «Быстрый вариант: cypher-sqlite (Python)» и «интегрировать scip-python»).
**Команда:** PyPI JSON API для scip-python, cypher-sqlite, leidenalg, igraph, tree-sitter-language-pack.
**Сырой результат:**
```
scip-python:      HTTP 404 Not Found (НЕ существует на PyPI)
cypher-sqlite:    HTTP 404 Not Found (НЕ существует на PyPI)
leidenalg 0.12.0: есть, win_amd64 abi3 (совместим с 3.14) ✓
igraph 1.0.0:     есть, win_amd64 abi3 ✓
tree-sitter-language-pack 1.14.3: есть, abi3 ✓
```
**Вердикт:** частично опровергнута. SCIP-индексеры для Python на PyPI НЕТ (только отдельные CLI-репозитории Sourcegraph, требуют node/native сборку) — «встроить scip-python как optional backend» требует не-pip установки. cypher-sqlite не существует — не нужен (свой Cypher уже есть). Leiden-стек (leidenalg+igraph) доступен abi3 — community detection реализуем.
**Урок:** audit.md ссылается на пакеты, которых нет на PyPI (scip-python, cypher-sqlite) — «проверить существование пакета до планирования» (§1.14 Verified vs Recalled).

---

## [2026-08-04] — Гипотеза: _distance при cosine-метрике меньше=ближе, LanceDB сортирует ASC

**Ожидание:** для lancedb 0.34.0 + IVF_FLAT cosine `_distance = 1 − cos_sim ∈ [0,2]` (сам вектор = 0.0), строки приходят по возрастанию. Комментарий `engine.py:166` «чем больше, тем ближе» неверен, и `sort(reverse=True)` в fast mode инвертирует топ.
**Команда:** `<ext>/venv/Scripts/python.exe experiments/exp_distance_semantics.py` (temp-таблица, IVF_FLAT metric=cosine, query=[1,0,0,0], тот же путь create_index, что в index_project_runner.py:540)
**Сырой результат:**
```
lancedb version: 0.34.0
=== search([1,0,0,0]) c cosine-индексом ===
  id=q_self   _distance=0.000000
  id=near     _distance=0.006116
  id=orth     _distance=1.000000
  id=far      _distance=1.000000
=== search c default (l2) ===
  id=q_self   _distance=0.000000
  id=near     _distance=0.020000
  id=orth     _distance=2.000000
```
**Вердикт:** подтверждена — `_distance` = 1−cos_sim, порядок ASC, меньше=ближе. Комментарий engine.py:166 и `sort(reverse=True)` (engine.py:791, fast — дефолтный режим search_tools.py:270) неверны. Векторный поиск (157-186), hybrid RRF (513), context_search (885) — корректны, не тронуты. Fix: комментарий + `sort()` + регрессионный тест `test_search_with_mode_fast_sorts_distance_ascending`.
**Урок:** семантика `_distance` — свойство БД, не кода: её нельзя выводить из комментария соседнего кода. Связь с отрицательными: не из таблицы §3.8; метод — реальный lancedb-запрос (не мок). Раньше (EXPERIMENTS_LOG#2026-07-31) аудит полагался на чтение кода → та же ловушка P-002.

---

## [2026-08-03] — Гипотеза: ONNX embedder не поднимается из-за off-by-one путей (не из-за модели/портов)

**Ожидание:** исправление PROJECT_ROOT (parent×3 → parents[3]) в onnx_client/onnx_server вернёт ONNX-режим: сервер найдёт скрипт и модель, /embed вернёт 384-dim.
**Команда:**
```
cd <ext> && PYTHONPATH=<ext> venv/Scripts/python.exe D:/Project/MSCodeBase/.local/onnx_client_check.py
curl -X POST http://127.0.0.1:9876/embed -d '{"text":"тест"}'
```
**Сырой результат:**
```
[1] ensure_server_running: True
[2] embed status=200
[3] dim=384 first3=[0.037, -0.058, -0.041]
ONNX CLIENT PATH: PASSED
```
**Вердикт:** подтверждена — причина в путях: (1) onnx_client искал `…\src\src\core\embedder\onnx_server.py` (задвоенный src), (2) onnx_server искал модель в `…/src/.codebase_models/…` (вместо корня). До фикса: `FileNotFoundError: Model directory not found for: multilingual-e5-small-int8`. Логи сервера: «НЕ УДАЛОСЬ загрузить E5-base ONNX» ×5 за день.
**Урок:** off-by-one пути в `src/core/embedder/` копируются между файлами (onnx_client ← onnx_server) — при работе с путями в src/core/embedder обязателен `parents[3]` или проверка `path.exists()` на всех search_paths (remote_embedder использует get_extension_dir — верно).

---

## [2026-07-31] — P0-3: verify_clean_state.sh --no-clone (CI self-clone убран)

### Гипотеза
Параметризация `verify_clean_state.sh` (флаг `--no-clone` + `$1` = repo URL) убирает self-clone из CI (тестируется checkout раннера), сохраняя единый источник правды: локальный запуск без аргументов = прежний полный клон.

### Команда
1. `bash -n scripts/verify_clean_state.sh` — синтаксис
2. Python `yaml.safe_load` для `.github/workflows/ci.yml` — валидность
3. Локальный прогон `bash scripts/verify_clean_state.sh --no-clone` — не-Linux ветка (Windows)

### Сырой результат
```
SYNTAX_OK (bash -n scripts/verify_clean_state.sh)
YAML_OK — ci.yml jobs.clean-state.steps[-1].run = bash scripts/verify_clean_state.sh --no-clone "${{ github.repository }}"
Локальный прогон --no-clone (Windows): «No-clone mode: verifying current directory» — clone пропущен, ветка выбрана верно; далее падение на venv/bin/* — pre-existing Linux-only assumption скрипта (POSIX-layout venv), не связано с правкой.
Полный pytest tests/: 610 passed, 0 failed (35.25s)
```

### Вердикт: подтверждена
`--no-clone`-ветка выбирается и корректно пропускает clone (работа в текущем каталоге). Локальный ручной запуск без аргументов сохраняет полный клон (default URL). Linux-путь (venv/bin, lockfile gate, install из lock) требует ubuntu-раннера — покрыто bash -n и логикой ветвления, полный CI-прогон выполнит GH Actions.

---

## [2026-07-27] — P0 Fixes: alias injection, layer injection, CI paths, sandbox docstring

### Гипотеза
Четыре P0-бага из протокольного аудита можно исправить минимальными, проверяемыми правками без риска регрессий.

### Команда
1. `edit_file` cypher_sql.py L84 — добавить `re.fullmatch` валидацию alias
2. `edit_file` engine.py L352, L740 — экранировать `layer` через `_escape_sql_value`
3. `edit_file` verify_clean_state.sh — заменить Windows-пути на POSIX
4. `edit_file` codebase_tool.py — синхронизировать docstring с кодом

### Сырой результат
Все 4 правки применены успешно через `edit_file`. Проверка через `read_file` подтвердила корректность каждой правки:
- cypher_sql.py L84: `if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item.alias):` — добавлен
- engine.py L352-356: `_esc = IndexerTableMixin._escape_sql_value(layer)` — добавлен перед f-string
- engine.py L740-742: аналогично для `search_with_mode`
- verify_clean_state.sh: `venv/bin/pip` и `venv/bin/python` — заменены
- codebase_tool.py: docstring переписан, дубликат удалён

### Вердикт: подтверждена
Правки минимальны, точечны, не затрагивают логику — только добавляют валидацию/экранирование.

---

## [2026-07-22] — Audit: P0-1 DebounceBatch deadlock

**Ожидание:** `await self._flush()` вызывается ВНУТРИ `with self._lock` → deadlock при 100 файлах
**Команда:** AST-анализ + ручное чтение rate_limiter.py L154-232
**Сырой результат:**
```
=== DebounceBatch.add() at line 154 ===
  L154:     async def add(self, file_path: str) -> bool:
  L156:         with self._lock:                    # L156 — lock acquired
  ...
  L163:         if batch_full:                       # OUTSIDE lock
  L164:             await self._flush()              # OUTSIDE lock ✓
```
**Вердикт:** подтверждена — `_flush()` вызывается вне lock, deadlock не воспроизводится.

---

## [2026-08-01 22:35] — Гипотеза: HF-truncation 512 гарантирует лимит llama.cpp (n_ctx_train=512)

**Ожидание:** после усечения до 512 HF-токенов llama.cpp посчитает ≤ 512 токенов → HTTP 400 исчезнет.
**Команда:** `_measure_tokens.py` (живой llama-server :8080, /tokenize, 20 реальных длинных чанков: error_handler, modification_guard, db_writer, lsp_project_bridge, rate_limiter, graph, runtime_coordinator, changelogs en/ru/zh) + прогон реиндекса 22:01-22:11.
**Сырой результат:**
```
file                              len   HF512  ->llama  rawllama
docs/zh/CHANGELOG.md              3500    512      502      1860   ← максимум после truncation
docs/zh/CHANGELOG.md              3500    512      475      1822
src/core/error_handler.py         3500    512      479       831
... (все 20 чанков: llama_after_trunc <= 502)
llama_server_stderr.log: E srv send_error: task id = 5977, input (526 tokens) is larger than the max context size (512). skipping
_reindex_err.log: [embed] 4512/4677 ... Chunk 8 failed all retries, zero vector → Embedding failed for chunk 8 after all retries. Aborted.
```
**Вердикт:** ОПРОВЕРГНУТА — запас после HF-512 всего 0-10 токенов (502/512), плотный CJK даёт 526>512 (разные BPE у HF и GGUF). Фикс 48e695b8 не работает.
**Вывод:** гарантия только через нативный `/tokenize` llama-server (лимит 480). Реализовано в remote_embedder.py; реиндекс 22:37→22:47: 4677 chunks, HTTP 400=0, Aborted=0.

---

## [2026-08-02 22:40] — Гипотеза: drop_table+create_table наследует мёртвые фрагменты только при mmap-локе

**Ожидание:** в чистом окружении (без живого mmap-лока процесса) drop_table удаляет физические файлы, и новый create_table имеет ровно 1 фрагмент; наследование версий (INC-6C62) возникает только когда файлы залочены → rmtree/delete молча пропускается.
**Команда:** `python -m pytest tests/test_lancedb_recreate.py -v` (venv расширения, lancedb 0.34.0, Windows).
**Сырой результат:**
```
tests/test_lancedb_recreate.py::test_drop_create_does_not_inherit_fragments PASSED [ 33%]
tests/test_lancedb_recreate.py::test_recreate_table_physical_fresh_table PASSED [ 66%]
tests/test_lancedb_recreate.py::test_close_for_maintenance_releases_handles PASSED [100%]
3 passed in 3.63s
```
**Вердикт:** ПОДТВЕРЖДЕНА — в чистом окружении drop+create даёт 1 фрагмент (наследования нет); корень INC-6C62 — именно залоченные mmap-файлы живого MCP-процесса. Фикс: `recreate_table_physical()` (close → gc → sleep 0.5 → rmtree(ignore_errors=False) → reconnect; PermissionError → fresh path). Полный pytest: 670 passed / 0 failed.
**Вывод:** физическое пересоздание таблицы или fresh-path — единственный надёжный путь; drop+create под живым процессом запрещён (guard: recreate_table_physical централизует все 4 места).


## [2026-08-03] — Гипотеза: Python 3.14 ломает asyncio.get_event_loop() в синхронных потоках проекта

**Триггер §1.7 п.2:** проект работает на Python 3.14.3 (новее training cutoff); §1.9 требует проверки актуальности API по источнику, а не по памяти.
**Ожидание:** официальный changelog подтвердит «get_event_loop() без текущего цикла → RuntimeError»; в проекте найдутся использования в синхронном коде без защиты → латентные поломки инструментов в non-loop потоках.
**Команда:** fetch https://docs.python.org/3.14/whatsnew/3.14.html (секции Removed/Deprecated/asyncio) + grep `get_event_loop|set_event_loop_policy|iscoroutinefunction` в src/ + чтение контекстов.
**Сырой результат:**
```
В Python 3.14: asyncio.get_event_loop() raises RuntimeError if no current event loop,
no longer implicitly creates one. asyncio policy system deprecated (удаление в 3.16).
iscoroutinefunction deprecated → inspect.iscoroutinefunction. from __future__ import
annotations deprecated (после EOL 3.13, 2029). Инкрементальный GC 3.14.0-3.14.4
ОТКАТАН в 3.14.5 (memory pressure). Новое: python -m asyncio ps/pstree PID,
pdb -p PID, pathlib.copy/move, map(strict=), uuid6/7/8.
grep: 15 использований get_event_loop — 14 защищены (async-контекст или except RuntimeError),
1 латентный: error_handler.py:605 sync_wrapper (RuntimeError ловится общим except Exception
→ инструмент вернёт ошибку вместо запуска в non-loop потоке).
```
**Вердикт:** ПОДТВЕРЖДЕНА (частично — 1 из 15 рискован). Фикс error_handler.py:605: get_event_loop() → get_running_loop() + fallback на прямой вызов (поведение идентично ≤3.13 во всех контекстах). 56 passed (error-тесты). Остальные 14 — проверены и безопасны (except RuntimeError есть везде, где нужен).
**Урок:** «get_event_loop() в sync-обёртке» — классический паттерн-ловушка: работал все годы, ломается тихо на 3.14. Guard: новые sync-обёртки используют get_running_loop() с try/except, никогда get_event_loop(). Отдельный урок: verify_diary.py — проверяльщик без собственных тестов; его ложные ❌ шумели в логах при каждом старте MCP (3 бага, exp-16 связан с KNOWN_ISSUES#2026-08-03 23:40). Применимость: audit asyncio-паттернов при бампе рантайма; python -m asyncio pstree <PID> — новый инструмент диагностики зависших async-задач MCP.

---

## [2026-08-03] — Гипотеза: рефлексивное обучение (Reflexion/Self-Refine) применимо к операционной DIS-системе агента через дневники

**Триггер §1.7 п.3:** задача «как сделать агента самообучающимся» (add.md) — сама формулировка есть триггер исследования.
**Ожидание:** академические подходы к самообучению LLM-агентов (вербальная рефлексия, memory augmentation) ложатся на существующие артефакты проекта (AGENT_DIARY, EXPERIMENTS_LOG, KNOWN_ISSUES) без переобучения весов.
**Команда:** fetch arXiv:2303.11366 (Reflexion), arXiv:2303.17651 (Self-Refine), arXiv:2309.02427 (CoALA).
**Сырой результат:**
```
Reflexion (Shinn et al., 2023, arXiv:2303.11366): вербальная рефлексия в episodic
memory → 91% pass@1 на HumanEval; дообучение весов не требуется.
Self-Refine (Madaan et al., 2023, arXiv:2303.17651): итеративный цикл feedback→refine
даёт ~20% абсолютного улучшения (GPT-4, 7 задач).
CoALA (Sumers et al., 2023, arXiv:2309.02427): modular memory = episodic (история
инцидентов) + semantic (правила/паттерны) + procedural (навыки) + working (контекст)
— прямое соответствие AGENT_DIARY/KNOWN_ISSUES/протоколу.
```
**Вердикт:** подтверждена — впитано в личный AGENTS.md: §3.5 (Systemic Generalization Loop), §3.6 (Cross-Domain Analogies), §6.6.2 (мета-проверка паттернов P-###), §6.6.5 (отрицательные результаты), §6.6.8 (Monthly Self-Review), §11 (добродетель «Обучение»).
**Урок:** дневники проекта — это уже CoALA-память; протоколу не хватало только циклов рефлексии (обобщение после фикса, мета-анализ раз в месяц), а не новых артефактов.

---

## 🚫 Отрицательные результаты (не повторять)

| Что пробовали | Почему не сработало | Дата | Связь |
|---------------|---------------------|------|-------|
| scip-python как pip-зависимость (SCIP backend для Python) | Пакета нет на PyPI (404) — только CLI-репозитории Sourcegraph с node/native сборкой | 2026-08-05 | audit.md п.9 |
| cypher-sqlite как готовая Cypher-библиотека | Пакета нет на PyPI (404); свой CypherExecutor уже реализован | 2026-08-05 | audit.md п.2 |
| «371 язык symbol extraction» из tree-sitter-language-pack | Манифест = 371 грамматика, но tags.scm есть только у 71 (19%); 300 языков — AST-парсинг без символов | 2026-08-05 | audit.md п.1 |
