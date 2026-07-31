# Накопленные проблемы аудита — MSCodeBase

> Создано: 2026-07-27. Статус: активный.
> Источник: 4 раунда протокольного аудита (graph.py, cypher-стек, indexing-стек, write_tools, search/engine, error_handler, remote_embedder, ci.yml, server_tools).

---

## P0 — Критические (безопасность / CI)

### P0-1: SQL injection через alias в Cypher (цепочка lexer→parser→sql)
- **Файлы:** `src/core/search/cypher_parser.py:427`, `src/core/search/cypher_sql.py:84`
- **Статус:** ✅ FIXED (parser + sql.py)
- **Детали:**
  - Parser `_parse_return_item` берёт `self.advance().value` без проверки типа токена (L427)
  - `cypher_sql.py` L84: `f" AS {item.alias}"` — f-string подстановка без валидации
  - PoC: `MATCH (n:Function) RETURN n.name AS "x FROM nodes-- "` → SQL: `SELECT n.name AS x FROM nodes-- FROM nodes AS n`
  - `--` обрезает остаток SQL, возвращает ВСЕ строки таблицы nodes вместо отфильтрованные
  - Контраст: `_property_ref_to_sql` (L321-324) валидирует имена свойств через `re.fullmatch`, alias — нет
- **Фикс (parser):** ✅ Добавлена проверка `alias_token.type not in (TokenType.IDENTIFIER, TokenType.STRING)` → `SyntaxError`
- **Фикс (sql.py):** ✅ Добавлена валидация alias через `re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item.alias)` перед f-string подстановкой (L84-88)

### P0-2: SQL injection через `layer` параметр в search/engine.py
- **Файл:** `src/core/search/engine.py:352,736`
- **Статус:** ✅ FIXED
- **Детали:**
  - `filter_expr = f"layer = '{layer}'" if layer else ""` — f-string подстановка пользовательского ввода в LanceDB SQL
  - PoC: `search_code(query="test", filter_layer="core' OR '1'='1")` → `layer = 'core' OR '1'='1'` → возвращает чанки из ВСЕХ слоёв
  - Контраст: `indexer_table.py:_escape_sql_value` корректно экранирует кавычки и backslash, но здесь не использовался
- **Фикс:** ✅ Вызов `IndexerTableMixin._escape_sql_value(layer)` перед f-string подстановкой в обоих местах (L352-356 и L740-742). Импорт `IndexerTableMixin` уже есть на уровне модуля (L18).

### P0-3: CI clean-state скрипл использует Windows-пути на Linux
- **Файлы:** `.github/workflows/ci.yml:59`, `scripts/verify_clean_state.sh:53,55,58,62`
- **Статус:** ✅ FIXED (verify_clean_state.sh)
- **Детали:**
  - `verify_clean_state.sh` использовал `venv/Scripts/pip.exe` и `venv/Scripts/python.exe` — Windows-формат
  - CI job `clean-state` запускается на `ubuntu-latest` → `venv/Scripts/pip.exe` не существует → exit 127
  - Также `bash scripts/verify_clean_state.sh` в CI вызывает скрипт, который внутри делает `git clone` внешнего репозитория — ненадёжно в CI
- **Фикс:** ✅ Заменены `venv/Scripts/pip.exe` → `venv/bin/pip`, `venv/Scripts/python.exe` → `venv/bin/python`
- **Примечание:** `ci.yml` L59 вызывает `bash scripts/verify_clean_state.sh` — скрипт теперь использует POSIX-пути, но сам скрипт по-прежнему делает `git clone` внешнего репозитория. Это отдельная проблема (CI не должна клонировать сам себя). Оставлено на потом.

### P0-4: codebase_tool.py docstring противоречит коду (sandbox)
- **Файл:** `src/mcp/tools/codebase_tool.py:148-164`
- **Статус:** ✅ FIXED
- **Детали:**
  - Docstring: `⚠️ ВНИМАНИЕ: Изоляция (sandbox) ОТСУТСТВЕТ.`
  - Код реально использует sandbox: `execute_sandboxed` с `SANDBOX_MODE_STRICT` по умолчанию (AST validation + module allowlist + subprocess isolation)
  - Администратор, читающий docstring, мог решить инструмент нельзя включать
