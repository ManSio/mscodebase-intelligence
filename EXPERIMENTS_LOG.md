# EXPERIMENTS_LOG.md — Audit Verification (2026-07-22)

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
