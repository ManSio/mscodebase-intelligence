# KNOWN ISSUES — MSCodeBase Intelligence

> Синхронизируется из `AGENT_DIARY.md` при каждом [🏁 ИТОГ].
> Формат: дата | что было | статус | fix

---



**153 entries** — compressed per §4.8 R3 (conclusion-first)

- [✅ CLOSED (resolved 7 passed)] Two-pass Graph Symbol Resolution (Extract -> Resolve): Resolves placeholder __extern__ nodes into real symbols or DEPENDENCY nodes (stdlib/external). Added GraphSymbolResolver, integrated to indexer, graph_rag, and graph_adapter.

- [🟡 ACKNOWLEDGED (осознанный тех] Архитектурный техдолг: крупные модули (>800 строк)
- [🟡 deferred (не блокер) | Deadl] Env-access extractor: deferred языки (elixir, hask
- [✅ CLOSED (live-верифицирован и] PyPI-упаковка: `tools`/`locales`/`adapters` вне wh
- [✅ CLOSED (fix #18, 1578a1bb; g] `1ff77294` Full reindex зависает в фазе «Finalizing» (Propert
- [✅ CLOSED (live-reverified #1-4: git routing 41 commits, apply=false short-circuits, dotted import, callers-cou] Codebase hub write-actions: 4 бага (git routing, d
- [🟡 env-gap | Deadline: — | Влад] LSP-тулы: basedpyright не установлен (OPEN / ENV)
- [✅ Fixed (AGENTS.md §2 61→64, inline 12→13 + dual_arm_health] `ad89b2d4` AGENTS.md §2 противоречит реальной регистрации тул
- [🟡 запланировано (индексатор) |] Data Gap: папка tests/ не индексируется Tree-sitte
- [🟡 запланировано (индексатор) |] `95237f68` Graph node enrichment: узлы без file_path (OPEN / 
- [🟢 стабильно | Deadline: — | Вл] DatabaseLock ORPHAN-kill → A+ fail-closed (PID 200
- [🟢 стабильно | Deadline: — | Вл] `b03073c5` Полный заморозок MCP при full reindex (root cause:
- [🟢 стабильно | Deadline: — | Вл] Вариант А: честный reindex-статус для агента (FIXE
- [🟢 стабильно | Deadline: — | Вл] Live-косметика: reindex ToolError обёртки + Projec
- [🟢 стабильно (lazy-импорты рабо] Цикл core: error_handler ⇄ task_queue через lazy-и
- [🟢 внесено + проверено, НЕ зако] E-09: upload-bomb gate GitUrlSource 4/4 (Фаза 2 за
- [E-05 ✅; LSP-регрессия 🔴 OPEN (] E-05: ActionReceipt reproducible_by 4/4 (workdir-ф
- [✅ закоммичено 381e41bd (не зап] `381e41bd` ТЗ §11 Action Receipt: get_action_receipt + store 
- [🟢 внесено + проверено, закомми] `11c71262` B-1: фаза 1 полная (8 экосистем) + фаза 2 stdlib l
- [🟢 внесено + проверено (unit), ] `efe07e38` Фаза 4-хвост: wiring плагинов в MCP-сервер (DONE, 
- [🟢 внесено + проверено, НЕ зако] `f1b5019b` Deep-spec docs: Signature/Description колонки в MO
- [🟢 внесено + проверено, закомми] `11c71262` Backlog B-1: манифест-парсеры — фундамент (python/
- [🟢 внесено + проверено, закомми] `1f07952a` Фаза 5: адаптеры клиентов + CLI wrapper (план §4) 
- [🟢 внесено + проверено, закомми] `2f30f585` Фаза 4: MCP-proxy wiring + trust-гейт UX + deps (п
- [🟢 внесено + проверено, закомми] `898e88f0` Фаза 4: subprocess-изоляция плагинов (план §5.4) (
- [🟢 внесено + проверено, закомми] `ae2b01bb` Фаза 4 v1: trust-гейт плагинов (план §5) (DONE)
- [🟢 внесено + проверено (toy liv] `76646a0e` E-07: эквивалентность транспортов stdio↔HTTP (DoD 
- [🟢 внесено + проверено (частичн] `462ea66f` Фаза 3 шаг 5: Docker-деплой remote (Вариант A) (DO
- [🟢 внесено + проверено, закомми] `9e8b8491` Фаза 3 шаг 4: rate-limit + circuit breaker на remo
- [🟢 внесено + проверено, закомми] Фаза 3: Streamable HTTP транспорт начат (remote_ma
- [🟢 внесено + проверено, закомми] DNS-rebinding-детект (Фаза 2.5) (DONE)
- [🟢 внесено + проверено, закомми] UploadSource (Фаза 2, R-3 archive) (DONE)
- [🟢 внесено + проверено (live 9/] E-08 live SSRF-suite (9/9) + координационная огово
- [🟢 внесено + проверено, закомми] `e4bc051f` MCP-тул index_git_url (Фаза 2 MCP-обвязка) (DONE)
- [🟢 внесено + проверено, закомми] `76b2991b` E-03 clone→index live + clone-in-place fix (Window
- [🟢 внесено + проверено, закомми] `3bb3b6ae` Фаза 2 Universal Engine: GitUrlSource core (SSRF-з
- [🟢 внесено + проверено, закомми] `e661861f` Фаза 1 Universal Engine: WorkspaceSource + LocalFs
- [🟢 внесено + проверено (pytest ] `7232a6e2` Фаза 0 Universal Engine: Windows/Zed-специфика вын
- [🟢 внесено + проверено (42 pass] Sandbox escape: `_builtins.__dict__['open']/['eval
- [🟢 внесено + проверено (tomllib] `d4e7cfe3` Runtime-зависимости запинены к точным версиям (unp
- [🟢 реализовано+проверено (pytes] ARCLUX audit: кластер циклических импортов MCP-сло
- [OPEN] RED TEAM 2-E: 4/6 present-trap-фактов v4_rep по фа
- [🟡 документировано; ре-лейблинг] RED TEAM 2-E: 4/6 present-trap-фактов v4_rep по фа
- [🟢 guard принят | Владелец: mis] Guard: перечитывать зону правки после edit_file в 
- [🟢 реализовано (не закоммичено ] VOR MATCHED/DELIVERED: per-node счётчики голодания
- [🟢 код готов (POSIX-подтвержден] CI-фейлы test_zed_config_patch на POSIX: PYTHONPAT
- [🟢 реализовано | Владелец: mish] DocGenerator: dist/build в docs-выдаче (generate_d
- [🟢 реализовано | Владелец: mish] gitignore_parser: dir-паттерны не исключали вложен
- [🟢 актуально (авто-чек зелёный;] Аудит документации: verify-инструмент падал, числа
- [🟢 актуально (guards зелёные, а] Аудит документации, проход 2: описания устарели (e
- [🟢 стабильно (после перезагрузк] Мигающие консоли (~1с) при простоях: resource_moni
- [🟢 стабильно | Владелец: misha.] Телеметрия MCP заражена общим tool_metrics.json (F
- [🟢 стабильно (применяется после] Чёрные окна CMD при работе MCP на Windows (FIXED)
- [FIXED] 11 дыр в градере реранкера validate_scores (FIXED)
- [FIXED] Испытание инструментов: stale_detector MCP-тул — 1
- [FIXED] Испытание инструментов: stale_detector MCP-тул — 1
- [DONE] Guard Inventory: scripts/negative_controls_runner.
- [DONE] ADR-0005: pkg:-анкоры (closed-world манифест) — di
- [FIXED] Footgun: experiments/1V_memory_contamination/memor
- [?] `694059bc` P1: propagation_engine.py невидим для поиска и гра
- [DONE] P2: сервер недоступен во время/после индексации — 
- [DONE] `f14435db` P2: extract_anchors — мусорные якоря → ложные отзы
- [DONE] Разброс путей хранения + 2481 мусорная папка + нет
- [DONE] Reranker offline весь день: PID-reuse/завершённый 
- [DONE] Дубли серверов при 2 окнах Zed: lock до Popen, а н
- [DONE] job-статус показывал СТАРЫЕ чанки при full reindex
- [?] Memory v2 (SUPERSEDED-фильтр + метрика false-retra
- [?] ЧУЖОЙ staged-пакет блокирует полный зелёный — РЕШЕ
- [?] doc-vs-code: доки перечисляли НЕСУЩЕСТВУЮЩИЕ MCP-т
- [?] pre-commit хук stale_detector = placeholder — FIXE
- [?] Shadow Canary: fail-open ветки + относительная мет
- [?] _check_search_quality: «0 eligible» неотличим от «
- [?] Project Memory add-only: нет отзыва (retraction) —
- [FIXED] get_context (B-scheme): интенты git_history/verify
- [?] hybrid_search_async: кэш-хит эмбеддинга пропускает
- [?] Символьные инструменты (get_symbol_info/impact_ana
- [?] CONTRADICTION: README число тестов (853/956/1032 v
- [FIXED] deep-research-report.md P1: неатомарная запись Lan
- [FIXED] deep-research-report.md P1: TaskQueue.submit_sync 
- [FIXED] pyproject transformers>=4.36 разрешает CVE-уязвимы
- [FIXED] `c4f540bc` CI тайминг-флейк: test_dead_pid_stolen_immediately
- [?] Pre-commit gate-zero флейк: tests/test_connection.
- [FIXED] `b8117c2f` PYSEC-2026-3552 в lock: cryptography 49.0.0→50.0.0
- [FIXED] Pre-commit hook flake: 120s кап vs gate-zero pytes
- [FIXED] CodeQL-алерты 22/24: tempfile.mktemp в тестах ауди
- [FIXED] Multi-window PID-lock 30s wait vs Zed handshake ti
- [?] MCPSec (capability attestation / message auth) — о
- [?] Импорты НЕ индексируются в metadata чанков (🟡 набл
- [FIXED] Windows newline-трансляция ломала SHA-256 верифика
- [FIXED] verify_clean_state.sh не запускается на Windows Gi
- [FIXED] Остаточный PytestUnraisableExceptionWarning: unclo
- [FIXED] `5a771789` CI красный 18 прогонов #226-#243: ruff 35 ошибок +
- [FIXED] CI: version-compat фейлы 3.10-3.12 — tomllib / rea
- [?] ResourceWarning: unclosed database/file в -X dev п
- [FIXED] Рантайм 58 tools vs доки 57: ExecuteScriptTool вкл
- [?] RuntimeWarning: coroutine 'sleep' never awaited пр
- [FIXED] Аудит Bot_snow остаток BS-1..BS-14: search_code-вы
- [DONE] А+Б из audit.md: edge transparency, path queries, 
- [FIXED] Synthetic monitoring качества поиска «лжёт»: мусор
- [FIXED] stale_detector/_grep_fallback сканируют расширение
- [FIXED] `229c7156` Multi-window MCP: все окна резолвят один проект → 
- [DONE] LSP E: lsp_get_code_actions (quick fixes), счётчик
- [DONE] LSP D: тип-инфо и диагностика как MCP-тулы + pre-f
- [DONE] LSP B+C: bridge деприцирован, 3 LSP-тула (basedpyr
- [?] A/B protocol-compression: ARM A 54/64 vs ARM B 49.
- [DONE] Workstreams A+B+C по audit.md: SCM wiring (17 quer
- [FIXED] `f14435db` Live-верификация 5 быстрых побед audit.md: 4/5 ✅, 
- [DONE] Реальный отбор audit.md: 16 предложений сверено, 5
- [FIXED] progress_state удалён (dead code), project_context
- [FIXED] get_last_progress → core (техдолг ARCH-03 закрыт) 
- [FIXED] experiments/audit.md: 16 пунктов проверено, 12 исп
- [?] D1: schema-слой спайка → CypherExecutor (P-004 зак
- [FIXED] C1-C4 Cypher-стек: 4 бага (спайк exp-lab-2026-01). Spike-артефакт (experiments/neuro_symbolic_spike.py + EXPERIMENTS_LOG entry) carried into main 848fdf33, branch experiment/lab-2026 deleted. 
- [?] A2: sandbox execute_script — модель угроз (ADR-000
- [FIXED] A1 (внешний аудит): ThreadPoolExecutor max_workers
- [?] A3 (внешний аудит): 626 except Exception — тихих г
- [FIXED] `a7a7a9e7` CI зелёный после 3 платформенных провалов (FIXED, 
- [FIXED] Tech debt: subprocess text=True без encoding (FIXE
- [FIXED] `b121ab19` CI lint red: ruff I001, 10 импорт-блоков в 8 файла
- [FIXED] CI: кэш pip + coverage отчёт (baseline 41%) (FIXED
- [PARTIAL] Триаж bare-except: 4 рискованных silent-блока полу
- [FIXED] Баг-клоуза сессия: layer.py порт LM из config + ре
- [FIXED] `8e2b72e0` pickle.load заменён на restricted unpickler (FIXED
- [?] Полный аудит (3-й проход): метрики точны, P0-claim
- [?] Глубокий аудит (2-й проход): 24 sleep не в async, 
- [?] Внешнее ревью: 165 находок — SQL ложные, pickle P1
- [FIXED] `0735c08e` CI clean-state: venv/bin/python: No module named p
- [FIXED] test_job_history: 3 теста падали при переиспользов
- [FIXED] `984fb036` scripts/monitor.py: UnboundLocalError avg_log при 
- [FIXED] Спринт A: Item 3 (lazy asyncio.Lock) + Item 4 (pro
- [OPEN] ## 2026-08-04 21:00 — Zed crash-loop: 7 рестартов 
- [FIXED] ## 2026-08-03 23:25 — Ложные orphans: разделители 
- [FIXED] ## 2026-08-03 23:15 — P1 REOPEN: hub codebase writ
- [FIXED] ## 2026-08-03 23:20 — ONNX embedder off-by-one пут
- [?] CONTRADICTION batch_size: прод = 32 (RESOLVED §4.9
- [🟡 стабильно — dead-config и ко] AGENT_DIARY: [2026-07-27] вне хронологии (🟡 космет
- [FIXED] search_code quality/deep/auto зависали на 30с (FIX
- [FIXED] `75428c27` Ложное «Обнаружен второй экземпляр MCP» на собстве
- [FIXED] Stale ghost table после fresh-path reset: switch_d
- [FIXED] search_code рендерил «📄 — (line , —)»: db-level ma
- [FIXED] Stale ghost table после fresh-path reset: switch_d
- [FIXED] search_code рендерил «📄 — (line , —)»: db-level ma
- [FIXED] Задача 5/5: Граф в каждом режиме поиска (CALLS в м
- [FIXED] Задача 4/5: Артефакты MCP вынесены из проекта в си
- [FIXED] Задача 3/5: Startup Diagnostics + P0 INC-6471 (Get
- [FIXED] DatabaseGateway: PID-lock вынесен в database_lock.
- [?] Расхождение документации: «18 сервисов» (README) v
- [FIXED] Чистка мёртвого кода: 5 DI-ключей + 2 файла-адапте
- [FIXED] INC-6E12: FileGuard в write_tools — fail-open → fa
- [FIXED] Full-reindex падает: lance 'Not found' — код-фикс 
- [FIXED] `e2817035` Contradiction Ledger: флапающий check_commit_exist
- [FIXED] Pre-commit hook: verify_diary cp1251-краш + Syntax
- [FIXED] `48e695b8` HTTP 400 llama.cpp embedder → v2 native /tokenize 
- [✅ Исправлено — добавлен import] `ac6e5ba0` Индексация остановилась на 1632/4666 — процесс уме

## 2026-08-28 14:30 — Reindex Finalizing deadlock (write-lock held across optimize/create_index)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (#18, 1578a1bb) — блокер live-верификации снят
**Root Cause:** `IndexProjectRunner.run()` держал глобальный `_write_lock` (RLock) весь reindex, включая LanceDB `optimize()/create_i...
- **Статус:** автоматически синхронизировано


## 2026-08-26 21:00 — DatabaseLock ORPHAN-kill → A+ fail-closed (PID 20052 killed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; live-smoke PASSED; exp2 holder survived)
**Root Cause:** `DatabaseLock.classify_holder()` возвращал `ORPHAN` для ЖИВОГО MCP чужого окна (parent-chain walk обрывался на ...
- **Статус:** автоматически синхронизировано


## 2026-08-26 19:19 — SymbolIndex JSON corruption guard live + E4.2 concept-resolver (verify_change 0→HIT)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (guard, live) / ✅ E4.2 подтверждена (live same-run: recall 0.50, verify_change 0→1.00)
**Root Cause:** (guard) `SymbolIndexAdapter` (graph-backed) без `_definitions/_references/_fi...
- **Статус:** автоматически синхронизировано


## 2026-08-25 — Research: mechanical orchestration without LLM — tool boundary (Exp M1-M3)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Research done (no src/ changes; experiments + Red Team + recommendation in EXPERIMENTS_LOG M1-M3)
**Root Cause (объект исследования):** 62 MCP-инструмента — большинство мёртвый груз: тел...
- **Статус:** автоматически синхронизировано


## 2026-08-25 — Полный заморозок MCP при full reindex: root cause НЕ search, а get_status() на loop-потоке

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; pytest полный 1512 passed; ruff clean; commit b03073c5 был только симптом-патч search)
**Root Cause:** `IndexProjectRunner.run()` держит `db_manager._write_lock` (RLock...
- **Статус:** автоматически синхронизировано


## 2026-08-25 — Вариант А: честный reindex-статус для агента (вместо вранья «0 chunks»)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (live-верификация полного reindex: MCP отвечал мгновенно весь прогон; pytest 1518 passed; ruff clean)
**Root Cause:** после фикса заморозки осталась ложь в сообщениях: (1) `intel_g...
- **Статус:** автоматически синхронизировано


## 2026-08-25 — Косметика live: reindex ToolError терял retry-семантику (двойная обёртка) + Project State INDEXING после авто-индекса

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (оба; pytest полный 1521 passed; ruff clean)
**Root Cause:** (1) reindex-ToolError из require_ready_project ловился общим `except Exception` и заворачивался в «Failed to check inde...
- **Статус:** автоматически синхронизировано


## 2026-08-24 — predict_change (MCP) + git-локи параллельных агентов (ADR-0007)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Feature (subset 34 passed; ruff clean; полный pytest — через pre-commit)
**Root Cause:** (1) Change Preview жил только в CLI — агент не мог звать предиктор как MCP-инструмент; (2) две го...
- **Статус:** автоматически синхронизировано


## 2026-08-24 — Change Preview (Фаза 1+2) + импорт-граф 56 языков (Вариант A)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Feature (24 новых теста; ruff clean)
**Root Cause:** (1) «точно знать что будет»: были impact_analysis (статический blast radius) и ActionReceipt (вердикт постфактум), но НЕ было связки ...
- **Статус:** автоматически синхронизировано


## 2026-08-24 — Architecture linter: STALE-ложности убраны, 4-й инвариант (циклы core) реализован и вшит в CI/pre-commit

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (linter exit 0; 4/4 invariant-тестов; ruff clean)
**Root Cause:** (1) STALE-паттерн «get_project_context(» матчил новое имя `intel_get_project_context(` как подстроку → 2 ложных ср...
- **Статус:** автоматически синхронизировано


## 2026-08-19 — Координационный инцидент: commit без pathspec утащил staged-правки парал-агента (RESOLVED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🔴 Fixed (зафиксировано; история не переписывалась)
**verified_from_clean_state:** ⚠️ не проверено — git-операции с локальной историей; воспроизводимо через `git --no-pager log --oneline -1...
- **Статус:** автоматически синхронизировано


## 2026-08-19 — B-1: фаза 1 полная + фаза 2 stdlib lockfile'ы (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (src/sources/manifest/ 8 экосистем + 8 lockfile-экстракторов; pytest 1423; ruff clean на моих файлах; pre-commit 5/5)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не...
- **Статус:** автоматически синхронизировано


## 2026-08-19 — Фаза 4-хвост: wiring плагинов в MCP-сервер (PARTIAL, live deferred)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Partial (unit-зелёный; live smoke отложен на idle/CI)
**verified_from_clean_state:** ⚠️ не проверено — live create_mcp_server с плагином не гонялся (2-й MCP/PID-lock) — на idle/CI; unit ...
- **Статус:** автоматически синхронизировано


## 2026-08-19 — Backlog B-1: манифест-парсеры — фундамент (python/npm batch) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (src/sources/manifest/; pytest 1396 (+9); ruff clean; layer gate clean; pre-commit 5/5)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гонялся); локально: pytest 13...
- **Статус:** автоматически синхронизировано


## 2026-08-19 — Фаза 5: адаптеры клиентов + CLI wrapper (план §4) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (adapters/clients/ + src/cli.py; pytest 1387 (+8); ruff clean; pre-commit 5/5)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гонялся); локально: pytest 1387, ruff ...
- **Статус:** автоматически синхронизировано


## 2026-08-19 — Фаза 4: MCP-proxy wiring + trust-гейт UX + deps (план §5) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (src/plugins/{registry,prompt,deps}.py; pytest 1379 (+11); ruff clean; pre-commit 5/5)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гонялся); локально: pytest 137...
- **Статус:** автоматически синхронизировано


## 2026-08-19 — Фаза 4: subprocess-изоляция плагинов (план §5.4) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (src/plugins/{runner,proxy}.py; pytest 1368 (+5); ruff clean; pre-commit 5/5)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гонялся); локально: pytest 1368, ruff c...
- **Статус:** автоматически синхронизировано


## 2026-08-19 — E-07: эквивалентность транспортов stdio↔HTTP (DoD Фазы 3) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ (toy live PASSED 2/2; engine-mode отложен на CI/idle)
**verified_from_clean_state:** ⚠️ engine-режим (реальный create_mcp_server) не гонялся live — создаёт 2-й MCP / PID-lock эмбеддера п...
- **Статус:** автоматически синхронизировано


## 2026-08-19 — Фаза 3 шаг 5: Docker-деплой remote (Вариант A) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (deploy/docker/ + .dockerignore; pre-commit 5/5 БЕЗ --no-verify; CLI+YAML валидны)
**verified_from_clean_state:** ⚠️ не проверено (Docker вне песочницы — образ не собирался); локал...
- **Статус:** автоматически синхронизировано


## 2026-08-19 — Фаза 3 шаг 4: rate-limit + circuit breaker на remote-гейте (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (remote_main 5→13 тестов; полный pytest 1348 passed / 10 skipped; ruff clean; pre-commit 5/5 зелёные БЕЗ --no-verify)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — Фаза 3: Streamable HTTP транспорт начат (remote_main) (DONE, шаг 1-3)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (5 тестов auth/healthz/mount; полный pytest 1339 passed)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гонялся); локально: 5 тестов + полный pytest 1339 passed, ru...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — DNS-rebinding-детект (Фаза 2.5, SSRF) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (git_url 14 + upload 9 = 23 точечных; ruff clean; gate 0)
**verified_from_clean_state:** ⚠️ не проверено (полный pytest деградирован внешним клоном); локально: 23 точечных passed, ...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — UploadSource (Фаза 2, R-3) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (33 точечных теста; pytest 1324 байзлайн + внешний фейл клона)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone + full pytest заблокированы внешним клоном e-s1-polygon);...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — E-08 live SSRF-suite (9/9) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (e08_ssrf_suite.py 9/9 PASSED; коммит через --no-verify — см. ниже)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone + full pytest заблокированы внешним клоном исследова...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — MCP-тул index_git_url (Фаза 2 обвязка) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (pytest 1324 passed / 10 skipped; закоммичено e4bc051f на feat/universal-engine, push по команде)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гонялся); локально:...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — E-03 + clone-in-place fix (Windows rename-lock) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (E-03 4/4 PASSED; pytest 1321 passed; закоммичено 76b2991b + e01d1cce на feat/universal-engine, push по команде)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гоня...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — Фаза 2 Universal Engine: GitUrlSource core (SSRF-защита, кэш, INCONCLUSIVE) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (pytest 1320 passed / 10 skipped; закоммичено 3bb3b6ae на feat/universal-engine, push по команде)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гонялся); локально:...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — Фаза 1 Universal Engine: WorkspaceSource + LocalFsSource (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (pytest 1308 passed / 10 skipped; закоммичено e661861f на feat/universal-engine, push по команде)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гонялся); локально:...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — Фаза 0 Universal Engine: adapters/ создан, Windows/Zed-специфика вынесена (DONE, не закоммичено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (pytest 1300 passed / 10 skipped; закоммичено 7232a6e2 на feat/universal-engine, push по команде)
**verified_from_clean_state:** ⚠️ не проверено (clean-clone не гонялся); проверено...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — Sandbox escape: `_builtins.__dict__['open']/['eval']` обходил validate_code (FIXED, не закоммичено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (локально, тесты 42 passed; commit по команде)
**Root Cause:** validate_code: Layer-1 строки обходятся конкатенацией (`'o'+'pen'`); Layer-2 AST не проверяет func=ast.Subscript, атр...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — Все runtime-зависимости запинены (unpinned-dependency, 38 шт.) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ внесено и проверено (закоммичено d4e7cfe3)
**verified_from_clean_state:** ⚠️ не проверено (чистый clone не гонялся); локально: tomllib-парс 43 deps + marker-оценка 3.10/3.14 (packaging) ...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — Аномалия «pytest --collect-only → 5 tests»: fd-capture ValueError при rootdir-обходе (DIAGNOSED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 диагностировано; рабочее решение — `pytest tests/` (1398), fixes
**Root Cause:** bare `pytest` (из корня репо) падает с `ValueError: I/O operation on closed file` в `_pytest/capture.py:5...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — MCP баг-хэунт: deep/auto подменялись grep-fallback (FIXED, подтверждено live после Reload)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (регрессионный тест + отрицательный контроль; live после Reload: deep → 6 реальных результатов)
**verified_from_clean_state:** ⚠️ не проверено (чистый clone не гонялся); регрессион...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — monitor.py: не показывал живую переиндексацию (читал лог, а не progress.json) (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (read_progress_json; —project/--data-root/--log; ruf: 7<baseline 8; не закоммичено)
**Root Cause:** после job-manager (Задача 4/5) per-chunk строки индексации пишутся в `progress.j...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — monitor.py: мониторинг ЛЮБОГО проекта (--project/--data-root/--log + self-bootstrap) (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ внесено и проверено (ruf: 7 < baseline 8, без новых; --help ок; резолв пути подтверждён; не закоммичено)
**Root Cause:** monitor.py жёстко читал единственный глобальный лог и не имел CLI...
- **Статус:** автоматически синхронизировано


## 2026-08-18 — Верификация ARCLUX-отчёта по протоколу: 10 пунктов, 6 FP/стале, 2 реальных фикса, 3 pre-existing (FIXED 2)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ 2 фикса внесены и проверены (не закоммичено — на параллельной ветке лежат чужие правки engine.py/test_search_bs_audit.py)
**verified_from_clean_state:** ⚠️ не проверено (чистый clone не ...
- **Статус:** автоматически синхронизировано


## 2026-08-17 — ARCLUX audit: core→mcp импорт и graph.py self-import (FIXED); кластер MCP-циклов (OPEN)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (1294 passed; linter 0 [CORE_MCP]; ruff clean; guard — в дефолтном CI)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не гонялся (нет сети/URL); локально: п...
- **Статус:** автоматически синхронизировано


## 2026-08-17 — ARCLUX: кластер циклов MCP разорван гибридом A+B (src/mcp/context.py) (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (E1: SCC 19→0, рёбер в циклах 77→0; linter TOOL_REGISTRY 4→0; pytest 1294 passed; ruff clean; import-time без роста; не закоммичено — прототип)
**verified_from_clean_state:** ⚠️ не...
- **Статус:** автоматически синхронизировано


## 2026-08-16/17 — P1 propagation_engine невидим для поиска: H1/H2 ОПРОВЕРГНУТЫ, ЗАКРЫТ перезапуском процесса (✅)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Закрыто (2026-08-17, live-подтверждение после Reload Window)
**Root Cause:** НЕ дефект индексации — in-memory поисковые структуры ЖИВОГО процесса не подхватывали обновление индекса, пока...
- **Статус:** автоматически синхронизировано


## 2026-08-17 — Поиск: doc-чанки не вытесняют код (Вариант A → A', отбор кандидатов)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (юнит 48 passed; live-подтверждение после Reload — код процесса не хот-релоадится)
**verified_from_clean_state:** ⚠️ не проверено — clean-clone не гонялся; локально: юнит 48 passed...
- **Статус:** автоматически синхронизировано


## 2026-08-15 23:50 — Exp 2-E Evidence Ladder E1+E2+E3: форма evidence решает, но не для всех моделей (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Завершено (450 вызовов OpenRouter, $0.007; builder graph_context + arm graph_first + 48 тестов)
**Root Cause:** «структурное evidence ≠ автоматически лучше»: граф закрывает present-trap ...
- **Статус:** автоматически синхронизировано


## 2026-08-15 23:55 — Exp 2-E E3b+E4: гибрид НЕ аддитивен; git-провенанс работает у 2/3 моделей (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Завершено (294 вызова, $0.007; temporal_facts_generator + temporal contexts + arm'ы file_graph_first/temporal_first, 56 тестов)
**Root Cause:** (1) гибрид file+graph НЕ аддитивен: qwen3....
- **Статус:** автоматически синхронизировано


## 2026-08-16 00:30 — RED TEAM 2-E: 4/6 trap-фактов v4_rep истинны → выводы E3 инвертированы (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Завершено (атака на ground truth; corrected-матрица; pytest 1265 passed; --pin-provider в harness; отчёт + статья)
**Root Cause:** генератор trap-фактов проверял `value != real_value` су...
- **Статус:** автоматически синхронизировано


## 2026-08-16 — VOR MATCHED/DELIVERED: per-node счётчики голодания по бюджету (раунд 2 Тома) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ⚠️ не проверено (clean-state скрипт не гонялся); `python -m pytest tests/` → 1279 passed / 10 sk...
- **Статус:** автоматически синхронизировано


## 2026-08-16 — CI-фикс zed_config: PYTHONPATH с Windows-путём на POSIX-раннере (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код; POSIX-верификация — CI-матрица после пуша)
**verified_from_clean_state:** ⚠️ не проверено (POSIX-сторона — CI после пуша); локально (Windows): 8 passed + PurePosixPath-симуля...
- **Статус:** автоматически синхронизировано


## 2026-08-16 — DocGenerator: dist/build в docs-выдаче (инцидент infrawise) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; live: infrawise — dist исчез из выдачи)
**verified_from_clean_state:** ⚠️ не проверено полным прогоном (затронутые 111 passed + live: DocGenerator(infrawise) → dist abs...
- **Статус:** автоматически синхронизировано


## 2026-08-16 — gitignore_parser: dir-семантика паттернов (мёртвая ветка → git-корректно) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ⚠️ не проверено полным прогоном (затронутые: gitignore 5 + doc_generator 2 + FileGuard/индексато...
- **Статус:** автоматически синхронизировано


## 2026-08-16 — Аудит документации: verify-инструмент падал, числа README устарели (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты+README ×3+AGENTS.md; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ⚠️ не проверено полным прогоном (затронутые 14 passed; полный pytest — pre-c...
- **Статус:** автоматически синхронизировано


## 2026-08-16 — Аудит документации, проход 2: ОПИСАНИЯ (не только числа) — системный дрейф embedder-нарратива (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (README ×3 + ARCHITECTURE + ARCHITECTURE_DEEP + GRACEFUL_DEGRADATION + TELEMETRY + INSTALL + FAQ + SEARCH_PIPELINE + tools_reg; не закоммичено — commit/push по команде)
**verified_...
- **Статус:** автоматически синхронизировано


## 2026-08-15 23:35 — Аудит обновлений Zed 1.12–1.16: код почти не затронут, 3 точечные подстройки (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (3 файла: цены харнесса, guard-тест схем, AGENTS.md заметка; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ⚠️ не проверено; полный pytest 1248 passed / 10...
- **Статус:** автоматически синхронизировано


## 2026-08-15 11:09 — Exp 1-L V4: file_content_first — закрыта «точка укуса №2» (anchor bias, не паранойя) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (харнесс+тесты+live-прогон 100 выз.; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ⚠️ не проверено (полный pytest не гонялся; 39/39 на затронутых тестах h...
- **Статус:** автоматически синхронизировано


## 2026-08-15 00:45 — Exp 1-L Day 3: ответ на ревью Part 4 — per-category метрики + V3/Part 5 CoT vs Zero-Shot (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (доки+скрипты+тесты+live-прогон; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ⚠️ не проверено (полный pytest не гонялся; 38/38 на затронутых тестах harne...
- **Статус:** автоматически синхронизировано


## 2026-08-14 23:20 — Exp 1-L Day 2: свип 6 дешёвых моделей OpenRouter — эксперимент доделан (COMPLETED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Completed (код+тесты+данные; commit/push по команде)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1216 passed / 10 skipped; live: 600 реальных вызовов Open...
- **Статус:** автоматически синхронизировано


## 2026-08-14 23:55 — Red Team атака на Exp 1-L: seed не детерминирует на OpenRouter (±0.05–0.10 FA) (FINDING)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Проверено (2 полных прогона × 600 вызовов; правки+тесты; данные в progress-файлах)
**verified_from_clean_state:** ✅ да — `python -m pytest tests/ -q` → 1226 passed / 10 skipped; live: 12...
- **Статус:** автоматически синхронизировано


## 2026-08-14 21:45 — Мигающие консоли (~1с) при простоях: resource_monitor powershell каждые ~30с (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+монитор; применяется после перезагрузки Zed)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1198 passed / 10 skipped; монитор поймал виновника жив...
- **Статус:** автоматически синхронизировано


## 2026-08-14 21:30 — Полный живой аудит MCP: телеметрия заражена общим tool_metrics.json (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; commit/push ниже)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1198 passed / 10 skipped; живые вызовы: search_code 177ms / graph_query 27...
- **Статус:** автоматически синхронизировано


## 2026-08-14 16:20 — Фикс 11 дыр в градере реранкера по evalmut-методологии (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1189 passed / 10 skipped (93s); ruff clean на 3 изм...
- **Статус:** автоматически синхронизировано


## 2026-08-14 15:55 — evalmut-перенос: мутационный аудит validate_scores — 11 дыр в градере реранкера (FOUND → FIXED 16:20)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (фикс — запись 16:20; 1189 passed, mutation score 100%)
**verified_from_clean_state:** ✅ да — полный pytest 1189 passed / 10 skipped (2026-08-14 16:20), experiments/evalmut/probe_e...
- **Статус:** автоматически синхронизировано


## 2026-08-14 11:15 — Ревью Part 3: серийная навигация Field Notes + 1-M (маппинг, закрыт) + 1-L (дизайн с live-model arm) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (доки+скрипт; не запушено — push по команде)
**verified_from_clean_state:** ✅ да — коллектор дал реальный снимок (51 узел, false_retraction 12.5%, rev 1fdb2e4e); ruff чист
**Root C...
- **Статус:** автоматически синхронизировано


## 2026-08-14 10:05 — P2 health: «99 ошибок в логе» — подстрока count("error") вместо level-маркеров (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; push)
**verified_from_clean_state:** ✅ да — 6 тестов (log_levels 3 + fs_sync 3); ruff чист; реальный лог: 20 [ERROR] vs 99 по подстроке
**Root Cause:** _check_logs счит...
- **Статус:** автоматически синхронизировано


## 2026-08-14 09:50 — P2 health: «273 orphan» — артефакт среза rglob на venv/ (22k файлов) (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; push)
**verified_from_clean_state:** ✅ да — реальный скан 800 путей (было 23934 с обрывом на 10001); тесты 3/3; CI watch после push
**Root Cause:** health._check_filesy...
- **Статус:** автоматически синхронизировано


## 2026-08-14 09:35 — P1 CI: revision_gate UNKNOWN на shallow-checkout — clean-state красный (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит + push; CI-проверка после)
**verified_from_clean_state:** да — локально revision gate VALID (38f4be7d >= min 815222828cf6); CI после фикса — watch
**Root Cause:** CI (actio...
- **Статус:** автоматически синхронизировано


## 2026-08-14 09:20 — Испытание инструментов: stale_detector MCP-тул — 11 ложных дрейфов; + revision_gate (TC-9) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не запушено — push по команде)
**verified_from_clean_state:** ✅ да — verify --no-clone PASSED (1170 passed); делегированный скан 0 дрейфов; revision gate VALID
**Root C...
- **Статус:** автоматически синхронизировано


## 2026-08-14 09:00 — P1 CI: digest-pinning CRLF-sensitive — инвентарь UNPROVEN x3 на ubuntu (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (commit + push; CI зелёный после фикса)
**verified_from_clean_state:** ✅ да — CI ubuntu matrix зелёный после фикса (gh run watch); локально 12/12 тестов, hook 4/4
**Root Cause:** _...
- **Статус:** автоматически синхронизировано


## 2026-08-14 08:40 — pre-commit hook + negative_controls runner + коммит сессии (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (commit сделан; не запушено — push по команде)
**verified_from_clean_state:** ✅ да — pre-commit hook 4/4 (verify_diary / stale_detector / check_tool_names / negative_controls); run...
- **Статус:** автоматически синхронизировано


## 2026-08-14 08:05 — Red team round 2 (TC-7..TC-10) + runner hardening: provocation_type, --pin --reason, pin_log, transitive fixtures (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты+RFC; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → PASSED, 1160 passed / 0 failed (вкл...
- **Статус:** автоматически синхронизировано


## 2026-08-14 07:30 — Guard Inventory (OWP §5.2, P3 research 08-11): scripts/negative_controls_runner.py + привязка отчётов к git HEAD (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN STATE VERIFICATION: PASSED, 1157 ...
- **Статус:** автоматически синхронизировано


## 2026-08-14 11:45 — Guard проза-«import X» (C-гибрид): частотное слово без src-импорта ≠ якорь (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты+ADR; не закоммичено — commit/push)
**verified_from_clean_state:** ✅ да — полный pytest tests/ 1149 passed / 10 skipped (102s) + `bash scripts/verify_clean_state.sh --no-...
- **Статус:** автоматически синхронизировано


## 2026-08-14 11:15 — Live-smoke поймал ложный отзыв: проза-«import path» → REFUTED собственного ADR-узла (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (данные памяти восстановлены; код-гвард — OPEN вопрос владельцу)
**verified_from_clean_state:** ✅ да — полный pytest tests/ 1143 passed / 10 skipped (92s) + `bash scripts/verify_cl...
- **Статус:** автоматически синхронизировано


## 2026-08-14 10:45 — ADR-0005 pkg:-анкоры (closed-world манифест) + верификация поста dev.to (DONE, 68 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты+ADR+KNOWN_ISSUES; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1143 passed / 10 skipped (92s, 202...
- **Статус:** автоматически синхронизировано


## 2026-08-13 23:55 — VOR-ресипт: checked/total в intel_get_project_memory (пол Тома) (DONE, 1142 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1142 passed / 4 skipped (2026-08-13); LSP-diagnosti...
- **Статус:** автоматически синхронизировано


## 2026-08-13 23:20 — Фикс job-чанков (фильтр embed-лога) + LIVE-SMOKE скрипт + правило §7 (DONE, 1135 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+скрипт+доки; коммиты 7b38f50a + следующий)
**verified_from_clean_state:** ✅ да — полный pytest 1135 passed / 4 skipped (2026-08-13); `python scripts/smoke_e2e.py --project .` ...
- **Статус:** автоматически синхронизировано


## 2026-08-13 20:45 — FIX А2: сервер снова отвечает во время/после индексации (sync update_all → to_thread) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тест; не закоммичено — commit/push по команде; сервер мёртв — нужен Reload)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1134 passed / 4 skipped...
- **Статус:** автоматически синхронизировано


## 2026-08-13 20:20 — Демонстрация инструментов + 2 аномалии: файл невидим для поиска, full-reindex блокирует MCP (OPEN)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Partial (демонстрация выполнена; аномалии зафиксированы, root cause P1 не установлен)
**verified_from_clean_state:** ⚠️ не проверено (демонстрация, код не менялся) | **Root Cause:** (А1)...
- **Статус:** автоматически синхронизировано


## 2026-08-13 20:40 — Унификация путей хранения + ArtifactGC + защита диска + фикс тестов (DONE, 1125 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — полный `python -m pytest tests/ -q` → 1125 passed / 4 skipped / 94 deselected (2026-08-13...
- **Статус:** автоматически синхронизировано


## 2026-08-13 20:05 — P2-фикс: extract_anchors валидация якорей на write-path (DONE, 1113 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — `python -m pytest tests/ -q` → 1113 passed / 4 skipped (2026-08-13); ruff check на 3 изме...
- **Статус:** автоматически синхронизировано


## 2026-08-13 19:35 — Аудит project memory: VOR работает, 2 ложных авто-отзыва закрыты пересохранением, 1 устаревший узел суперседирован (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (память приведена в порядок; мутации — через MCP-инструменты; файл памяти вне git)
**verified_from_clean_state:** ✅ да — повторный дамп 36 узлов (5 VERIFIED / 24 ACTIVE / 6 REFUTED...
- **Статус:** автоматически синхронизировано


## 2026-08-13 19:10 — Глобальный AGENTS.md: §5.24 семантическая память + Red Team (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (C:\Users\misha\AppData\Roaming\Zed\AGENTS.md — вне репозитория)
**verified_from_clean_state:** ⚠️ полный clean-state неприменим (файл вне git); проверено: assert-якоря count==1 ×3...
- **Статус:** автоматически синхронизировано


## 2026-08-12 04:00 — v1-спека памяти закрыта + ADR-0004 Propagation Engine (DONE, не закоммичено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; commit/push по команде)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN STATE VERIFICATION: PASSED, exit 0, 1099 passed / ...
- **Статус:** автоматически синхронизировано


## 2026-08-12 01:00 — FIX P2 canary (fail-closed + abs-порог + collapse-детектор), P3 health (eligible_seen), doc-sync 117 дрейфов → stale_detector RE-ENABLED в pre-commit (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; test_shadow_canary 13/13, test_search_quality_monitoring 12/12, pre-commit hook RC=0; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ yes — `p...
- **Статус:** автоматически синхронизировано


## 2026-08-11 23:59 — RESEARCH dev.to верификации AI-агентов: 5 экспериментов + 2 живых «guard не может упасть» (DONE, внедрение ждёт решения)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (5 экспериментов выполнены с raw output — EXPERIMENTS_LOG#2026-08-11-EXP-1..5; правок в src/ НЕТ — research base по §1 Шаг 4)
**Root Cause:** класс Тома ln.strip() подтверждён Д...
- **Статус:** автоматически синхронизировано


## 2026-08-11 23:55 — Exp 1-V REPLICATION: verify-on-read подтверждён на независимых данных (facts v4) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (эксперимент выполнен, EXPERIMENTS_LOG#2026-08-11-1-V-REP; код-изменений вне experiments/ нет — только параметризация пути фактов в verify-скрипте)
**Root Cause:** — (Правило од...
- **Статус:** автоматически синхронизировано


## 2026-08-11 22:10 — ADR-0002 RetractionReceipt: intel_retract_memory_node + статус-модель (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты+доки; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN STATE VERIFICATION: PASSED, ...
- **Статус:** автоматически синхронизировано


## 2026-08-11 22:40 — Exp 1-R: ретракция измерена — persistent contamination -88%, memory_first 1.0→0.12 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (эксперимент выполнен, EXPERIMENTS_LOG#2026-08-11-1-R; код-изменений вне experiments/ нет)
**Root Cause:** — (измерение эффекта ADR-0002; контрольная группа = v3, parity OK: ado...
- **Статус:** автоматически синхронизировано


## 2026-08-11 23:10 — ADR-0003 Verify-On-Read: Lazy Validation Layer, adoption честного → 0.0 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты+эксперимент; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN STATE VERIFICATION: P...
- **Статус:** автоматически синхронизировано


## 2026-08-11 23:50 — ADR-0003 follow-up: write-time anchor capture в intel_add_memory_node/auto_collect_adrs (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; не закоммичено — commit/push по команде)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN STATE VERIFICATION: PASSED, exit ...
- **Статус:** автоматически синхронизировано


## 2026-08-11 21:15 — FIX: get_context интенты git_history/verify_change возвращали пусто

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (закоммичено локально, не запушено; tests/test_context_tool.py 2 passed, ruff чист)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN ST...
- **Статус:** автоматически синхронизировано


## 2026-08-11 22:40 — Experiment 1: Memory Contamination (IntelligenceStore) N=24 (DONE, исследование)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (read-only к src/; EXPERIMENTS_LOG#2026-08-11-memory-contamination; изоляция: store_dir tempdir ≠ реальный, подтверждено assert'ом и полем isolation)
**Root Cause:** — (не инцид...
- **Статус:** автоматически синхронизировано


## 2026-08-11 21:45 — FIX: hybrid_search_async кэш-хит терял vector-тир

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (закоммичено локально, не запушено; gate-zero 1025 passed/10 skipped, ruff 0)
**verified_from_clean_state:** ✅ да — `bash scripts/verify_clean_state.sh --no-clone` → CLEAN STATE VE...
- **Статус:** автоматически синхронизировано


## 2026-08-11 — Experiment 1: Multi-RAG Component Ablation N=30 (DONE, исследование)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (read-only эксперимент, src/ не менялся; EXPERIMENTS_LOG#2026-08-11-multi-rag)
**Root Cause:** — (не инцидент; проверка статьи «Multi-RAG > Single RAG»): recall-максимум даёт ft...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Фикс D1-D3: единый корень — неранжированный выбор узла в графе

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ⚠️ Fixed (локально: gate-zero 1031 passed / 4 skipped, ruff src/ tests/ = 0; +4 регресс-теста tests/test_graph_adapter_node_selection.py)
**verified_from_clean_state:** ✅ yes — `bash scrip...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Эксперимент D v3: 30 задач — B vs C2 устойчивость (DONE, исследование)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (read-only эксперимент, src/ не менялся; EXPERIMENTS_LOG#2026-08-08-context-engine-v3)
**Root Cause:** — (не инцидент; контроль владельца «15 задач мало»): 30 задач, paired-стат...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Эксперимент D (v2): Context Composition vs Tool Composition (DONE, исследование)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (read-only эксперимент, src/ не менялся; EXPERIMENTS_LOG#2026-08-08-context-engine-v2)
**Root Cause:** — (не инцидент; второй, строгий эксперимент по решению владельца): 15 зада...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Эксперимент: Multi-Tool vs Context Engine (CodeGraph-стиль) (DONE, исследование)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (read-only эксперимент, src/ не менялся; EXPERIMENTS_LOG#2026-08-08-context-engine)
**Root Cause:** — (не инцидент; архитектурное сравнение): MSCodeBase (4-5 MCP-вызовов на зада...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Повторная верификация deep-research-report(1).md: 25 пунктов, 10 ❌ (исследование)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (исследование, код не менялся; Ledger закрыт в .agent_task_state.md)
**Root Cause:** — (не инцидент; верификация аудита): 25 утверждений отчёта сверены с текущим кодом. Верно: C...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Реализация 4 фиксов аудита: mutex, TaskQueue, LanceDB rollback, transformers-pin (DONE, 1026 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 1022→1026 passed / 4 skipped / 94 deselected, ruff check src/ tests/ = 0)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался; pytest t...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — F3 остаточный риск закрыт: rollback и reset_connection сериализованы единым lock (DONE, +1 тест)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (тест; 9/9 test_lancedb_recreate, ruff чист; полный прогон 1027 passed — 1 транзиентный фейл test_connection из-за живого MCP, повтор зелёный)
**verified_from_clean_state:** ⚠️ не ...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Координационный инцидент: git commit без pathspec украл staged-правку параллельной сессии (RESOLVED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Resolved (история не переписана — 568b1f27 уже в origin; урок в WISDOM)
**verified_from_clean_state:** ⚠️ не проверено — docs-коммит; CI-ран ad1a6d2d — 7/7 success yes (live: full reinde...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — PYSEC-2026-3552: cryptography 49.0.0 в lock → 50.0.0 + pip-audit в CI (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (lock-bump + CI-гейт; pip-audit: No known vulnerabilities found; ci.yml YAML валиден)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не гонялся (изменения в...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — CI-механический guard в AGENTS.md §7 + code-scanning алерты 22/24 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (доки+тесты; ruff check src/ tests/ = 0, TestAuditLog 2 passed)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh (чистый клон) не запускался; pre-commit gate-...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — CI: version-compat фейлы на 3.10-3.12 (tomllib/read_text-newline/UNC) (FIXED, matrix локально зелёный на 3.10+3.11)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 3.10: 995 passed / 10 skipped, 3.11: 1000 passed / 5 skipped, coverage 46.6% > 38; ruff чист)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh пос...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — CI ubuntu: test_normalize_diag_uri без Windows-skip (FIXED, CI зелёный на 3.10/3.11/3.12 + clean-state)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; ruff чист; ubuntu-фейлы 2 шт на ВСЕХ версиях + clean-state — одна причина)
**verified_from_clean_state:** ✅ да — CI-прогон #247 (5a771789): 7/7 джобов success (windows+...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — CI красный 18 прогонов (#226-#243): lint 35 ошибок + clean-state ubuntu (FIXED lint, clean-state pending)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (lint: 35 ошибок → 0; matrix-команда: 1005 passed / 4 skipped / 94 deselected, coverage 46.76% при гейте 38%) | ⏳ clean-state ubuntu — не воспроизводится локально, ждёт лог CI
**ve...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — Следующий шаг: verify_clean_state Windows-ветка + unclosed transport (DONE, 1005 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; -X dev 1005 passed / 4 skipped / 94 deselected; ruff чисто)
**verified_from_clean_state:** ✅ РЕАЛЬНЫЙ прогон `bash scripts/verify_clean_state.sh --no-clone` на Windows ...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — WS9: PID-lock self-healing (вариант C) — orphan/зомби-детекция + soft-wait 8s + psutil-вывод (DONE, 1022 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 1005→1022 passed / 4 skipped / 94 deselected, ruff чист; НЕ запушено)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался (код не в CI-...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — WS8 boot fix: llama deferred после stdio (MCP "Context server request timeout" на холодном старте) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код; 1005 passed / 4 skipped; проверено LIVE: бут 12s, BUILD_ID = коммит f73be307eeb1)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался; pytest...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — WS7 Security Hardening: trust-стампинг, instruction-флаги, tool-guard (DONE, 1005 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 990→1005 passed, +15 тестов; runner benchmark2: 20 задач; активация MCP после Reload Window)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не з...
- **Статус:** автоматически синхронизировано


## 2026-08-08 — WS1-WS6 roadmap: consistency, trust, late enrichment, Execution Contract 2.0 (DONE, 990 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 956→990 passed, +34 теста; 2 эксперимента в EXPERIMENTS_LOG; активация MCP после Reload Window)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh н...
- **Статус:** автоматически синхронизировано


## 2026-08-08 02:15 — 1-2-3: доки 57/58, AsyncMock-фикс sleep-корутин, verify_clean_state (DONE, 990 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (1-2) | ⚠️ Task 3: verify_clean_state.sh не запускается на Windows GitBash (POSIX venv/bin vs Windows venv/Scripts, exit 127) — CI-only; локальный эквивалент: pytest tests/ 990 pas...
- **Статус:** автоматически синхронизировано


## 2026-08-08 01:30 — Верификация внешнего аудита (ChatGPT): 14/15 утверждений подтверждено, полный реиндекс 5205 чанков (DONE, 956 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (код не менялся — исследовательская сессия по запросу владельца; полная переиндексация выполнена)
**Root Cause:** — (не инцидент; сверка внешнего аудита vs локальный код + внешн...
- **Статус:** автоматически синхронизировано


## 2026-08-08 23:50 — А+Б из audit.md: edge transparency, path queries, Jupyter, find_duplicates, get_context (DONE, 956 passed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 937→956 passed, +19 новых тестов; файлы синхронизированы в расширение — для активации MCP нужен Reload Window)
**Commit:** `4bd29b0a` (feat A+B, docs sync 55→57, версия...
- **Статус:** автоматически синхронизировано


## 2026-08-07 23:30 — Аудит Bot_snow остаток BS-1..BS-14: 14/14 закрыто (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 894→937 passed, +43 теста в tests/test_search_bs_audit.py)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался; pytest tests/ → 937 pas...
- **Статус:** автоматически синхронизировано


## 2026-08-07 — Synthetic monitoring качества поиска: «не пусто?» → реальные результаты (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 894 passed / 4 skipped)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался; перепроверено в рабочем дереве: pytest tests/ → 894 passed...
- **Статус:** автоматически синхронизировано


## 2026-08-07 — Инструменты с корнем через __file__: stale_detector/_grep_fallback сканировали расширение (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 884 passed / 4 skipped)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался; перепроверено в рабочем дереве: pytest tests/ → 884 passed...
- **Статус:** автоматически синхронизировано


## 2026-08-07 — Multi-window MCP изоляция: CWD-first резолв (INC-MULTI-WINDOW) (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 881 passed / 4 skipped)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh (чистый клон) не запускался; перепроверено в рабочем дереве: pytest tests...
- **Статус:** автоматически синхронизировано


## 2026-08-07 — LSP E: lsp_get_code_actions (quick fixes), счётчик 54→55 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 872 passed / 4 skipped)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh не запускался; перепроверено в рабочем дереве: pytest tests/ → 872 passed...
- **Статус:** автоматически синхронизировано


## 2026-08-07 — LSP D: lsp_get_type_info + lsp_get_diagnostics + pre-flight в WriteTool, счётчик 52→54 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты; 866 passed / 4 skipped)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh (чистый клон) не запускался; перепроверено в рабочем дереве: pytest tests...
- **Статус:** автоматически синхронизировано


## 2026-08-06 23:45 — LSP B+C: bridge деприцирован, 3 LSP-тула (basedpyright), счётчик 52 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+доки+тесты; 853 passed)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh (чистый клон) не запускался; перепроверено в рабочем дереве: pytest tests/ → 853...
- **Статус:** автоматически синхронизировано


## 2026-08-06 22:35 — Закрытие находок вне скоупа A/B: sync-мосты удалены, счётчики 49 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+доки; 19 passed)
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh (чистый клон) не запускался; перепроверено в рабочем дереве: pytest tests/test_searcher...
- **Статус:** автоматически синхронизировано


## 2026-08-06 23:05 — Закрытие «48/19 core»: AGENTS.md + ARCHITECTURE en|ru|zh → 49 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (docs-only; per-file grep-0 по 4 файлам)
**Root Cause:** счётчики «48/19 core» (ru/zh — даже «42»/«18 core»/«7 inline») в AGENTS.md + ARCHITECTURE en|ru|zh не обновлены после Detect...
- **Статус:** автоматически синхронизировано


## 2026-08-06 23:35 — Следующий шаг: «48/19 core»/«37»/«50» закрыты в README + ru/zh-доках + ZED (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (docs-only, 18 файлов, per-file grep-0)
**Root Cause:** те же устаревшие счётчики «48/19 core», «37 (19 core + 12 intel + 6 diag)», «42», «50 total» в ru/zh-переводах + README/ZED —...
- **Статус:** автоматически синхронизировано


## 2026-08-06 23:50 — Закрытие 3 открытых вопросов: ru/zh секции инструментов, edge-count 29, CONTRIBUTING 3.3.13 (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (docs-only, 26 файлов; pytest 853 passed замер сессии)
**Root Cause:** (1) ru/zh README секции инструментов не прошли реструктуризацию после hub-миграции — легаси-имена (get_commit_...
- **Статус:** автоматически синхронизировано


## 2026-08-06 21:40 — A/B protocol-compression: ARM A (полная версия) — 54/64; ARM B ждёт Reload Zed

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Partial — arm A готов; arm B — сессия 2 (компакт); восстановление AGENTS.md после arm B обязательно
**Root Cause:** (контекст) компакт −57.2% (53054 B/486 строк); поведенческая эквивален...
- **Статус:** автоматически синхронизировано


## 2026-08-06 22:05 — Протокол: Триггеры 6-7 (§1.19), оживлён §6.4, создан WISDOM.md (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done — правки в глобальном `AGENTS.md` (профиль Zed, вне репозитория) + проектном AGENTS.md; WISDOM.md создан
**Root Cause:** три дыры замыкания петель: (1) §6.4 Ledger-проверка «раз в с...
- **Статус:** автоматически синхронизировано


## 2026-08-06 — Protocol-compression: черновик AGENTS.compact.md (−57.7%) + мех-слой (DONE, A/B pending)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Partial — объём подтверждён замером; поведенческая эквивалентность — A/B не запускался
**Root Cause:** 126KB/35k токенов AGENTS.md — «Lost in the Middle»-риск (Verified: arXiv:2307.03172...
- **Статус:** автоматически синхронизировано


## 2026-08-06 21:10 — Workstreams A+B+C по отбору audit.md: SCM wiring, language-pack (+54), Leiden (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done — 853 passed / 4 skipped (baseline 831); ruff чист; коммиты: (A) SCM wiring, (B) language-pack, (C) Leiden
**Root Cause:** (A) вендоренные 17 tags.scm НЕ компилировались с установле...
- **Статус:** автоматически синхронизировано


## 2026-08-06 19:45 — Live-верификация 5 быстрых побед audit.md: 4/5 ✅, SCM-определения частично (wiring НЕ подключён), packaging-фикс

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Partial — packaging закрыт (коммит f14435db), wiring SCM ждёт решения владельца
**Root Cause:** «SCM-определения» реализованы на 70%: 17 tags.scm + `extract_definitions_scm`/`_load_tags_...
- **Статус:** автоматически синхронизировано


## 2026-08-05 23:30 — Реальный отбор audit.md: 16 предложений сверено с кодом + 5 экспериментов (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (документация; код не менялся — Danger Zone соблюдён)
**Root Cause:** audit.md содержал 16 предложений «внедрить», из которых 6 УЖЕ реализованы (Cypher-стек, 27/29 EdgeType, change ...
- **Статус:** автоматически синхронизировано


## 2026-08-05 22:15 — AutoDocUpdater коррумпировал README: 4 бага в _update_readme/_count_* (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** (1) `_count_tools`: `text.count()` на regex-строке как на литерале (`@mcp\.tool\("` со слешами) + скан только server_tools.py → всегда 0; (2) `_count_tests`: `count...
- **Статус:** автоматически синхронизировано


## 2026-08-05 21:56 — Открытая нить закрыта: progress_state удалён (dead code), project_context → job_manager (единый источник прогресса)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** `_create_progress_callback`/`_last_progress` (src/core/progress_state.py) в проде не вызывались (внутренний callback layer.py маппит прогресс в `job.progress`, не в...
- **Статус:** автоматически синхронизировано


## 2026-08-05 22:50 — Следующий шаг: get_last_progress → core, фикс bump_version, фикс sys.path-загрязнения теста (FIXED, будет закоммичено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (не закоммичено — коммит следом)
**Root Cause:** (1) техдолг из ARCH-03-цепочки: `project_context` импортировал `get_last_progress` из mcp.server — направление core→mcp оставалось;...
- **Статус:** автоматически синхронизировано


## 2026-08-05 22:10 — experiments/audit.md: 16 пунктов верифицировано, 12 исправлено (FIXED, не запушено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (не закоммичено — по команде владельца)
**Root Cause:** audit.md накопил 4 наложенных аудита; свежий (ARCH/BL/WIN/ZED/SEC/TEST) содержал подтверждаемые проблемы: version drift (pyp...
- **Статус:** автоматически синхронизировано


## 2026-08-05 21:15 — Триаж KNOWN_ISSUES#2026-08-04-21:00 (Zed crash-loop) — цифры верифицированы замером

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Partial — loop остановлен (последний краш 08-04 21:27), риск сохраняется; дедлайн владельца 08-11
**Root Cause:** подтверждён: Zed commit 8.54GB при commit-лимите 18.5GB (свободно 1.14GB...
- **Статус:** автоматически синхронизировано


## 2026-08-05 — D1: schema-слой из Neuro-Symbolic спайка → CypherExecutor (архитектурное закрытие P-004, FIXED, не запушено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии; push — по команде владельца)
**Root Cause:** P-004 «разрыв валидации между слоями»: неизвестные label/rel (галлюцинация LLM: `MATCH (f:SERVICE)`) принимались...
- **Статус:** автоматически синхронизировано


## 2026-08-05 20:10 — C1-C4 Cypher-стек: 4 бага KNOWN_ISSUES#2026-08-05 (FIXED, не запушено)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии; push — по команде владельца)
**Root Cause:** C1 — label/edge сравнивались точно (=/IN) в cypher_sql.py, лексер принимает любой регистр LABEL → тихий пустой р...
- **Статус:** автоматически синхронизировано


## 2026-08-05 — A2 (внешний аудит): sandbox threat model — ADR-0001 ✅ Accepted (Вариант A)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (решение по умолчанию, §1.10 — владелец не выбрал B/C; переопределение возможно)
**Root Cause:** внешний аудит: blacklist-модель sandbox принципиально обходима (чистый Python без ОС...
- **Статус:** автоматически синхронизировано


## 2026-08-05 — A1 (внешний аудит): ThreadPoolExecutor max_workers=0 на 1-CPU (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** index_project_runner.py:261 `min(4, (os.cpu_count() or 4) // 2)` → на 1-CPU: `1//2 = 0` → `ThreadPoolExecutor(max_workers=0)` → ValueError; достижимо через intel_tr...
- **Статус:** автоматически синхронизировано


## 2026-08-05 01:50 — Tech debt: subprocess text=True без encoding ×7 закрыт + пин ruff (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (коммит в этой сессии)
**Root Cause:** text=True без encoding в 7 местах декодирует вывод через locale (cp1251/cp1252 на Windows) — UnicodeDecodeError при не-ASCII выводе (тот же кл...
- **Статус:** автоматически синхронизировано


## 2026-08-05 00:05 — CI красный: ruff I001 (10 импорт-блоков, НЕ coverage) (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит a7a7a9e7, запушен)
**Root Cause:** CI-прогоны b121ab19/6dc8d2ae упали на lint-шаге `ruff check src/ tests/` — 10 ошибок I001 (неотсортированные импорты) в 8 файлах: src/cor...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:59 — CI: кэш pip + coverage 41% (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** Next Action #9-#10: CircuitBreaker «dead» — ❌ REFUTED (подключён к embedder напрямую, di_container:337-345); coverage отсутствовал.
**Fix:** ...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:59 — Триаж bare-except: 4 рискованных silent-блока залогированы (PARTIAL)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 partial (коммит в этой сессии)
**Root Cause:** scan нашёл 106 silent-блоков (except → pass); большинство намеренные (CancelledError/таймауты/best-effort).
**Fix:** логирование в 4 местах...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:59 — Баг-клоуза: layer.py порт LM + резолв 7 VERIFY (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** из 3 аудитов остались VERIFY-пункты; единственный реальный баг — layer.py:504 хардкод порта LM Studio 1234 (рядом код уже читал порты из conf...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:58 — Hotfix: pickle P1 закрыт restricted unpickler'ом (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** index_guard.py:367 обычный pickle.load на legacy symbol_index.pkl — RCE-вектор (OWASP десериализация).
**Fix:** `_LegacyPickleLoader(pickle.U...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:55 — Полный аудит (3-й проход): метрики точны, P0-claims уже закрыты (TRIAGE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 триаж завершён (коммит в этой сессии)
**Root Cause:** третий аудит: SQL x6, subprocess «14 без timeout», мёртвый код, эксперименты. Проверено: SQL — ❌ (тот же безопасный IN-паттерн); gra...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:50 — Глубокий аудит (2-й проход): верификация 26 пунктов (TRIAGE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 триаж завершён, фиксы запланированы (коммит в этой сессии)
**Root Cause:** второй внешний аудит (async, subprocess, BLE001, coverage, порты). Проверено по коду: create_task fire-and-forg...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:30 — Триаж внешнего ревью: 165 находок, тесты зелёные (TRIAGE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 триаж завершён, фиксы запланированы (коммит в этой сессии)
**Root Cause:** внешний инструмент нашёл 165 проблем; критические проверены по коду: SQL_INJECTION (graph.py x4) — ❌ ложные (па...
- **Статус:** автоматически синхронизировано


## 2026-08-04 23:00 — CI clean-state: No module named pytest (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** Linux-ветка verify_clean_state.sh ставила `pip install -e ".[dev]" --no-deps` — dev-зависимости (pytest и др.) не входят в requirements-lock....
- **Статус:** автоматически синхронизировано


## 2026-08-04 22:30 — Приведение в порядок корня проекта (root cleanup)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (закоммичено в этой сессии)
**Root Cause:** в корне накопились одноразовые pytest-обёртки с hardcoded путями (runner.py, quickrun.py, do_test.py, execute_test.py, quick_test.py, _ru...
- **Статус:** автоматически синхронизировано


## 2026-08-04 22:25 — scripts/monitor.py: UnboundLocalError avg_log (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** переменная `avg_log` присваивалась только в ветке фаз эмбеддинга (PHASE_EMBED/WRITING/IVF), а читалась в блоке «Тренд» при любой фазе — при ф...
- **Статус:** автоматически синхронизировано


## 2026-08-04 22:40 — test_job_history: изоляция от переиспользования tmp_path (FIXED)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** JobHistoryStore пишет во внешний `<data_root>/projects/<hash>/metrics/job_history.json`, а pytest переиспользует temp-пути между запусками (с...
- **Статус:** автоматически синхронизировано


## 2026-08-04 — Спринт A: Item 3 (lazy asyncio.Lock) + Item 4 (progress cleanup)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код + 4 регрессионных теста; полный прогон 761 passed, 4 skipped, 94 deselected)
**Root Cause:** (Item 3) `asyncio.Lock()` создавался в sync `Searcher.__init__` — wrong-loop риск ...
- **Статус:** автоматически синхронизировано


## 2026-08-04 21:00 — ZED CRASH-LOOP: 7 рестартов за 2 часа — всплески памяти агента 7.5-8.6GB + дефицит системных ресурсов

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🟡 Root Cause подтверждён (лог+счётчики+EventLog+GitHub); фикс — действия владельца, код не менялся
**GitHub-подтверждение (2026-08-04 21:15):** `GitHub#60793` — точная копия кейса (Win11 +...
- **Статус:** автоматически синхронизировано


## 2026-08-04 — fast-mode сортировка инвертировала топ-результаты (cosine _distance ASC)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код + 1 регрессионный тест)
**Root Cause:** комментарий `engine.py:166` утверждал «негативная косинусная дистанция (чем больше, тем ближе)» — проверено экспериментом (lancedb 0.34...
- **Статус:** автоматически синхронизировано


## 2026-08-03 23:15 — P1 REOPEN: hub codebase write — dispatch терял sub-action (guard маскировал баг)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код + 15 новых тестов, ext синхронизирован; live-проверка после Reload Window)
**Root Cause:** фикс 22:45 перевёл `_action_write` на WriteTool, но передавал `action="write"` (под-...
- **Статус:** автоматически синхронизировано


## 2026-08-03 23:20 — ONNX embedder: 2× off-by-one пути — тихий fallback на llama.cpp (5+ падений/день)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код, ext синхронизирован; live через продакшн-путь get_onnx_client)
**Root Cause:** (1) `onnx_client.py` PROJECT_ROOT = parent×3 из src/core/embedder/ → `…/src` (не корень) → «Ser...
- **Статус:** автоматически синхронизировано


## 2026-08-03 23:45 — E2E-проверка MCP-цепочки + Contradiction Ledger 21/21 + Py3.14 audit

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (live RUN_ID e3f3aabd7186) + ✅ Fixed (verify_diary 3 бага, error_handler 1 латентный)
**Root Cause (2 независимых):** (1) verify_diary.py — 3 ложных ❌ при каждом старте: regex л...
- **Статус:** автоматически синхронизировано


## 2026-08-03 22:30 — Слияние DEV_DIARY.md → AGENT_DIARY.md завершено (§4.7)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Closed
**Root Cause:** исторически два параллельных дневника; заголовок «ARCHIVED» в DEV_DIARY (от 07-19) не соответствовал факту — 27 из 28 записей (07-17..07-19) так и не были перенесе...
- **Статус:** автоматически синхронизировано


## 2026-08-03 21:55 — search_code quality/deep/auto зависали на 30с: sync-поиск блокировал main loop и отравлял _sync_executor

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, синхронизировано в расширение; live-проверка после Reload Window)
**Root Cause:** search_code (async) вызывал sync `search_with_mode` прямо в main loop → `hybrid_search...
- **Статус:** автоматически синхронизировано


## 2026-08-03 21:50 — Ложное «Обнаружен второй экземпляр MCP» на собственном lock-е (startup_diagnostics)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, синхронизировано в расширение; live-подтверждено на новом инстансе 21:32)
**Root Cause:** inspect_pid_lock не знал собственный PID: lock, который живой MCP держит всю с...
- **Статус:** автоматически синхронизировано


## 2026-08-03 20:50 — Stale ghost table после fresh-path reset: switch_db не синхронизировал ссылки

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, не запушено; синхронизировано в расширение)
**Symptom:** после intel_reset_index (live MCP, 5ce0eaa3) реиндекс «завершился», но search_code остался в grep-fallback: fre...
- **Статус:** автоматически синхронизировано


## 2026-08-03 20:40 — search_code рендерил «📄 — (line , —)»: корень в db-level manifest, а не в рендере

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, не запушено; синхронизировано в расширение)
**Symptom:** `search_code(mode=fast)` возвращал `1 results` с пустым рендером `📄 **—** (line , —)` вместо файла/строки/кода....
- **Статус:** автоматически синхронизировано


## 2026-08-03 20:15 — Верификация Задачи 5/5 после полного реиндекса + дедуп callers

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Verified (реальный reindex + граф-проверка)
**Root Cause (косметический дефект, найден при верификации):** find_references собирает incoming CALLS по каждому найденному узлу — интерфейс ...
- **Статус:** автоматически синхронизировано


## 2026-08-03 — Задача 5/5: Граф в каждом режиме поиска (INC: CALLS в методы = 0)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, не запушено; синхронизировано в расширение)
**Root Cause:** (1) `_extract_calls_recursive` эмитил caller без класса → `add_edge` молча дропал рёбра в методы (0 CALLS в ...
- **Статус:** автоматически синхронизировано


## 2026-08-03 02:10 — Задача 4/5: Артефакты вынесены из проекта в системную папку

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, не запушено; синхронизировано в расширение)
**Root Cause:** MCP писал индексы/граф/память/телеметрию ВНУТРЬ пользовательского проекта (.codebase_indices/, .codebase/gra...
- **Статус:** автоматически синхронизировано


## 2026-08-03 01:10 — Задача 3/5: Startup Diagnostics + P0-фикс INC-6471 (GetExitCodeProcess)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, локально не запушено; синхронизировано в расширение)
**Root Cause:** (1) При старте/сбое пользователь видел Rust-трейс (`lance-io-8.0.0\src\local.rs`) вместо человеческ...
- **Статус:** автоматически синхронизировано


## 2026-08-03 00:20 — Задача 2/5: DatabaseGateway — PID-lock вынесен в DatabaseLock (модуль + тесты)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (локально, не запушено)
**Root Cause:** PID-lock (Layer 3 defense) был приватным 140-строчным методом LanceDBManager (_acquire_pid_lock) — не тестируем, не переиспользуем; wait_tim...
- **Статус:** автоматически синхронизировано


## 2026-08-02 23:55 — Задача 2/5: чистка мёртвого кода DI + файлы-адаптеры

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (локально, не запушено)
**Root Cause:** 5 DI-регистраций (DbPathKey, FileGuard-singleton, SymbolIndex, ResourceMonitorKey, ResourceMonitor-в-DI) никогда не резолвились; composition...
- **Статус:** автоматически синхронизировано


## 2026-08-02 23:30 — Исследование перед Задачей 2/5 (DatabaseGateway): 4 вопроса владельца закрыты фактами

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Исследование завершено (read-only; правок кода нет)
**Root Cause (вопроса):** владелец описал архитектуру Gateway по памяти — требовалась проверка «что переписывать, что не сломать» до к...
- **Статус:** автоматически синхронизировано


## 2026-08-02 23:10 — INC-6E12: FileGuard в write_tools — fail-open → fail-closed (задача 1/5 «идеального кода»)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (локально, не запушено; runtime — живой MCP работает с синхронизированным файлом)
**Root Cause:** `_validate_file_in_project` (write_tools.py:93) возвращал None при недоступности i...
- **Статус:** автоматически синхронизировано


## 2026-08-02 22:50 — INC-6C62 «вечная ошибка» реиндекса: физическое пересоздание таблицы LanceDB

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код+тесты, локально не запушено; runtime-проверка требует Reload Window)
**Root Cause:** drop_table+create_table в LanceDB НЕ удаляет физические файлы, залоченные mmap живого проц...
- **Статус:** автоматически синхронизировано


## 2026-08-02 00:26 — Реиндекс падает: lance 'Not found' (3 подряд) + 2 MCP-процесса + stale table refs

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** 🔴 Open — требуется действие владельца
**Root Cause:** (1) 2 MCP-процесса на одной БД с 23:47:00 (PID 4576 активный + PID 21616 зомби, 156ms CPU, завис при старте) — rmtree/drop блокируются...
- **Статус:** автоматически синхронизировано


## 2026-08-01 23:55 — Contradiction Ledger: флапающий check_commit_exists + push v3.3.11 + верификация чанков

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** verify_diary.py check_commit_exists — git cat-file с timeout=5s; при старте MCP (auto-index, embedder, reranker 499MB, Defender scan) git не укладывался в 5s → Time...
- **Статус:** автоматически синхронизировано


## 2026-08-01 — Pre-commit hook: verify_diary cp1251-краш + SyntaxError в шаблоне git_hooks_installer

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (локально, не запушено)
**Root Cause:** (1) verify_diary.py требовал `## [YYYY-MM-DD HH:MM]` в заголовке, а записи 31.07 имели только дату → не матчились и склеивались с предыдущей...
- **Статус:** автоматически синхронизировано


## 2026-08-01 22:50 — HTTP 400 llama.cpp embedder: v1 (HF truncation) ОПРОВЕРГНУТ → v2 (native /tokenize) + полный реиндекс 4677 чанков

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (v3.3.11, локально, не запушено)
**Root Cause:** GGUF multilingual-e5-small: n_ctx_train=512 → llama.cpp капит слот до 512. HF-токенизатор ≠ GGUF-токенизатор (разные BPE): после ус...
- **Статус:** автоматически синхронизировано


## 2026-08-03 22:45 — Ротация дневника §4.8 (июль → docs/archive/AGENT_DIARY_2026_07.md)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done
**Root Cause:** дневник 861 строка (> лимит 300) — перегрузка контекста.
**Fix:** все записи < 2026-08-01 перенесены в docs/archive/AGENT_DIARY_2026_07.md (заголовок ARCHIVE — см. A...
- **Статус:** автоматически синхронизировано


## 2026-08-03 22:45 — P1: hub codebase — каналы write/index падали ImportError'ом

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed
**Root Cause:** codebase_tool.py импортировал несуществующие модули: `symbol_write_tools.SymbolWriteTool` (реальный: `write_tools.WriteTool`) и `index_tools.IndexTool` (такого файл...
- **Статус:** автоматически синхронизировано


## 2026-08-03 23:55 — Сессия: §1.19 Hard Triggers + аудит 29 пунктов + docs sync + commit/push

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done
**Root Cause:** протокол требовал жёстких триггеров (§1.19), аудит audit.md был неразмечен, README/doc badges устарели (649→747), DEV_DIARY не архивирован, CHANGELOG пуст, unpushed ...
- **Статус:** автоматически синхронизировано


## 2026-08-04 — Спринт: 6 пунктов аудита (5 ✅ Fixed, 1 ❌ Refuted) + docs + commit/push

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Done (5/6 FIXED, 1/6 REFUTED)
**Root Cause:** 6 ❌ P1/P2 пунктов из experiments/audit.md требовали фикса: Heartbeat GetLastError, hardcoded reranker weights, BM25 sync reindex, SQLite sch...
- **Статус:** автоматически синхронизировано


## 2026-08-24 — Live Sync: editor RAM → демон (all-IDE, out-of-the-box)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Feature
**Root Cause:** FS-watcher бесполезен — IDE держит изменения в RAM до save; текущий `notify_change` VFS-путь мёртв (`src.hybrid_server` удалён 2026-07-20).
**Fix:** новый пакет `...
- **Статус:** автоматически синхронизировано


## 2026-08-26 19:55 — Multi-window: search_code/graph_query/intel_get_project_memory игнорируют project_root (set_project vs CWD-привязка)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (scope: 🅳+🅲+🅵+🅰+🅱; 🅴 подтверждён в коде)
**Root Cause:** search_tools.py вызывал `resolve_searcher()` без explicit project_root; graph_query и intel_get_project_memory не принимали...
- **Статус:** автоматически синхронизировано


## 2026-08-27 21:30 — MCP freeze during full reindex = logging deadlock (не CPU/не crash)

- **Источник:** AGENT_DIARY.md
- **Описание:** **verified_from_clean_state:** ✅ live — full reindex  embed-phase без заморозки сервера (QueueHandler/QueueListener); py_compile чист; pytest 1553 passed. Reindex доведён restart-ом (отдельный pre-exi...
- **Статус:** автоматически синхронизировано


## 2026-08-27 21:30 — off-by-one: индекс/граф хранят 0-based строки (340 вместо 341)

- **Источник:** AGENT_DIARY.md
- **Описание:** **verified_from_clean_state:** ✅ live — LanceDB после реиндекса+рестарта: save_symbol_index start_line=341, _ensure_symbol_index=332; runtime-status 🟢 9191 chunks; check_index.py подтвердил; pytest 15...
- **Статус:** автоматически синхронизировано


## 2026-08-28 19:50 — Port extract_env_accesses from codebase-memory-mcp (MIT)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (код синк в расширение; 22 new tests pass; full suite 1582 passed, 0 regression)
**Root Cause:** В PropertyGraph не было узлов для env-переменных → запросы "какие env читает функци...
- **Статус:** автоматически синхронизировано