- **Фикс:** ✅ Docstring синхронизирован: указано что sandbox активен (`execute_sandboxed` + `SANDBOX_MODE_STRICT`), перечислены механизмы изоляции

---

## P1 — Высокий приоритет (race conditions / data loss / crash)

### P1-1: `shortest_path` в graph.py — экспоненциальное потребление памяти
- **Файл:** `src/core/graph.py:636-683`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** BFS хранит все пути целиком в queue (`List[List[Tuple[int, Optional[int]]]]`). Для графа со средней степенью 10 и max_depth=10 — до 10^10 путей в памяти. Стандартный BFS хранит parent-pointer и восстанавливает путь в конце.

### P1-2: `batch_add_edges` — N+1 запросов
- **Файл:** `src/core/graph.py:917-962`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Для каждого ребра 2 SELECT + 1 INSERT. Для батча из 10000 рёбер — 30000 SQL-вызовов вместо одного `INSERT ... SELECT FROM ... JOIN`.

### P1-3: `db_manager.py` — search без `_write_lock` vs `reset_connection`
- **Файл:** `src/core/indexing/db_manager.py:274-305`, `indexer.py:304,399,324`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `reset_connection` пересоздаёт `self.table` под `_write_lock`, но `search()` (L304) этот lock не захватывает. Параллельный write во время search → `LanceError: table modified during scan` или stale reference.

### P1-4: `switch_db` без `_write_lock`
- **Файл:** `src/core/indexing/db_manager.py:227-267`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Закрывает старую БД и открывает новую без захвата `_write_lock`. Параллельный write в этот момент → запись в закрытую БД → crash.

### P1-5: `move_chunks_metadata` — delete+add не атомарно
- **Файл:** `src/core/indexing/indexer.py:494-502`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Read → Delete → Modify → Add. Если процесс упадёт между Delete и Add, чанки пропадут из индекса без восстановления.

### P1-6: `CypherExecutor.execute` обходит блокировку PropertyGraph
- **Файл:** `src/core/search/cypher_executor.py:51-52`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `_get_conn()` возвращает raw `sqlite3.Connection` без захвата `self._graph._lock`. Параллельный `add_edge` во время Cypher-запроса → `sqlite3.OperationalError: database is locked`.

### P1-7: `write_tools.py` — `file_path` без FileGuard (path traversal)
- **Файл:** `src/mcp/tools/write_tools.py` (все write-операции)
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `file_path` от пользователя передаётся в `Path(file_path).resolve()` без проверки, что он внутри `project_path`. Можно записать файл за пределами проекта.

### P1-8: `write_tools.py` — `new_name` без валидации идентификатора
- **Файл:** `src/mcp/tools/write_tools.py:99-126`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `new_name` и `symbol` не проверяются как идентификаторы. Пользователь может передать `new_name = "evil(); import os; os.system('rm -rf /')"` — текстовая замена через `str.replace` вставит вредоносный код.

### P1-9: `write_tools.py` — `_uri_to_path` без проверки project_path
- **Файл:** `src/mcp/tools/write_tools.py:450-455`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** LSP может вернуть URI для файла за пределами проекта — запись выполнится без проверки.

### P1-10: `error_handler.py` — `elapsed = ... - 1000` вместо `* 1000`
- **Файл:** `src/core/error_handler.py:454`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** При timeout `elapsed = int((time.perf_counter() - start_time) - 1000)` — вычитает 1000 секунд вместо перевода в миллисекунды. Записывает отрицательную latency в метрики, ломая min_ms, avg_ms, P50/P95.

### P1-11: `error_handler.py` — `future.cancel()` не вызывается при timeout
- **Файл:** `src/core/error_handler.py:513-514`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** При `TimeoutError` future остаётся в пуле, поток продолжает выполнение. 4 зависших timeout-а исчерпают `_SYNC_POOL` (max_workers=4), все последующие sync-вызовы будут ждать вечно.

### P1-12: `remote_embedder.py` — silent zero-vector fallback маскирует отказ
- **Файл:** `src/providers/embedder/remote_embedder.py:717-718,731-732`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** При падении провайдера возвращаются нулевые векторы. Индексация проходит «успешно», но векторный поиск возвращает случайные результаты (cosine similarity с нулевым вектором = 0 для всех). Нет маркера в БД «этот чанк имеет fallback-вектор».

### P1-13: `db_manager.py` — `_write_lock = threading.Lock`, не `RLock`
- **Файл:** `src/core/indexing/db_manager.py:48`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `threading.Lock` не реентерабелен. Будущий рефакторинг, добавляющий `reset_connection` внутрь `with self._table_write_lock:`, создаст deadlock.

### P1-14: `db_manager.py` — PID lock race → crash вместо ожидания
- **Файл:** `src/core/indexing/db_manager.py:374-398`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Между `lock_path.unlink()` и `os.open(... O_EXCL)` другой процесс может создать lock file. `os.open` падает с `FileExistsError`, ловится и превращается в `RuntimeError` — процесс крашится вместо ожидания.

---

## P2 — Средний приоритет

### P2-1: `layer.py` — 22 `except Exception` молчаливая деградация
- **Файл:** `src/core/intelligence/layer.py`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** 18 из 22 `except Exception` с `pass` или `return []`. Программные ошибки маскируются под «нет данных».

### P2-2: `layer.py` — `hash(line) % 10000` недетерминированный ID
- **Файл:** `src/core/intelligence/layer.py:662`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `hash()` рандомизирован через `PYTHONHASHSEED`. Один и тот же код-фрагмент при разных запусках получит разные `incident_id`, ломая дедупликацию.

### P2-3: `layer.py` — `netstat -ano` Windows-only
- **Файл:** `src/core/intelligence/layer.py:299-314`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `netstat -ano` не работает на Linux/macOS. `_find_pid` всегда возвращает 0 на не-Windows. RAM-метрика неполная.

### P2-4: `layer.py` — asyncio.Lock + threading.Lock смешаны
- **Файл:** `src/core/intelligence/layer.py:110-112`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `intel_log_incident` использует `asyncio.Lock`, `intel_auto_collect_adrs` использует `threading.Lock`. Оба пишут в `IntelligenceStore` — race condition.

### P2-5: `engine.py` — `_cache` без TTL, stale после reindex
- **Файл:** `src/core/search/engine.py:643-718`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Кэш на 500 записей без TTL. После reindex кэш не инвалидируется — поиск возвращает устаревшие результаты.

### P2-6: `engine.py` — `asyncio.run` в ThreadPoolExecutor bottleneck
- **Файл:** `src/core/search/engine.py:271-285`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `asyncio.run` создаёт новый event loop в каждом вызове. 3+ параллельных запроса → третий ждёт.

### P2-7: `engine.py` — 18 `except Exception` с возвратом `[]`
- **Файл:** `src/core/search/engine.py` (множество методов)
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Пользователь не отличит «нет результатов» от «поиск упал».

### P2-8: `write_tools.py` — `_infer_package` некорректный `rstrip(".py")`
- **Файл:** `src/mcp/tools/write_tools.py:307-310`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `rstrip(".py")` удаляет любую комбинацию символов `.`, `p`, `y` с конца. `happy.py` → `ha`. Должно быть `p.stem`.

### P2-9: `write_tools.py` — неатомарная запись без backup
- **Файл:** `src/mcp/tools/write_tools.py:386-413`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Read → modify → write_text без tempfile+rename. Если процесс упадёт — файл в неконсистентном состоянии.

### P2-10: `remote_embedder.py` — `mode_lock` только на чтение current_mode
- **Файл:** `src/providers/embedder/remote_embedder.py:644-645`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Блокировка отпускается после чтения `self.mode`, но HTTP-запрос выполняется без блокировки. Смена mode посреди batch → часть чанков получит векторы от одного провайдера, часть — нулевые.

### P2-11: `remote_embedder.py` — один `httpx.Client` на все провайдеры
- **Файл:** `src/providers/embedder/remote_embedder.py:56`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Один Client с connection pool для llama.cpp, LM Studio, ONNX. Медленный провайдер блокирует остальных.

### P2-12: `error_handler.py` — `_TIMELINE.pop(0)` O(n) под локом
- **Файл:** `src/core/error_handler.py:206-218`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `list.pop(0)` сдвигает все элементы. Под `_TOOL_METRICS_LOCK` на каждый вызов инструмента. Bottleneck при высокой нагрузке.

### P2-13: `indexer_table.py` — ручное `_escape_sql_value` хрупко
- **Файл:** `src/core/indexing/indexer_table.py:26-47`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Экранирование покрывает 3 вектора, но не двойные кавычки, Unicode-обходы. Зависит от того, что DataFusion не изменит escape-правила.

### P2-14: `indexer.py` — `get_status` читает кэш без `_index_lock`
- **Файл:** `src/core/indexing/indexer.py:250,269-272`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `total_chunks` обновился, а `unique_files` ещё нет — статус вернёт неконсистентные числа.

### P2-15: `db_manager.py` — `_warmup_cache` без `_write_lock`
- **Файл:** `src/core/indexing/db_manager.py:160-189`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Читает `self.table` без `_write_lock`. Если параллельный поток делает `reset_connection`, может попасть на закрытую таблицу.

### P2-16: `ci.yml` — Node 20 deprecated, нет Python 3.10
- **Файл:** `.github/workflows/ci.yml`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `actions/setup-python@v5` с python 3.11/3.12, но нет 3.10. Node 20 в matrix может быть deprecated.

### P2-17: `ruff.toml` — BLE001 (broad except) не в `select`
- **Файл:** `ruff.toml`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** 532 broad `except` по проекту не ловятся ruff-ом.

---

## P3 — Низкий приоритет

### P3-1: `graph.py` — `export_compressed` / `import_compressed` `unlink` без `finally`
- **Файл:** `src/core/graph.py:1017,1083`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Если `subprocess.run(check=True)` упадёт, `temp_db.unlink()` не выполнится → `.tmp.db` останется на диске.

### P3-2: `graph.py` — `close()` — `PRAGMA wal_checkpoint(TRUNCATE)` без таймаута
- **Файл:** `src/core/graph.py:231-233`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** На больших графах checkpoint может занять минуты и заблокировать закрытие. Нет `PRAGMA busy_timeout`.

### P3-3: `graph.py` — `_get_conn` `check_same_thread=False` + RLock bottleneck
- **Файл:** `src/core/graph.py:188,179`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Все операции сериализуются через один `threading.RLock`. WAL mode позволяет конкурентные чтения, но блокировка это отменяет.

### P3-4: `graph.py` — `detect_dead_code` молчаливый LIMIT 200
- **Файл:** `src/core/graph.py:725`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Возвращает максимум 200 кандидатов; если dead code больше, пользователь не узнает об усечении.

### P3-5: `cypher_executor.py` — SQL и params утекают в ответ MCP
- **Файл:** `src/core/search/cypher_executor.py:69-70`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Сгенерированный SQL и параметры возвращаются в `stats` и попадают в MCP-ответ. Раскрывает внутреннюю структуру таблиц.

### P3-6: `cypher_sql.py` — variable-length paths `[*1..3]` молча игнорируются
- **Файл:** `src/core/search/cypher_sql.py:209-217`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Запрос `MATCH (n)-[:CALLS*1..5]->(m)` возвращает только прямых соседей, не 5 уровней. Только debug-level лог.

### P3-7: `write_tools.py` — `_apply_delete` по line_no без проверки содержимого
- **Файл:** `src/mcp/tools/write_tools.py:456-483`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Удаляет строки по номеру без проверки `symbol in text_lines[idx]`. Если индекс устарел — удалятся неправильные строки.

### P3-8: `write_tools.py` — `_action_replace` без проверки синтаксиса
- **Файл:** `src/mcp/tools/write_tools.py:226-234`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `new_code` вставляется как есть. Нет `ast.parse` для Python-файлов перед записью.

### P3-9: `write_tools.py` — `_apply_changes` неатомарная запись без backup
- **Файл:** `src/mcp/tools/write_tools.py:386-413`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Нет backup-файла, нет `tempfile + os.replace` паттерна.

### P3-10: `error_handler.py` — traceback в MCP-ответ (info leak)
- **Файл:** `src/core/error_handler.py:495`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `traceback.format_exc(limit=3)` возвращается в MCP-ответ пользователю. Раскрывает пути к файлам, имена модулей.

### P3-11: `layer.py` — ручной парсинг git objects через zlib
- **Файл:** `src/core/intelligence/layer.py:729-787`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Не поддерживает packfiles (`.git/objects/pack/*.pack`). Если `git gc` был сделан — ADR-коллектор молча вернёт «не найдено».

### P3-12: `db_manager.py` — `asyncio.Lock` в `__init__` — wrong loop на Python 3.10
- **Файл:** `src/core/indexing/db_manager.py:45`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** `asyncio.Lock()` создаётся без running loop. Если `LanceDBManager` инстанцируется в sync-коде startup, а `ensure_async_table` вызывается из async MCP-handler в другом event loop — lock может привязаться к неправильному loop.

### P3-13: `server_tools.py` — двойная инстанциация каждого инструмента
- **Файл:** `src/mcp/server_tools.py:148-158`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Каждый класс создаётся дважды: первый раз для `.name` (фильтр), второй раз для регистрации. Кэш хранит только имя, не экземпляр. 38 инстанциаций вместо 19.

### P3-14: `server_tools.py` — `_action_write` создаёт `SymbolWriteTool` на каждый вызов
- **Файл:** `src/mcp/server_tools.py:82-83`
- **Статус:** 🔍 IN PROGRESS
- **Детали:** Локальный import + новая инстанция каждый вызов. Для MCP-сервера с сотнями write-операций — лишний overhead.

---

## Протокол нарушения (предыдущая сессия)

| # | Нарушение | Пункт AGENTS.md |
|---|-----------|-----------------|
| 1 | MCP-FIRST не соблюдён — grep/read_file вместо MCP-инструментов | §0.2 |
| 2 | `.agent_task_state.md` не обновлялся для текущей задачи | §0.1 |
| 3 | `EXPERIMENTS_LOG.md` не заполнен | §1.6 |
| 4 | `## Verification Results` не создана | §0.1.1 |
| 5 | `verified_from_clean_state` не выполнен | §7 п.7 |
| 6 | `## Definition of Done` не проверен | §7 |
| 7 | Числа без команды замера | §5.15 |
| 8 | `Verified vs Recalled` не разграничены | §1.14 |
| 9 | `AGENT_DIARY.md` не обновлён | §4 |
| 10 | `KNOWN_ISSUES.md` не синхронизирован | §4 п.6 |

---

## Что сделано в текущей сессии

- ✅ Parser `_parse_return_item` — добавлена валидация alias token type (P0-1 частично)
- ✅ `.agent_task_state.md` обновлён
- ✅ MCP connectivity проверена (`debug_runtime_passport` — RUN_ID: ae0c5dfb6fab)
- ✅ Все P0-P3 проблемы выписаны в ISSUE.md

## Что осталось

- P0-1: Валидация alias в `cypher_sql.py` L84 (f-string подстановка)
- P0-2: Фикс `layer` SQL injection в `engine.py:352`
- P0-3: Фикс `verify_clean_state.sh` Windows-пути → POSIX
- P0-4: Фикс docstring sandbox в `codebase_tool.py`
- P1-P3: Все остальные баги ждут фикса
- Верификация через pytest после каждого фикса
- Обновление `AGENT_DIARY.md` и `KNOWN_ISSUES.md`
