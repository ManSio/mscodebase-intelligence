## Key Historical Decisions

- **Embedder:** multilingual-e5-small-int8 + batch=32 (100 ch/s sustained) — 2026-07-17
- **Concurrency:** AsyncInferQueue → лок (тихая гонка подмены векторов) — 2026-07-18
- **Cache:** Chunk-level content-addressed cache (skip re-embedding) — 2026-07-18
- **Windows:** subprocess.run(capture_output) в daemon-тредах = deadlock; Popen+communicate (§5.16) — 2026-07-18
- **Артефакты:** progress.json вне проекта, системная папка (Задача 4/5) — 2026-08-03
- **Hub & Spoke:** codebase(action) + DEFAULT-allowlist MSCODEBASE_MCP_TOOLS (скрытые инструменты — через hub) — 2026-07-22
- **Защита:** PID-lock + self-healing + auto-index guard (3-layer defense) — 2026-08-02
- **Security:** SQL injection fixes (alias/layer), FileGuard fail-open → fail-closed в write_tools — 2026-07-27/08-02
- **P0 reindex deadlock:** bulk-загрузка known_hashes вне RLock между потоками — 2026-07-31

---

## [2026-08-06 22:05] — Протокол: Триггеры 6-7 (§1.19), оживлён §6.4, создан WISDOM.md (DONE)

**Status:** ✅ Done — правки в глобальном `AGENTS.md` (профиль Zed, вне репозитория) + проектном AGENTS.md; WISDOM.md создан
**Root Cause:** три дыры замыкания петель: (1) §6.4 Ledger-проверка «раз в сессию/по команде» — мёртвое правило, мёртвый код сессии 2026-08-05 (0/17 SCM) дожил до 2026-08-06; (2) урок «короткий edit-якорь ест заголовок» повторился 3×, но пополнение §9 ждало команды; (3) 4 урока (elixir макро-шум, matlab .m конфликт, language-pack вопреки #174, python 0.25 без async_function_definition) утонули в дневнике.
**Fix:** Триггер 6 (LEDGER-ПРОВЕРКА — блокиратор первого действия: grep ✅ за 14 дней, артефакт обязателен, иначе P1); Триггер 7 (ПАМЯТЬ БЕЗ СПРОСА — блокиратор [🏁 ИТОГ]: запись в §9 + guard в том же коммите, edit-safety guard для markdown); §6.4 переписан под Триггер 6; §0.1 п.2 — блокирующее обновление task state («запрещено переходить к следующему шагу, пока предыдущий не отражён») + финальная синхронизация перед [🏁 ИТОГ]; §7 п.10 — DoD «task state актуален или удалён» (закрывает дыру «Next Action устарел»); WISDOM.md ≤50 строк с 4 семенами; проектный AGENTS.md §0.6 + FIRST STEP загружают WISDOM.md всегда.
**Guard:** §1.19 Триггеры 6-7 (самоисполняющиеся); WISDOM.md — строки без использования 30+ дней удалять/архивировать.
**Pattern:** P-002 «предположение вместо проверки» — корень дыры №1; fix = механический Триггер 6, а не доверие.

---

## [2026-08-06 21:10] — Workstreams A+B+C по отбору audit.md: SCM wiring, language-pack (+54), Leiden (DONE)

**Status:** ✅ Done — 853 passed / 4 skipped (baseline 831); ruff чист; коммиты: (A) SCM wiring, (B) language-pack, (C) Leiden
**Root Cause:** (A) вендоренные 17 tags.scm НЕ компилировались с установленными грамматиками (0/17 — async_function_definition не существует в tree-sitter-python 0.25); extract_definitions_scm вызывался только из scripts/patch_parser.py; формат SCM-символов несовместим с walk (simple name, 1-based, capture-kind). (C) leidenalg GPL-3.0 + igraph GPL-2.0 ≠ MIT. (B) issue #174 «нет windows-бандла» мог блокировать язык-pack.
**Fix:** (A) переписаны 17 tags.scm под установленные грамматики (name: (_) @name, positional где нет полей) + extract_definitions_scm: qualified names через контейнерные предки, 0-based line, kind=node.type, whitelist kinds, @name-спаривание через ancestor-walk, фильтр валидных имён; parse_file: SCM-first с fallback на walk; _parse_with_tree_sitter через _get_tree (без двойного парсинга); label_map расширен (class/struct/enum/interface/type/property). SCM теперь ⊇ walk (классы, async, struct, enum). (C) [community] extra + src/core/community_detection.py (CPM Leiden, лимиты OOM) + MCP tool detect_communities (49 tools всего). (B) [language-pack] extra + гейт MSCODEBASE_LANGUAGE_PACK (off) + src/core/language_pack.py (54 языка, tags queries, DYNAMIC_EXTENSIONS→FileGuard); elixir/matlab исключены (макро-шум/.m конфликт). Эксперимент: per-language download на Windows работает (Exp 6).
**Guard:** tests/test_scm_definitions.py (11: format parity, superset, fallback, compile-guard на бампы грамматик), test_community_detection.py (5), test_language_pack.py (6); README 48→49 (20 core); .env.example += MSCODEBASE_LANGUAGE_PACK.
**Pattern:** P-002 «предположение вместо проверки» — прошлая сессия закоммитила нерабочие queries без compile-теста; guard = compile-guard теперь обязателен.
**verified_from_clean_state:** ⚠️ не проверено — clean-clone не запускался (нет repo URL/сети); полный pytest 853 passed запущен явно.

---

## [2026-08-06 19:45] — Live-верификация 5 быстрых побед audit.md: 4/5 ✅, SCM-определения частично (wiring НЕ подключён), packaging-фикс

**Status:** 🟡 Partial — packaging закрыт (коммит f14435db), wiring SCM ждёт решения владельца
**Root Cause:** «SCM-определения» реализованы на 70%: 17 tags.scm + `extract_definitions_scm`/`_load_tags_query` есть, но прод-путь `parse_file` (parser.py:297) использует TARGET_NODES walk — `extract_definitions_scm` вызывается только из `scripts/patch_parser.py` (наивный патч не применён: ломает .md, callees, двойной парсинг и qualified names «Class.method» → регресс CALLS/DECORATES/OVERRIDES).
**Fix:** queries/__init__.py + `*.scm` в pyproject.toml/MANIFEST.in (wheel больше не теряет queries); `install.py --sync-only` → расширение синхронизировано (grep-подтверждены все 5 побед в копии расширения); полный pytest 831 passed / 4 skipped / 94 deselected (0 failed).
**Guard:** .agent_task_state.md «Decision 2026-08-06» (варианты A/B wiring); проверка вызовов (grep callers) перед заявлением «✅ реализовано».
**Pattern:** P-002 «предположение вместо проверки» — победа помечена ✅ без проверки прод-пути.
**verified_from_clean_state:** ⚠️ не проверено — clean-clone не запускался (нет repo URL/сети); полный pytest 831 passed запущен явно; install --sync-only применён, ожидается Reload Window.

---

## [2026-08-05 23:30] — Реальный отбор audit.md: 16 предложений сверено с кодом + 5 экспериментов (DONE)

**Status:** ✅ Done (документация; код не менялся — Danger Zone соблюдён)
**Root Cause:** audit.md содержал 16 предложений «внедрить», из которых 6 УЖЕ реализованы (Cypher-стек, 27/29 EdgeType, change coupling, dead code, depth-группировка impact) и 2 опровергнуты (scip-python и cypher-sqlite не существуют на PyPI; «371 язык» = 71 с tags.scm).
**Fix:** 5 реальных экспериментов (EXPERIMENTS_LOG#2026-08-05): (1) language-pack: манифест 371, tags.scm у 71 (19%), первый парс 37.6s/0.03ms повторно; (2) tags.scm recall 100% (66/66) vs CodeParser 60/65ms — паритет; (3) Cypher 0.3–13ms direct / 7–13ms live MCP на 6856 узлов / 19969 рёбер — «4297ms» опровергнуто; (4) DECORATES/OVERRIDES извлекаемы (decorated_definition в AST); (5) PyPI: scip-python/cypher-sqlite 404, leidenalg/igraph доступны. Итоговый отбор: делать next_step-hints, DECORATES, OVERRIDES, confidence в impact, language-pack как опциональный слой (+62 tags-языка); не делать SCIP/KuzuDB/tsg-DSL/GitHub-Artifacts.
**Guard:** секция верификации в experiments/audit.md (матрица 16 строк); EXPERIMENTS_LOG.md 5 записей + таблица отрицательных результатов §3.8.
**Pattern:** P-002 «предположение вместо проверки» — аудит планировал внедрение того, что уже существует; guard = Phase Zero сверки перед планированием.
**verified_from_clean_state:** N/A — docs-only (код не менялся); замеры выполнены реальным исполнением в этой сессии.

---

## [2026-08-05 22:15] — AutoDocUpdater коррумпировал README: 4 бага в _update_readme/_count_* (FIXED)

**Status:** ✅ Fixed
**Root Cause:** (1) `_count_tools`: `text.count()` на regex-строке как на литерале (`@mcp\.tool\("` со слешами) + скан только server_tools.py → всегда 0; (2) `_count_tests`: `count("def test_") + count("async def test_")` — двойной счёт async (1016 вместо 890); (3) замена тестов `\d+\s*passed` ловила '20passed' внутри URL-бейджа `tests-747%20passed` → `747%1016 passed`; (4) `_replace_between(marker)` с cross-line `[^\d]*?` попадал на якорь навигации вместо заголовка и, для «language», перепрыгивал таблицу языков и заменял «13 high-level intel_* tools» → «0 …».
**Fix:** `_count_tools` зеркалит runtime-константы (19 core из списка tool_classes + 12 inline + 13 intel из tools_reg.py + 4 dev + ExecuteScriptTool по env = 48); `_count_tests` — line-anchored regex `^(?:async )?def test_`; замены в `_update_readme` точечные: бейдж `tests-N%20passed`, заголовок `MCP Tools (N total)` + якорь `mcp-tools-N-total` синхронно; `_count_languages`/`_replace_between` удалены (не имели корректной цели). Тесты: tests/test_auto_doc_updater.py (6 новых, включая регрессию на коррупцию).
**Guard:** регрессионные тесты (fixture README + фейковые src/tests); полный pytest 802 passed / 4 skipped; README пересобран корректно (бейдж 747→890, 48 не тронут).
**Pattern:** P-002-класс «regex-паттерн используется как литерал» (`text.count(regex)` вместо `re.findall`) — guard: fixture-тест на реальный счёт (48) и на отсутствие коррупции.
**verified_from_clean_state:** ⚠️ не проверено — clean-clone не запускался (нет repo URL/сети); полный pytest 802 passed запущен явно.

---

## [2026-08-05 21:56] — Открытая нить закрыта: progress_state удалён (dead code), project_context → job_manager (единый источник прогресса)

**Status:** ✅ Fixed
**Root Cause:** `_create_progress_callback`/`_last_progress` (src/core/progress_state.py) в проде не вызывались (внутренний callback layer.py маппит прогресс в `job.progress`, не в `_last_progress`) → get_last_progress() всегда пуст → `ProjectContext._capture_jobs` вечно 0/0. `JobManager.cleanup_old_jobs()` определён, но не вызывался нигде (латентный рост `jobs`).
**Fix:** механизм удалён целиком: progress_state.py (92 строки) + 6 реэкспортов в mcp/server.py + 11 легаси-тестов; `_capture_jobs` переключен на `job_manager.list_jobs()` (новый метод с ленивым cleanup — cleanup_old_jobs теперь реально работает); в снэпшот добавлен честный счётчик `jobs_failed`; исторические комментарии (architecture_linter, test_architecture_lifecycle) обновлены.
**Guard:** tests/test_index_progress.py переписан (9 тестов: JobManager lifecycle/list/cleanup + _capture_jobs mapping running/completed/failed); полный pytest 796 passed / 4 skipped (0 failed); grep `progress_state|_create_progress_callback|_last_progress` — 0 ссылок в src/tests (только обновлённые комментарии).
**Pattern:** NEW-класс «диагностический accessor без проверки прод-использования» — механизм держался 1 версию «для диагностики», никто не проверил, что он мёртв. Guard: открытая нить закрыта явно, по плану владельца.
**verified_from_clean_state:** ⚠️ не проверено — clean-clone не запускался (нет repo URL/сети); полный pytest 796 passed запущен явно. Runtime (после install+reload): ✅ MCP PID 12076, BUILD_ID=HEAD; live-проверка — intel_trigger_reindex (инкрементальный job) → intel_get_project_context().jobs = {running:0, completed:1, failed:0} (до фикса было вечно 0/0).

---

## [2026-08-05 22:50] — Следующий шаг: get_last_progress → core, фикс bump_version, фикс sys.path-загрязнения теста (FIXED, будет закоммичено)

**Status:** ✅ Fixed (не закоммичено — коммит следом)
**Root Cause:** (1) техдолг из ARCH-03-цепочки: `project_context` импортировал `get_last_progress` из mcp.server — направление core→mcp оставалось; (2) `version_manager.check_consistency` ловил ВСЕ `X.Y.Z` (версии зависимостей, старых записей) как дрифты; `scripts/bump_version.py` вставлял заголовок после первого `---`, для ru/zh он попадал в середину файла; (3) `test_architecture_lifecycle` на уровне модуля делал `sys.path.insert(0, extension_dir)` — вся pytest-сессия импортировала УСТАРЕВШУЮ копию src из установленного расширения → ModuleNotFoundError для новых core-модулей (вскрыто переносом progress_state).
**Fix:** (1) новый `src/core/progress_state.py` (состояние+callback+cleanup), mcp.server реэкспортирует, project_context импортирует из core, исключения в architecture_linter убраны; (2) per-file версионные паттерны в check_consistency, вставка ПЕРЕД первым `## [X.Y.Z]` в обоих bump (scripts + version_manager), version_manager обновляет все три CHANGELOG; (3) sys.path/env-загрязнение перенесено в autouse-fixture с восстановлением (намерение теста «установленное расширение» сохранено).
**Guard:** tests/test_version_manager.py (4 регрессионных: ложные дрифты, реальный дрифт, вставка заголовка, три CHANGELOG); полный pytest 799 passed / 4 skipped (0 failed); вскрытая аномалия: `_create_progress_callback` в проде не вызывается → get_last_progress() всегда пуст — открытая нить.
**Pattern:** P-002 «предположение вместо проверки» (симптом: «тесты флейкят» → реальная причина: глобальное загрязнение sys.path чужим тестом).
**verified_from_clean_state:** ⚠️ не проверено — clean-clone скрипт не запускался (нет repo URL/сети); полный pytest 799 passed запущен явно, 2 раза подряд (стабильно).

---

## [2026-08-05 22:10] — experiments/audit.md: 16 пунктов верифицировано, 12 исправлено (FIXED, не запушено)

**Status:** ✅ Fixed (не закоммичено — по команде владельца)
**Root Cause:** audit.md накопил 4 наложенных аудита; свежий (ARCH/BL/WIN/ZED/SEC/TEST) содержал подтверждаемые проблемы: version drift (pyproject 3.3.11 vs extension.toml 3.3.9 vs __init__ 3.2.3 — три версии!), hardcoded start_server.bat, subprocess decode/encoding debt, read_live_file без cp1251, ONNX providers без env override, stderr-лог в корне проекта, absolute_path без guard, rename в PropertyGraph без rollback, resolve() под threading.Lock, core→mcp import (resolve_project_root, дедлайн v2.5 просрочен).
**Fix:** (1) версии синхронизированы к 3.3.11 + tests/test_versions.py (TEST-01); (2) start_server.bat portable (%~dp0, errorlevel, PYTHONUTF8, venv check); (3) encoding utf-8+replace: llama_runner:1278, llama_install ×3, install.py ×2, onnx_client HTTP/taskkill; (4) cp1251 fallback в read_live_file (WIN-03) + MSCODEBASE_RESTRICTED_READ guard для absolute_path (SEC-05) + tests/test_read_live_file.py (TEST-04); (5) select_onnx_providers (WIN-11, MSCODEBASE_ONNX_PROVIDER) + tests/test_onnx_providers.py (TEST-03); (6) onnx stderr → <data_root>/logs (WIN-12); (7) extension.toml += PYTHONUTF8 (ZED-03); (8) rename_symbol rollback (BL-05); (9) RLock в ServiceCollection.resolve (ARCH-02); (10) resolve_project_root → src/core/project_resolution.py (ARCH-03, mcp.server реэкспорт для тестов); (11) install.bat errorlevel после cd (WIN-16); (12) docs/en+ru+zh ARCHITECTURE.md: убраны устаревшие lsp_main (контрадикция §4.9); .env.example += MSCODEBASE_ONNX_PROVIDER/MSCODEBASE_RESTRICTED_READ.
**Guard:** тесты 16 новых + полный pytest 801 passed / 4 skipped; diagnostics чисто; architecture_linter: runtime_coordinator больше не нарушает core→mcp (9 остальных нарушений — существовавшие).
**Pattern:** P-002 «предположение вместо проверки» — 3 пункта старого аудита опровергнуты (файлы src/di_container.py, src/process_manager.py, src/lsp_main.py не существуют; encoding частично уже исправлен).
**verified_from_clean_state:** ⚠️ не проверено — clean-clone скрипт (scripts/verify_clean_state.sh) не запускался: требует repo URL и сеть; полный pytest 801 passed запущен явно в этой сессии (pre-commit = verify_diary+stale_detector).
**Temporal:** T+0 OK | T+30d: версии снова разъедутся без CI-гейта — tests/test_versions.py теперь ловит на прогоне; MSCODEBASE_RESTRICTED_READ/ONNX_PROVIDER задокументированы в .env.example | T+180d: project_resolution.py — точка входа для переноса get_last_progress (техдолг, KNOWN_ISSUES#2026-08-05).

---

## [2026-08-05 21:15] — Триаж KNOWN_ISSUES#2026-08-04-21:00 (Zed crash-loop) — цифры верифицированы замером

**Status:** 🟡 Partial — loop остановлен (последний краш 08-04 21:27), риск сохраняется; дедлайн владельца 08-11
**Root Cause:** подтверждён: Zed commit 8.54GB при commit-лимите 18.5GB (свободно 1.14GB = 93.8%); C: 92.4% (9.75GB free); pagefile 3.2GB; рендер на AMD iGPU (GitHub#40465 не применён); threads.db 79.7MB растёт (GitHub#59442 upstream).
**Fix (частично применён 08-04 22:04, settings.json):** auto_compact=90%, edit_predictions=false, 1 context-server → краши прекратились: 13 рестартов 08-04 (18:39-22:20) → 0 WER-крашей 08-05, 1 чистый старт 19:12, стабилен 2ч+.
**Guard:** KNOWN_ISSUES#2026-08-04-21:00 обновлён верифицированными числами; владельцу до 08-11: C: <85% (~9.6GB), pagefile ≥8GB или D:, решение по gpu_acceleration:false, AGENTS.md 126KB→15-20KB.
**Pattern:** P-002 «гипотеза без замера» (цифры записи от 08-04 не проверялись) — здесь закрыто исполняемой проверкой (§0.2).

## [2026-08-05] — D1: schema-слой из Neuro-Symbolic спайка → CypherExecutor (архитектурное закрытие P-004, FIXED, не запушено)

**Status:** ✅ Fixed (коммит в этой сессии; push — по команде владельца)
**Root Cause:** P-004 «разрыв валидации между слоями»: неизвестные label/rel (галлюцинация LLM: `MATCH (f:SERVICE)`) принимались парсером и тихо давали `[]` без объяснения; источник схемы был захардкожен в спайке (5 меток, 3 rel) и расходился с реальной схемой (15 меток, 27 rel).
**Fix:** новый `src/core/search/cypher_schema.py` — `schema_check` (имена меток/rels из `NodeLabel`/`EdgeType` graph.py как single source of truth, case-insensitive upper()); внедрён в `CypherExecutor.execute` после parse, до translate (cypher_executor.py:62-74) → понятная ошибка `schema: unknown label :SERVICE` вместо тихого `[]`. OPTIONAL MATCH намеренно пропускается (NULL-семантика, тесты NONEXISTENT). WHERE-label-tests валидируются. Свойства узла `{prop}`: парсер на них падает (SyntaxError), schema-проверка — defensive-слой.
**Guard:** 9 регрессионных тестов (Phase 7 TestSchemaValidation): unknown label/rel → error, Method/function case-insensitive → ок, OPTIONAL NONEXISTENT → NULL не error, WHERE label-test, node properties → error. Полный pytest 785 passed / 0 failed.
**Pattern:** P-004 → закрыт архитектурно (валидация перенесена в постоянный слой executor'а, а не точечные фиксы).
**Обобщение (§3.5):** `node.properties` в паттерне игнорируются SQL-генератором (grep — 0 использований); парсер падает раньше (SyntaxError) — тихий неверный результат сейчас невозможен; defensive-слой на будущее. Аналогов «принято-но-не-исполнено» в Cypher-стеке не найдено.
**verified_from_clean_state:** ⚠️ полный pytest 785 passed запущен явно в этой сессии (pre-commit = только verify_diary+stale_detector); 45 ✅ / 0 ❌ verify_diary.
**Temporal:** T+0 OK | T+30d: добавление метки в NodeLabel автоматически расширяет валидацию (источник правды); риск — пользователь с сознательным «пустым» запросом на неизвестную метку получит ошибку вместо `[]` (задокументировано) | T+180d: при поддержке node-properties в SQL-генераторе schema-слой переиспользуется без изменений.

## [2026-08-05 20:10] — C1-C4 Cypher-стек: 4 бага KNOWN_ISSUES#2026-08-05 (FIXED, не запушено)

**Status:** ✅ Fixed (коммит в этой сессии; push — по команде владельца)
**Root Cause:** C1 — label/edge сравнивались точно (=/IN) в cypher_sql.py, лексер принимает любой регистр LABEL → тихий пустой результат; C2 — пустой count-вызов ронял parser (IndexError), агрегат над узлом генерил `COUNT(n.*)` → SQLite near "*"; C3 — `except SyntaxError` молчал; C4 — expect() пропускал любую пунктуацию → cycle(a, b) терял аргумент, неизвестные RETURN-функции давали невалидный SQL.
**Fix:** C1 — COLLATE NOCASE в 9 местах (label+edge); C2 — count без аргумента → `COUNT(*)`, count(узел) → `COUNT(узел.id)` (точная семантика Cypher), агрегаты над узлом → ValueError; C3 — logger.warning «Cypher syntax error» + query[:200]; C4 — строгий expect() по значению + ValueError для неизвестных функций; бонус — `<-` больше не затирается правой стрелкой (легаси-баг направления, вскрыт expect).
**Guard:** 10 регрессионных тестов (регистр labels, count-семантика, caplog-лог, unsupported function); Cypher 61 + graph-смежные 48 passed; полный pytest — pre-commit при коммите.
**Pattern:** NEW — P-004 «разрыв валидации между слоями: принято лексером/parser'ом, исполнено SQL неверно и тихо».
**Обобщение (§3.5):** остальные label/edge-сравнения вне Cypher-стека (graph.py) — нативные enum-ключи, регистр не применим; аналогов рассинхрона не найдено.
**verified_from_clean_state:** ⚠️ полный pytest пройдёт через pre-commit при коммите (Cypher 61 + graph-смежные 48 уже зелёные; 3 failed в ходе фиксов — все исправлены).

## [2026-08-05] — A2 (внешний аудит): sandbox threat model — ADR-0001 ✅ Accepted (Вариант A)

**Status:** ✅ Done (решение по умолчанию, §1.10 — владелец не выбрал B/C; переопределение возможно)
**Root Cause:** внешний аудит: blacklist-модель sandbox принципиально обходима (чистый Python без ОС-изоляции); вопрос — для какого класса ввода defense-in-depth достаточна.
**Fix:** docs/adr/0001-sandbox-threat-model.md — первый ADR в репо (папка docs/adr/ создана). Границы зафиксированы: executor — для доверенных сниппетов агента внутри доверенного MCP-процесса, не для внешнего/пользовательского кода. Вариант A (defense-in-depth = статус-кво) принят; код НЕ менялся (Danger Zone). B (OS-изоляция, 2-4 нед) / C (гибрид) — отдельная фича при появлении недоверенного ввода.
**Guard:** ADR-0001 ✅ Accepted + KNOWN_ISSUES-запись; триггер переоткрытия: новый недоверенный источник ввода; кандидат (не блокер): сузить ast.Delete до global/attr.
**Pattern:** NEW (первый ADR в репозитории)
**verified_from_clean_state:** docs-only — код не менялся, полный pytest не требуется (761 passed на соседних коммитах).

## [2026-08-05] — A1 (внешний аудит): ThreadPoolExecutor max_workers=0 на 1-CPU (FIXED)

**Status:** ✅ Fixed
**Root Cause:** index_project_runner.py:261 `min(4, (os.cpu_count() or 4) // 2)` → на 1-CPU: `1//2 = 0` → `ThreadPoolExecutor(max_workers=0)` → ValueError; достижимо через intel_trigger_reindex mode=full (Indexer.index_project → IndexProjectRunner.run).
**Fix:** `max(1, min(4, (os.cpu_count() or 4) // 2))` + регрессионный тест test_run_survives_single_cpu_host (валидирован: без фикса — ровно ValueError, stash-прогон).
**Guard:** тест; безопасный паттерн уже был в resource_monitor.py:133.
**Pattern:** NEW (P-003 — отсутствие нижней границы воркеров при делении числа ядер пополам).
**Обобщение (§3.5):** grep по src/ — cpu_count: 4 места (runner:261 FIXED; resource_monitor:133 `max(1, ...)` SAFE; llama_install:95/810 — конфиг-значение cores, не делитель SAFE). ThreadPoolExecutor: 7 мест, все max_workers фиксированы ≥1 или защищены (error_handler:58=4; runner:502=1; health:49=1; agentic_search:551=1; engine:48=2; task_queue:78 default=2, единственный инстанциатор =2). ProcessPoolExecutor/multiprocessing как экзекуторы — 0. Аналогов уязвимого паттерна `min(N, cpu//2)` без `max(1, ...)`: **0** — P-003 закрыт как единичный экземпляр.
**verified_from_clean_state:** ✅ да — полный pytest 762 passed, ruff clean; CI-прогон после push подтвердит.

## [2026-08-05 01:50] — Tech debt: subprocess text=True без encoding ×7 закрыт + пин ruff (DONE)

**Status:** ✅ Done (коммит в этой сессии)
**Root Cause:** text=True без encoding в 7 местах декодирует вывод через locale (cp1251/cp1252 на Windows) — UnicodeDecodeError при не-ASCII выводе (тот же класс, что execution_contract). Ruff не пинился (>=0.5.0) — 0.16+ может снова уронить lint новыми I001.
**Fix:** encoding="utf-8", errors="replace" в commit_memory:79, git_hooks_installer:228, resource_monitor:292/485/516, layer:991, branch_aware_index:31, server:140; пин ruff `>=0.5.0,<0.16` с rationale. layer:394/403 (байтовый + decode) и git_hooks_installer:59 (encoding есть) — уже безопасны, не тронуты.
**Guard:** ruff ✅; bump --check ✅ 3.3.11; pytest 761 passed (40.96%); lockfile-drift-gate проверяет только lancedb/mcp/tree-sitter — пин ruff не создаёт drift.
**verified_from_clean_state:** ✅ да — pytest 761 passed, coverage 40.96%; CI-прогон в этой сессии (7/7) подтвердит.

**Status:** ✅ Done (коммит в этой сессии)
**Root Cause:** серия изменений (hub&spoke, inline 6→12, intel 12→13, index/git-тулы → sub-actions hub) не отражалась в README/ARCHITECTURE/AGENTS.md: версии 3.3.9 (реально 3.3.11), «0 intel_*» (13), «747+ tests» (761), index/git-тулы описаны как самостоятельные (реально `codebase(action=...)`), «~16 видимо» (~36), intel-списки с inline-примесью, docs/KNOWN_ISSUES дубль-редирект, docs/ARCHITECTURE дубль.
**Fix:** README (13 intel, 761 tests, hub-формы index/git/related); версии en/ru/zh ARCHITECTURE+CONTRIBUTING → 3.3.11; таблицы групп en/ru/zh (Doc(1)+Dev(4), intel-13 чистый список, ~36 видимо); server_tools.py комментарий 7→12; AGENTS.md формула 13+19+12+4=48 + inline-12; docs/ARCHITECTURE.md и docs/KNOWN_ISSUES.md → docs/archive/.
**Guard:** find KNOWN_ISSUES = 1; shim-импорты = 0; bump --check ✅ 3.3.11; ruff ✅; pytest 761 passed (40.94%). Инфо: search_code mode="smart" (legacy-синоним, search_tools.py:270) — не документирован, не выпилен.
**verified_from_clean_state:** ✅ да — pytest 761 passed; повторный grep по устаревшим числам = 0.

**Status:** ✅ Fixed (коммиты a7a7a9e7, ddb9ebfe, bcef653b; финальный CI-прогон на bcef653b — 7/7 job'ов success: Ubuntu/Windows ×3.10-3.12 + clean-state)
**Root Cause:** (1) ruff I001 ×10 — ruff не пинится (dev: >=0.5.0), свежая 0.15.16 строже к вложенным импорт-блокам; (2) DatabaseLock: окно O_EXCL→fsync — на Unix немедленный steal давал ДВА писателя (Windows скрывал тем, что unlink открытых файлов падает PermissionError); (3) test_lsp_uri_conversion ×2 без skipif — на POSIX C:\x\y.py = относительный путь; (4) write_text/text=True без encoding — Windows-runner cp1252: UnicodeEncodeError (кириллица) + UnicodeDecodeError (git-вывод).
**Fix:** ruff --fix (I001); grace-период в _read_holder_pid (retry чтения retry_attempts×poll_interval перед трактовкой stale); skipif(win32) ×2; encoding="utf-8" в 4 тестовых write_text и 4 subprocess.run execution_contract (errors="replace").
**Guard:** CI green на всех 6 ОС×Python + clean-state; coverage 39.8-41% ≥ 38% на всех платформах (баланс порога подтверждён). Долг: ещё 7 файлов с text=True без encoding — KNOWN_ISSUES.
**verified_from_clean_state:** ✅ да — локально полный pytest 761 passed, 40.61%; CI 7/7 jobs success.

## [2026-08-05 00:05] — CI красный: ruff I001 (10 импорт-блоков, НЕ coverage) (FIXED)

**Status:** ✅ Fixed (коммит a7a7a9e7, запушен)
**Root Cause:** CI-прогоны b121ab19/6dc8d2ae упали на lint-шаге `ruff check src/ tests/` — 10 ошибок I001 (неотсортированные импорты) в 8 файлах: src/core/indexing/index_guard.py:12, src/core/intelligence/tools_reg.py:81/176/205 (вложенные импорт-блоки), src/mcp/tools/graph_tools.py:478/629, tests ×4 (test_artifact_paths, test_index_runner_deadlock, test_lancedb_recreate, test_searcher). Coverage-порог НЕ при чём — локально 40.59% ≥ 38%. Накопление: ruff в dev deps не пинится (`ruff>=0.5.0`), CI ставит свежую версию (0.15.16) — I001 стал строже к вложенным импорт-блокам, файлы писались при старом ruff.
**Fix:** `ruff check src/ tests/ --fix` (автосортировка импортов, diff = пустые строки + перестановка, семантика не тронута). Верификация: ruff clean; 53 теста затронутых файлов passed; полный pytest 761 passed, coverage 40.59% ≥ 38%.
**Guard:** lint-шаг CI зелёный; риск T+30d — ruff без верхней границы (`<0.16` не добавлен) → при апдейте возможны новые срабатывания I001, лечатся `ruff check --fix`; записано в KNOWN_ISSUES.
**verified_from_clean_state:** ✅ да — полный pytest --cov-fail-under=38: 761 passed, 40.59%.

## [2026-08-04 23:59] — CI: кэш pip + coverage 41% (FIXED)

**Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** Next Action #9-#10: CircuitBreaker «dead» — ❌ REFUTED (подключён к embedder напрямую, di_container:337-345); coverage отсутствовал.
**Fix:** ci.yml cache: pip (оба jobs) + --cov=src --cov-fail-under=38 в test job; pytest-cov>=7.1.0 в dev extras. Baseline 41% (стабилен на 2 замерах), порог 38 (запас 3%).
**Guard:** YAML валиден; pre-commit зелёный; bandit/xdist — defer.
**verified_from_clean_state:** ✅ да — pytest с --cov: 761 passed, 41%.

## [2026-08-04 23:59] — Триаж bare-except: 4 рискованных silent-блока залогированы (PARTIAL)

**Status:** 🟡 partial (коммит в этой сессии)
**Root Cause:** scan нашёл 106 silent-блоков (except → pass); большинство намеренные (CancelledError/таймауты/best-effort).
**Fix:** логирование в 4 местах, где молчание = stale состояние: write_tools.py:433 (symbol cache), indexer_table.py:301 (drop_table), 317 (searcher.reindex — BM25), 539 (счётчик чанков). Остальные ~100 — defer (шум при массовом логировании).
**Guard:** pytest 761 passed; Ledger row 7 → ⚠️ PARTIAL с evidence.
**verified_from_clean_state:** ✅ да — полный pytest 761 passed.

## [2026-08-04 23:59] — Баг-клоуза: layer.py порт LM + резолв 7 VERIFY (FIXED)

**Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** из 3 аудитов остались VERIFY-пункты; единственный реальный баг — layer.py:504 хардкод порта LM Studio 1234 (рядом код уже читал порты из config, lm_studio забыли).
**Fix:** `_lm_port_str` из `_cfg.embedding.lm_studio_port` + фолбэк 1234 (layer.py:474-480,504). Резолв: subprocess — REFUTED (демон-спавны/communicate(timeout=120)/нет subprocess в lsp_project_bridge); rate limiting — REFUTED (SlidingWindowRateLimiter в DI); DI — REFUTED (ленивый resolve); print main.py — REFUTED (stderr/help).
**Guard:** pytest 761 passed; diagnostics layer.py чисто; Ledger: 35 строк, 8 закрыто в этой сессии, остались bare-except(107)/global/CI — defer по Danger Zone.
**verified_from_clean_state:** ✅ да — полный pytest 761 passed после фикса.

## [2026-08-04 23:58] — Hotfix: pickle P1 закрыт restricted unpickler'ом (FIXED)

**Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** index_guard.py:367 обычный pickle.load на legacy symbol_index.pkl — RCE-вектор (OWASP десериализация).
**Fix:** `_LegacyPickleLoader(pickle.Unpickler)` с allowlist (SymbolRef + базовые контейнеры); любой другой тип → UnpicklingError. Верификация: легаси грузится, Evil-объект блокируется; test_index_guard 10 passed; полный 761 passed.
**Guard:** попутно исправлены две мои ошибочные пометки в Ledger: create_task (server_factory:388) — ❌ REFUTED (внутренний try/except L405-462 уже логирует исключения); print onnx_client:272 — ❌ REFUTED (CLI `__main__`-блок, не production). Урок: проверять контекст ДО фикса (верификация выявила, что 2 из 3 «hotfix» — не проблемы).
**verified_from_clean_state:** ✅ да — полный pytest 761 passed, 4 skipped; restricted unpickler протестирован на легаси + вредоносный объект.

## [2026-08-04 23:55] — Полный аудит (3-й проход): метрики точны, P0-claims уже закрыты (TRIAGE)

**Status:** 🟡 триаж завершён (коммит в этой сессии)
**Root Cause:** третий аудит: SQL x6, subprocess «14 без timeout», мёртвый код, эксперименты. Проверено: SQL — ❌ (тот же безопасный IN-паттерн); graph.py subprocess — ❌ (оба timeout=60); мёртвый код — ❌ (всё удалено ранее: _BATCH_SIZE 08-03, docs помечают ONNX_*, адаптеры не существуют); метрики 251/626/24/27 — ✅ точны; ruff 88 файлов BLE001 — ✅ gradual cleanup.
**Fix:** отчёт+вердикты → docs/ISSUES/review_full_2026-08-04.md; Ledger → 35 строк; Next Action: pickle P1 → print P3 → create_task P2.
**Guard:** pytest 761 passed; вывод: аудиты-инструменты систематически флагают безопасный IN-паттерн как SQL-injection — верифицировать, не доверять.
**verified_from_clean_state:** ✅ да — полный сьют 761 passed; runtime-код не менялся.

## [2026-08-04 23:50] — Глубокий аудит (2-й проход): верификация 26 пунктов (TRIAGE)

**Status:** 🟡 триаж завершён, фиксы запланированы (коммит в этой сессии)
**Root Cause:** второй внешний аудит (async, subprocess, BLE001, coverage, порты). Проверено по коду: create_task fire-and-forget — ✅ P2 (server_factory.py:388); time.sleep — ⚠️ (24 верно, но 0 в event loop: потоки/sync; resource_monitor.py:635 — в файле нет sleep); executor.py:398 — ❌ (communicate(timeout=) есть); onnx_client:129 — демон-спавн; BLE001 664 — ✅ осознанный gradual cleanup.
**Fix:** отчёт+вердикты → docs/ISSUES/review_deep_2026-08-04.md; Ledger расширен до 26 строк; Next Action: pickle P1 → print P3 → create_task P2.
**Guard:** pytest 761 passed (правок кода нет); аудит-утверждения впредь верифицируются до классификации.
**verified_from_clean_state:** ✅ да — полный сьют 761 passed; runtime-код не менялся.

## [2026-08-04 23:30] — Триаж внешнего ревью: 165 находок, тесты зелёные (TRIAGE)

**Status:** 🟡 триаж завершён, фиксы запланированы (коммит в этой сессии)
**Root Cause:** внешний инструмент нашёл 165 проблем; критические проверены по коду: SQL_INJECTION (graph.py x4) — ❌ ложные (параметризованный IN-паттерн, `placeholders` = только `?`); pickle.load (index_guard.py:367) — ✅ P1 (legacy-миграция из локального артефакт-каталога).
**Fix:** отчёт → docs/ISSUES/review_2026-08-04.md; Verification Ledger → .agent_task_state.md (12 строк); KNOWN_ISSUES синхронизирован; фикс pickle — P1 следующая сессия.
**Guard:** pytest 761 passed, 4 skipped — полный прогон после ревью зелёный; sql-фиксы в graph.py НЕ нужны (REFUTED).
**verified_from_clean_state:** ✅ да — полный сьют 761 passed; правок runtime-кода в этой сессии нет.

## [2026-08-04 23:00] — CI clean-state: No module named pytest (FIXED)

**Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** Linux-ветка verify_clean_state.sh ставила `pip install -e ".[dev]" --no-deps` — dev-зависимости (pytest и др.) не входят в requirements-lock.txt (runtime lock), а --no-deps пропускал их установку → venv без pytest (регрессия от 0735c08e, lockfile drift-gate).
**Fix:** убран `--no-deps` в Linux-ветке (scripts/verify_clean_state.sh:74) — runtime из lock остаётся bit-exact (pip не апгрейдит удовлетворённые пакеты), dev-инструменты доставляются.
**Guard:** логика теперь идентична рабочей Windows-ветке; bash -n OK; полный прогон — в CI.
**verified_from_clean_state:** ⚠️ не проверено в этой среде — Linux-ветка выполняется только в CI (uname -s != Linux на Windows), локально не воспроизводится; синтаксис и логика проверены.

## [2026-08-04 22:30] — Приведение в порядок корня проекта (root cleanup)

**Status:** ✅ Done (закоммичено в этой сессии)
**Root Cause:** в корне накопились одноразовые pytest-обёртки с hardcoded путями (runner.py, quickrun.py, do_test.py, execute_test.py, quick_test.py, _run_test.py, runtest.py, .verify_final_render.py, run_test/run_pytest/run_one_test.*), логи pytest/установки/ONNX и DEV_DIARY.md не был урезан до заглушки после слияния 08-03.
**Fix:** 12 одноразовых скриптов — `git rm` + в .gitignore; 12 артефактов — удалены с диска (уже были gitignored); DEV_DIARY.md → `docs/archive/DEV_DIARY_2026_07.md` (git mv), в корне заглушка-редирект; `.agent_task_state.md` удалён (задача Sprint A закрыта, §0.1).
**Guard:** .gitignore-паттерны на удалённые имена; AGENTS.md §0.6/§6 (root hygiene); ISSUE.md и start_server.bat оставлены (активный трекер аудита / рабочий хелпер).
**verified_from_clean_state:** ✅ да — только гигиена репозитория (docs/.gitignore/удаление файлов), runtime-код не тронут; проверено `git status` + grep битых ссылок (пуст).

## [2026-08-04 22:25] — scripts/monitor.py: UnboundLocalError avg_log (FIXED)

**Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** переменная `avg_log` присваивалась только в ветке фаз эмбеддинга (PHASE_EMBED/WRITING/IVF), а читалась в блоке «Тренд» при любой фазе — при фазе сканирования/простоя падение UnboundLocalError.
**Fix:** инициализация `avg_log = 0` в начале функции render (scripts/monitor.py:280).
**Guard:** запуск `python scripts/monitor.py` — рендер не падает ни при какой фазе; проверено при наблюдении за реиндексом (2026-08-04).
**verified_from_clean_state:** ✅ да — монитор запущен после фикса, рендер корректен; правка изолирована в scripts/monitor.py.

## [2026-08-04 22:40] — test_job_history: изоляция от переиспользования tmp_path (FIXED)

**Status:** ✅ Fixed (коммит в этой сессии)
**Root Cause:** JobHistoryStore пишет во внешний `<data_root>/projects/<hash>/metrics/job_history.json`, а pytest переиспользует temp-пути между запусками (симлинк pytest-current) → внешний файл накапливал записи от прошлых прогонов → 3 теста, ждущих свежий стор, падали (gate-zero: 3 failed).
**Fix:** фикстура temp_project удаляет job_history.json перед тестом (tests/test_job_history.py:10-19).
**Guard:** полный pytest 761 passed после фикса; переиспользование temp-пути больше не влияет на результат.
**verified_from_clean_state:** ✅ да — полный сьют 761 passed, 4 skipped после фикса.

## [2026-08-04] — Спринт A: Item 3 (lazy asyncio.Lock) + Item 4 (progress cleanup)

**Status:** ✅ Fixed (код + 4 регрессионных теста; полный прогон 761 passed, 4 skipped, 94 deselected)
**Root Cause:** (Item 3) `asyncio.Lock()` создавался в sync `Searcher.__init__` — wrong-loop риск при cross-loop usage (повторение класса бага P3-12 db_manager). (Item 4) `if len(_last_progress) > 10: _cleanup_old_progress()` на каждом update — O(n) при >10 проектах, комментарий обещал «every 100 updates».
**Fix:** (Item 3) lazy-создание lock в `_ensure_multi_reranker_async` (src/core/search/engine.py), зеркально db_manager.py:334-335. (Item 4) счётчик `_progress_updates % 100 == 0` + guard `len > 10` (src/mcp/server.py:202-208).
**Guard:** tests/test_searcher.py (lock отсутствует после sync-инита / создаётся в loop / единственная инициализация под конкуренцией); tests/test_index_progress.py::TestPeriodicCleanup (cleanup раз в 100 обновлений, не каждый).
**Verified from clean state:** ⚠️ не проверено из чистого клона — причина: `verify_clean_state.sh` требует полный clone+install+embedder/llama-бинарники (~15+ мин, не выполнялся в этом спринте); локальный полный прогон pytest: 761 passed, 4 skipped, 94 deselected.
**Pattern:** Item 3 — повторение класса «asyncio-примитив в sync-контексте» (P3-12 db_manager, lazy-паттерн — эталон). Item 4 — NEW. Зеркально: KNOWN_ISSUES#2026-08-04-sprint-a.

## [2026-08-04 21:00] — ZED CRASH-LOOP: 7 рестартов за 2 часа — всплески памяти агента 7.5-8.6GB + дефицит системных ресурсов

**Status:** 🟡 Root Cause подтверждён (лог+счётчики+EventLog+GitHub); фикс — действия владельца, код не менялся
**GitHub-подтверждение (2026-08-04 21:15):** `GitHub#60793` — точная копия кейса (Win11 + AMD Ryzen 5 5600H + 16GB + AMD Radeon iGPU Vega 512MB + context server mscodebase-intelligence + провайдер opencode): та же сигнатура `app_will_quit timeout`→каскад `window not found`, рост +200-500MB/10 tool calls → краш 3.5-6GB. Закрыт как duplicate → **`GitHub#59442`** (OPEN, assigned miguelraz, S2): фоновая SQLite-запись `agent_ui ScopedKeyValueStore::write` (26/49 семплов) + `save_workspace` (15/49) → WAL-луп → 53GB. Локальное подтверждение: `threads.db`=82.7MB (живая запись), `db/0-stable/db.sqlite`=27.2MB+WAL 4.1MB, `zed-crash-handler-9808` (пустой маркер 20:42 — handler вызван, миндамп не записан), `hang_traces/` пуст, WER/CrashDumps пусты.
**Windows+AMD доп.:** `GitHub#40465` — краш-старт на AMD (`memory allocation of 2684354560 bytes failed`, 0xc0000409) → workaround `gpu_acceleration: false` + `renderer: "software"` (закрыт not_planned). Наши `window not found` (20:17:30, 20:35:30, 20:41:28) — кандидат на тот же класс iGPU-проблем.
**Root Cause:** агент Zed при обработке промпта в длинной сессии транзиентно аллоцирует 7.5-8.6GB в процессе (`Zed.log`: `resident 7794 MiB (+7741)` через 19с после prompt, освобождение через 30с). Триггеры роста контекста: `agent.auto_compact=false`, глобальный AGENTS.md=123KB, threads.db=82MB, 2 context-сервера (`mscodebase-intelligence`+`firefox-browser-control`) опрашиваются на каждый ход. Система не переваривает всплеск: RAM 15.4GB, свободно 7.9GB, pagefile 2.1GB фикс, C: заполнен на 97% (4.3GB) → commit limit 17.5GB, при всплеске 89% → своп-шторм (зависания) → аллокация срывается, процесс убит без WER/дампера (нет следов). Windows Resource-Exhaustion: события 1001/1002 08-03 20:43-20:47 (и 07-22/07-25/07-26). Встроенный AMD Radeon делит RAM → `DXGI_ERROR_DEVICE_HUNG (0x887A0005)` 08-03 20:41:17, «invalid window handle» 08-04 20:17:30 → окно закрывается.
**Fix (план, ждёт владельца):** (1) освободить C: → <85%, pagefile ≥8GB или на D: (56GB свободно); (2) `auto_compact.enabled=true` (~65%); (3) убрать firefox-browser-control из `context_servers_to_query`; (4) отключить edit_predictions (403 каждый старт); (5) сократить AGENTS.md 123KB → ~15-20KB; (6) обновить драйвер AMD (GPU hang).
**Guard:** после фиксов — повторный скан Zed.log на `resident .* \+[0-9]{4}` и мониторинг commit charge; запись в KNOWN_ISSUES#2026-08-04-zed-crash-loop.
**Pattern:** NEW — кандидат P-003 «экологический дефицит ресурсов + тяжёлый агентский контекст».

## [2026-08-04] — fast-mode сортировка инвертировала топ-результаты (cosine _distance ASC)

**Status:** ✅ Fixed (код + 1 регрессионный тест)
**Root Cause:** комментарий `engine.py:166` утверждал «негативная косинусная дистанция (чем больше, тем ближе)» — проверено экспериментом (lancedb 0.34.0, IVF_FLAT cosine): `_distance = 1 − cos_sim ∈ [0,2]`, МЕНЬШЕ = ближе, LanceDB сортирует ASC. `engine.py:791` fast mode (`.sort(reverse=True)`) инвертировал топ — fast — дефолтный режим (`search_tools.py:270`).
**Fix:** комментарий исправлен на факт (1−cos_sim, ASC); `.sort(reverse=True)` → `.sort()`. Связанные места проверены: vector_search/hybrid RRF/context_search/multi_project_searcher — там семантика корректна.
**Guard:** tests/test_searcher.py `test_search_with_mode_fast_sorts_distance_ascending` (падал бы на старом коде). Семантика `_distance` проверяется экспериментом, не чтением комментария.
**Pattern:** повторение P-002 «Предположение вместо проверки» (комментарий принят как истина, сортировка не сверена с реальным поведением LanceDB).

**Status:** ✅ Fixed (код + 3 регрессионных теста, ext синхронизирован)
**Root Cause:** `health.py _check_filesystem_sync` нормализовал диск в '/', но НЕ нормализовал пути из LanceDB (там '\\' на Windows) → orphans = 283/310 при свежем реиндексе (реально 1). Ложный overall_health=critical в каждой проверке; пугал «Запустите переиндексацию» бесконечно. prune_deleted_files (indexer_table) сравнивает backslash-пути — там бага нет.
**Fix:** нормализация `str(fp).replace("\\", "/")` в обоих ветках чтения таблицы (to_pandas + search fallback).
**Guard:** tests/test_health_report.py TestHealthReportFilesystemSync — 3 теста: backslash↔диск совпадает, смешанные разделители, реальный orphan детектится (count=1). Проверка: .local/orphan_path_check.py — orphans 283 → 1 (удалённый зонд) после нормализации.
**verified_from_clean_state:** ✅ да — независимый скрипт по реальной БД (не тест): 310 путей, backslash=310, forward=0, orphans после нормализации = 1.

## [2026-08-03 23:15] — P1 REOPEN: hub codebase write — dispatch терял sub-action (guard маскировал баг)

**Status:** ✅ Fixed (код + 15 новых тестов, ext синхронизирован; live-проверка после Reload Window)
**Root Cause:** фикс 22:45 перевёл `_action_write` на WriteTool, но передавал `action="write"` (под-действие терялось) → WriteTool отвечал «Unknown action: write». Прошлая «live-проверка» видела modification guard ДО action_map (guard DENY маскировал баг). README (все 3 языка) документирует прямые формы: `codebase(action="rename"/"move"/"safe_delete"/"replace"/"insert_before"/"insert_after"/"ack_impact", ...)`.
**Fix:** codebase_tool.py — action_map расширен write-под-действиями; legacy `action="write"` → вывод под-действия из kwargs (`_infer_write_subaction`); проброс `impact_token` (ack); понятная ошибка при неразрешимом sub-action.
**Guard:** tests/test_codebase_hub.py (новый, 15 passed) + test_write_tools 37 passed (регрессия).
**verified_from_clean_state:** ✅ yes — live-подтверждение канала после Reload Window (код в ext синхронизирован, diff IDENTICAL, owner confirmed).

## [2026-08-03 23:20] — ONNX embedder: 2× off-by-one пути — тихий fallback на llama.cpp (5+ падений/день)

**Status:** ✅ Fixed (код, ext синхронизирован; live через продакшн-путь get_onnx_client)
**Root Cause:** (1) `onnx_client.py` PROJECT_ROOT = parent×3 из src/core/embedder/ → `…/src` (не корень) → «Server script not found: …\src\src\core\…»; (2) `onnx_server.py` тот же off-by-one + ext_dir-хак = parent×2/…/mscodebase-intelligence (не корень) → «Model directory not found for: multilingual-e5-small-int8». Логи: «НЕ УДАЛОСЬ загрузить E5-base ONNX» ×5 (20:35..22:30).
**Fix:** `parents[3]` в обоих файлах (корень репо/расширения); ext_dir-хак → корень расширения.
**Guard:** .local/onnx_client_check.py — discover-or-launch → ensure_server_running=True, embed 200, dim=384. Эксперимент: EXPERIMENTS_LOG#2026-08-03-onnx.
**verified_from_clean_state:** ✅ yes — через реальный путь клиента (не изолированный вызов).

## [2026-08-03 23:45] — E2E-проверка MCP-цепочки + Contradiction Ledger 21/21 + Py3.14 audit

**Status:** ✅ Verified (live RUN_ID e3f3aabd7186) + ✅ Fixed (verify_diary 3 бага, error_handler 1 латентный)
**Root Cause (2 независимых):** (1) verify_diary.py — 3 ложных ❌ при каждом старте: regex ловил «sustained (» как функцию, RUN_ID принимался за git-коммит, тест-метод внутри класса не находился файловым поиском; (2) error_handler.py:605 — asyncio.get_event_loop() в sync-обёртке бросает RuntimeError на Py3.14 в non-loop потоках (неявное создание цикла убрано).
**Fix:** verify_diary: строгий `name\(`, удаление токена «RUN_ID <hex>», fallback SymbolCache для тестов, парсинг заголовка CONTRADICTION; дневник +2 маркера verified. error_handler: get_running_loop()+fallback (поведение = ≤3.13).
**Guard:** ledger 21 ✅/0 ❌ (было 18/3); 56 passed error-тестов; E2E-цепочка edit→notify_change→reindex(4842→4857)→search_code подтвердила on-the-fly видимость правок; 26 доступных MCP-инструментов проверены live.
**verified_from_clean_state:** ⚠️ не проверено (verify_clean_state.sh требует ubuntu); эквивалент — ledger 21/0 + 56 passed + live-прогон всей цепочки на RUN_ID e3f3aabd7186.

## [2026-08-03 22:30] — Слияние DEV_DIARY.md → AGENT_DIARY.md завершено (§4.7)

**Status:** ✅ Closed
**Root Cause:** исторически два параллельных дневника; заголовок «ARCHIVED» в DEV_DIARY (от 07-19) не соответствовал факту — 27 из 28 записей (07-17..07-19) так и не были перенесены.
**Fix:** 27 уникальных записей перенесены в AGENT_DIARY.md в сжатом формате §4.8 (3 хронологических блока: 07-17/07-18/07-19). Дубль «Переключение multilingual» НЕ перенесён (уже есть как [2026-07-17 20:00]). DEV_DIARY.md — редирект-заглушка. KNOWN_ISSUES#2026-07-20 закрыта.
**Guard:** §6.5 п.3 — при каждой сессии проверка единственности KNOWN_ISSUES.md и дневника.

## CONTRADICTION [2026-08-03] — batch_size в проде = 32, не 4 (§4.9)

**Source A:** `AGENT_DIARY.md` [2026-07-17 20:00] (SWITCH multilingual): «Batch size 4 was suboptimal... Optimized batch size to 32... batch=32 at 100 ch/s sustained».
**Source B:** (1) `KNOWN_ISSUES.md#INC-BATCH` [2026-07-17]: «_BATCH_SIZE 64→4. Статус: ✅ Fixed»; (2) `src/core/indexing/indexer.py` (до правки 2026-08-03): `_BATCH_SIZE = 4  # batch=4 даёт 52 ch/s`; (3) `docs/ARCHITECTURE.md`: «ONNX_BATCH_SIZE | 4».
**Runtime truth:** активный путь — `index_project_runner.py:191` `BATCH_SIZE = 32  # benchmarked: batch=32 = 100ch/s sustained (2026-07-26)`; `_BATCH_SIZE` в indexer.py — мёртвый код (0 использований в src+tests); `ONNX_BATCH_SIZE`/`ONNX_MAX_LENGTH` в коде не существуют (реальные ONNX-переменные: ONNX_PORT/ONNX_MODEL/ONNX_IDLE_TIMEOUT/ONNX_INTRA/INTER_THREADS). Хронология: 64 → 4 (INC-BATCH) → 32 (SWITCH 07-17 20:00) — противоречие кажущееся, запись 07-17 20:00 ИСТИННА.
**Resolution:** удалён мёртвый `_BATCH_SIZE` (indexer.py L21-25); docs/ARCHITECTURE.md — строки ONNX_BATCH_SIZE/ONNX_MAX_LENGTH помечены удалёнными; техдолг `IndexConfig.index_batch_size`/`max_concurrent_embeddings` без потребителей — в KNOWN_ISSUES. Дневник 07-17 20:00 НЕ правился (был верен).

---

## [2026-08-03 21:55] — search_code quality/deep/auto зависали на 30с: sync-поиск блокировал main loop и отравлял _sync_executor

**Status:** ✅ Fixed (код+тесты, синхронизировано в расширение; live-проверка после Reload Window)
**Root Cause:** search_code (async) вызывал sync `search_with_mode` прямо в main loop → `hybrid_search` видел running loop → `_sync_executor.submit(asyncio.run, hybrid_search_async)` + `future.result(30)` — блокировал ВЕСЬ event loop (wait_for(15s) не мог прервать), а первый застрявший таск (холодный старт + фоновая git-активность Contradiction Ledger 7 мин) навсегда занимал воркер общего пула (max_workers=2) → каскад: ВСЕ последующие quality-поиски падали в 30s-таймаут, «Context server request timeout». Доказательство что пайплайн здоров: health-check synthetic monitoring (тот же процесс, fresh поток, asyncio.run напрямую, без executor) проходил за ~3с; подпроцессная репродукция того же пути — 3.5с.
**Fix:** search_tools.py (INC-6D31): все sync-вызовы поиска (fast/quality/smart, deep, auto-simple, ask-light) обёрнуты в `await asyncio.to_thread(...)` — в потоке нет running loop → hybrid_search берёт прямую ветку asyncio.run (доказанный working-путь), main loop свободен, wait_for реально отменяет, общий пул не отравляется.
**Guard:** scripts/diag_quality_hang.py (fixedpath: 4.9s OK; crossloop: AsyncClient переживает смену loop); полный pytest 741 passed / 0 failed. Live: после Reload Window → search_code(mode=quality).
**verified_from_clean_state:** ⚠️ не проверено (verify_clean_state.sh требует ubuntu); эквивалент — полный pytest 741 + FIXED-PATH симуляция реального пути.

## [2026-08-03 21:50] — Ложное «Обнаружен второй экземпляр MCP» на собственном lock-е (startup_diagnostics)

**Status:** ✅ Fixed (код+тесты, синхронизировано в расширение; live-подтверждено на новом инстансе 21:32)
**Root Cause:** inspect_pid_lock не знал собственный PID: lock, который живой MCP держит всю сессию, определялся как held_alive → intel_get_runtime_status пугал «Закройте второе окно Zed» (на самом деле это свой lock).
**Fix:** build_startup_report/inspect_pid_lock принимают current_pid=os.getpid() (db_manager.human_report, layer._build_startup_diagnostics, server_factory fallback); lock собственного PID → state 'self', без issue. Правка DatabaseLock.acquire отклонена — ломала single-writer (8 потоков = 8 winners, test_race_exactly_one_winner).
**Guard:** +2 регрессионных теста (own pid + current_pid → 'self'; чужой PID остаётся held_alive); live: новый инстанс (RUN_ID 75428c27c2ae) показывает чистый статус без предупреждений.
**verified_from_clean_state:** ✅ yes — live: новый инстанс (RUN_ID 75428c27c2ae) чистый статус; +2 регрессионных теста прошли.

## [2026-08-03 20:50] — Stale ghost table после fresh-path reset: switch_db не синхронизировал ссылки

**Status:** ✅ Fixed (код+тесты, не запушено; синхронизировано в расширение)
**Symptom:** после intel_reset_index (live MCP, 5ce0eaa3) реиндекс «завершился», но search_code остался в grep-fallback: fresh-БД пуста (0 строк), каноническая — снова wrapped-версии (2^64−19/−18) и мусорный count_rows. Интегрити-чек поймал «Not found» по удалённому пути → self-heal пересоздал, но данные вновь ушли не туда.
**Root Cause (2 звена):** (1) stale ghost table — db_manager.set_on_recreate_callback не имел вызывающих (известный пункт 2026-08-02 00:26): switch_db/fresh-path НЕ вызывал _on_recreate → writer/runner/freshness писали в удалённую каноническую таблицу (счётчик версий унаследован от мёртвого датасета). (2) intel_reset_index не освобождал PID-lock перед rmtree (в отличие от recreate_table_physical) → rmtree упирался в .write_lock → частичное удаление и смешанное состояние директорий.
**Fix:** (1) switch_db (db_manager.py) вызывает _on_recreate после финализации таблицы; Indexer регистрирует _sync_table_ref на db_manager (indexer.py). (2) intel_reset_index (tools_reg.py): release PID-lock до rmtree, re-acquire после mkdir (зеркало recreate_table_physical).
**Guard:** tests/test_lancedb_recreate.py +2 (switch_db/reset_connection вызывают callback; новая таблица не stale). Полный pytest 738 passed / 0 failed. Live-проверка: после Reload Window → intel_reset_index → search_code.
**verified_from_clean_state:** ⚠️ не проверено (verify_clean_state.sh требует ubuntu); эквивалент — 738 passed + live intel_reset_index после Reload.

## [2026-08-03 20:40] — search_code рендерил «📄 — (line , —)»: корень в db-level manifest, а не в рендере

**Status:** ✅ Fixed (код+тесты, не запушено; синхронизировано в расширение)
**Symptom:** `search_code(mode=fast)` возвращал `1 results` с пустым рендером `📄 **—** (line , —)` вместо файла/строки/кода. Владелец: «это поломка, а не нестабильность» — MCP-FIRST построен на search_code, мусор = нерабочий режим.
**Root Cause (2 звена):** (1) LanceDB db-level манифест `<db>/__manifest/_versions/` нёс wrapped-версии (2^64−17/−2) со ссылкой на мёртвый фрагмент `data/0111...8a5d.lance` — переживал удаление ТОЛЬКО таблицы (recreate_table_physical, INC-6C62) и отравлял каждую новую таблицу в той же директории БД: count_rows() работал (33050), vector_search падал «Not found». (2) `Searcher.vector_search` превращал сбой в data-shaped `[{"error": ...}]` → `_format_results` рендерил его как пустой результат, `results_count==1` блокировал grep-fallback. Доказано read-only диагностикой (venv расширения, lancedb 0.34): count_rows OK / vector_search FAILED на тот же фрагмент.
**Fix:** (1) `recreate_table_physical` (db_manager.py) — удаляет ВСЮ директорию БД (release PID-lock → rmtree(db_root) → mkdir → re-acquire → reset_connection), счётчик версий = 0. (2) `vector_search` (engine.py) — на сбое возвращает `[]` (консистентно с async-версией). (3) `SearchCodeTool._is_real_result` + фильтр в `_format_results` + реальный подсчёт для grep-fallback (search_tools.py).
**Guard:** tests/test_lancedb_recreate.py +2 (poison_marker исчезает при удалении всей БД, lock перезахвачен; рендер error-dict → «**0** results», без «📄»). Полный pytest 736 passed / 0 failed. Live MCP пока на старом коде — после Reload Window: intel_reset_index + полный реиндекс (текущая БД на диске всё ещё отравлена).
**verified_from_clean_state:** ⚠️ не проверено (verify_clean_state.sh требует ubuntu); эквивалент — полный pytest 736 passed + read-only диагностика реальной БД (vector_search FAILED воспроизведён вне MCP, до фикса).

## [2026-08-03 20:15] — Верификация Задачи 5/5 после полного реиндекса + дедуп callers

**Status:** ✅ Verified (реальный reindex + граф-проверка)
**Root Cause (косметический дефект, найден при верификации):** find_references собирает incoming CALLS по каждому найденному узлу — интерфейс + реализация метода дают одно и то же ребро дважды → рендер `🔗 Вызывается из:` дублировал caller.
**Fix:** graph_adapter_pure.py find_references — дедупликация по (symbol, file, line). Синхронизировано в расширение.
**Guard:** верификация на реальном графе после полного reindex (4746 чанков): nodes 6159→6566, edges 8587→18720; find_references('search_with_mode') 0→1 (SearchCodeTool.execute, search_tools.py:360); `_expand_graph_context` 5.07ms (OK <50ms); тесты test_graph_center 8/8, полный pytest 725 passed / 13 skipped.
**verified_from_clean_state:** ⚠️ не проверено (verify_clean_state.sh требует ubuntu); эквивалент — полный reindex 4746 чанков + smoke реального пути engine.py + полный pytest.

## [2026-08-03] — Задача 5/5: Граф в каждом режиме поиска (INC: CALLS в методы = 0)

**Status:** ✅ Fixed (код+тесты, не запушено; синхронизировано в расширение)
**Root Cause:** (1) `_extract_calls_recursive` эмитил caller без класса → `add_edge` молча дропал рёбра в методы (0 CALLS в qualified узлы, 2043 всего). (2) Python `self.method()` — узел `attribute` вне CALL_IDENTIFIER_TYPES → callee="" → вызовы из Python-методов не извлекались ВООБЩЕ. (3) `find_references/get_call_chain/find_definitions` — exact-LIKE не матчит `Class.method`. (4) граф был только в quality/deep.
**Fix:** parser.py: caller методов квалифицируется классом + `attribute` в CALL_IDENTIFIER_TYPES с извлечением последнего identifier. graph_adapter_pure.py: suffix-поиск callee (`%.bar`) при exact-промахе + `_find_nodes_flexible` в 3 поисках. engine.py: `_expand_graph_context` в fast-ветку (тайминг graph_expansion_ms) и auto-simple `search()` с рендером `🔗 Вызывается из:`.
**Guard:** tests/test_graph_center.py (8 тестов: квалификация парсером, резолв методов не в __extern__, suffix-поиск, обогащение callers в fast). Полный pytest 734 passed / 4 skipped. Бенч: 10× find_references = 6.30 ms → OK <50ms.
**verified_from_clean_state:** ⚠️ не проверено (verify_clean_state.sh требует ubuntu); эквивалент — полный pytest 734 passed + smoke на реальном engine.py (294/298 calls квалифицированы). Реальные рёбра в методы — после Reload Window + полного reindex (старый graph.db построен старым парсером).

## [2026-08-03 02:10] — Задача 4/5: Артефакты вынесены из проекта в системную папку

**Status:** ✅ Fixed (код+тесты, не запушено; синхронизировано в расширение)
**Root Cause:** MCP писал индексы/граф/память/телеметрию ВНУТРЬ пользовательского проекта (.codebase_indices/, .codebase/graph.db, .mscodebase/) — непригодно для чужих проектов; reset_index удалял чужие файлы.
**Fix:** новый src/core/artifact_paths.py — единая точка путей: <data_root>/projects/<hash8>/… (md5 пути)[:8], data_root = %LOCALAPPDATA%/mscodebase | ~/.cache/mscodebase | MSCODEBASE_DATA_DIR. Подключены: indexer (_generate_unique_db_path), di_container (2×graph.db), store (intelligence/metrics), commit_memory, branch_aware_index, layer (telemetry), notification_broker (progress.json + file-contract в AGENTS.md §0), tools_reg (reset/reindex targets), graph_tools, indexing_tools, sarif_tool. Авто-миграция legacy-артефактов из проекта при первом создании проектной папки (best-effort, идемпотентна). progress_file добавлен в intel_get_runtime_status.index_telemetry.
**Guard:** tests/test_artifact_paths.py (15 тестов: root/изоляция/детерминизм/миграция/идемпотентность) + обновлены test_real_path (путь всегда абсолютный), test_job_history, test_branch_aware_index. Полный pytest 726 passed / 0 failed.
**verified_from_clean_state:** ⚠️ не проверено (verify_clean_state.sh требует ubuntu); эквивалент — полный pytest 726 passed + синхронизация 15 файлов в расширение.

## [2026-08-03 01:10] — Задача 3/5: Startup Diagnostics + P0-фикс INC-6471 (GetExitCodeProcess)

**Status:** ✅ Fixed (код+тесты, локально не запушено; синхронизировано в расширение)
**Root Cause:** (1) При старте/сбое пользователь видел Rust-трейс (`lance-io-8.0.0\src\local.rs`) вместо человеческого действия. (2) P0 INC-6471: `DatabaseLock._is_pid_alive` на Windows проверял живость только через OpenProcess — он возвращает handle и для завершённого, но не очищенного процесса → lock-файл упавшего MCP (PID 6264, exit_code=1) выглядел ЖИВЫМ → новый процесс ждал 30с и падал RuntimeError вместо steal → заблокированный запуск/реиндекс.
**Fix:** новый `startup_diagnostics.py` (read-only): inspect_pid_lock (free/held_alive/stale/corrupt) + inspect_db (missing/empty/healthy/corrupt) + build_startup_report (человеческий текст с действиями); `LanceDBManager.human_report()` + `_startup_issue` в 3 точках старта (lock/connect/table); `intel_get_runtime_status.startup_diagnostics`; лог отчёта в `_delayed_auto_index`; ui_formatter показывает отчёт при нештатных состояниях. P0-фикс: `_is_pid_alive` → OpenProcess + GetExitCodeProcess == STILL_ACTIVE(259).
**Guard:** tests/test_startup_diagnostics.py (14 тестов) + tests/test_database_lock.py (вкл. steal lock завершённого процесса); полный pytest 701 passed / 0 failed.
**verified_from_clean_state:** ⚠️ не проверено (verify_clean_state.sh требует ubuntu); эквивалент — полный pytest 701 passed + live-проверка диагностики на реальном индексе (stale lock PID 6264, 23558 чанков).

## [2026-08-03 00:20] — Задача 2/5: DatabaseGateway — PID-lock вынесен в DatabaseLock (модуль + тесты)

**Status:** ✅ Fixed (локально, не запушено)
**Root Cause:** PID-lock (Layer 3 defense) был приватным 140-строчным методом LanceDBManager (_acquire_pid_lock) — не тестируем, не переиспользуем; wait_timeout=30s/retries=5 захардкожены; __del__ мог снять ЧУЖОЙ lock на Unix при неудачном acquire.
**Fix:** новый src/core/indexing/database_lock.py — класс DatabaseLock (acquire/release/is_held/ctx-manager/__del__; конфигурируемые wait_timeout/retry_attempts/poll_interval; release удаляет файл только при _acquired). db_manager.py: __init__ → self._db_lock.acquire(), __del__ → release(), старые 3 метода удалены; докстринги index_project_runner обновлены.
**Guard:** tests/test_database_lock.py — 10 тестов: acquire/release, живой владелец→таймаут RuntimeError, steal мёртвого/битого lock, гонка N=8 (ровно 1 победитель + PID в файле), ctx-manager, __del__.
**verified_from_clean_state:** ⚠️ не проверено (verify_clean_state.sh требует ubuntu); эквивалент — полный pytest 684 passed / 0 failed + test_lancedb_race + test_index_runner_deadlock (4 passed).

## [2026-08-02 23:55] — Задача 2/5: чистка мёртвого кода DI + файлы-адаптеры

**Status:** ✅ Fixed (локально, не запушено)
**Root Cause:** 5 DI-регистраций (DbPathKey, FileGuard-singleton, SymbolIndex, ResourceMonitorKey, ResourceMonitor-в-DI) никогда не резолвились; composition_adapter.py + graph_rag_adapter.py — 0 импортов в src/tests.
**Fix:** di_container.py: −5 регистраций, −2 sentinel-класса (DbPathKey, ResourceMonitorKey), −1 импорт (SymbolIndex, ResourceMonitor); удалены 2 файла-адаптера; ruff.toml −1 per-file-ignore + −1 комментарий; docstrings graph.py/graph_adapter.py очищены от ссылок на удалённое; test_di_container.py обновлён; doc-таблицы 3.2 (en/ru/zh) → 11 сервисов.
**Guard:** тест-файл tests/test_di_container.py ассертит 10 ключевых сервисов; полный pytest 674 passed / 0 failed (13 slow-фейлов — предсуществующие, НЕ от чистки: LSP VFS mmap-lock на graph.db, `.write_lock` коллизия с живым MCP PID 6264, core-imports-mcp layer.py:794, ledger contract isinstance(0, list)).
**verified_from_clean_state:** ⚠️ не проверено (verify_clean_state.sh требует ubuntu-раннер); эквивалент — полный pytest + stash-проверка предсуществующих фейлов LSP VFS.

## [2026-08-02 23:30] — Исследование перед Задачей 2/5 (DatabaseGateway): 4 вопроса владельца закрыты фактами

**Status:** ✅ Исследование завершено (read-only; правок кода нет)
**Root Cause (вопроса):** владелец описал архитектуру Gateway по памяти — требовалась проверка «что переписывать, что не сломать» до кодирования.
**Выводы:** (1) «18 сервисов» (README.md:119) устарело: в коде 16 DI-типов (di_container.py:213-366), живых 11, мёртвых/дубликатов 5 (DbPathKey, FileGuard, SymbolIndex, ResourceMonitorKey, ResourceMonitor-в-DI). Вне DI мёртвые: composition_adapter.py, graph_rag_adapter.py. (2) Сложность — в ~12 workaround-слоях (Windows mmap, LanceDB self-healing, RLock, multi-window), не в архитектуре. (3) Переписывания нет: db_manager.py (664 стр) уже 80% Gateway — PID-lock:496-584, begin_write:644, close_for_maintenance:242, recreate_table_physical:377, intel_reset_index исправлен (tools_reg.py:139-191). (4) Не ломать: 683 теста, test_index_runner_deadlock, 24 ADR (PID-lock 3-layer defense), граф уже в quality (engine.py:814-817).
**Guard:** Задача 2 = усиление LanceDBManager (PID-lock → database_lock.py + тесты, чистка 5 мёртвых DI-ключей), НЕ новый класс с нуля. Ждёт решения владельца.
**verified_from_clean_state:** ⚠️ не проверено — read-only исследование, кода не менялось; факты Verified по этой сессии (grep+read).

## [2026-08-02 23:10] — INC-6E12: FileGuard в write_tools — fail-open → fail-closed (задача 1/5 «идеального кода»)

**Status:** ✅ Fixed (локально, не запушено; runtime — живой MCP работает с синхронизированным файлом)
**Root Cause:** `_validate_file_in_project` (write_tools.py:93) возвращал None при недоступности indexer'а — fail-open: write-операции (rename/move/safe_delete/replace) разрешались на произвольных путях вне проекта. `is_safe_to_process` (SafePathManager) не вызывался, хотя indexer его использует (indexer.py:762).
**Fix:** fail-closed: indexer недоступен → ошибка «project root unavailable»; добавлен guard `path_manager.is_safe_to_process` (не-ASCII/пробелы/длина >200 → запрет). Все 4 call-site (write_tools.py:187/249/304/350) уже оборачивали path_error — правка одного метода закрыла все. Тесты: TestWriteToolFileGuard (4 шт).
**Guard:** fail-open в любом валидаторе путей запрещён; при недоступности корня — человеческое сообщение с действием («Откройте проект в Zed»).
**verified_from_clean_state:** ⚠️ не проверено — требует ubuntu-раннер; эквивалент: полный pytest 683 passed / 0 failed + новые тесты FileGuard.

## [2026-08-02 22:50] — INC-6C62 «вечная ошибка» реиндекса: физическое пересоздание таблицы LanceDB

**Status:** ✅ Fixed (код+тесты, локально не запушено; runtime-проверка требует Reload Window)
**Root Cause:** drop_table+create_table в LanceDB НЕ удаляет физические файлы, залоченные mmap живого процесса → новая таблица наследует цепочку версий со ссылками на мёртвые фрагменты (*.lance) → финальная optimize падает с 'Not found'. rmtree(ignore_errors=True) в intel_reset_index молча пропускал залоченные файлы → круг замкнут.
**Fix:** LanceDBManager: close_for_maintenance() (close+gc+sleep 0.5) → recreate_table_physical() (rmtree ignore_errors=False + PermissionError→fresh path lancedb_v2_{ts}) → reset_connection(). Все _safe_recreate_table (db_writer/indexer/indexer_table/runner) делегируют manager'у; trigger_reindex(full) и intel_reset_index переведены на физическую очистку; _verify_index_integrity после bulk_write с rewrite. Тест tests/test_lancedb_recreate.py (3 шт).
**Guard:** rmtree только ignore_errors=False; close→gc→sleep перед удалением (Windows mmap); integrity-check до optimize; регрессия test_index_runner_deadlock не тронута (670 passed).
**verified_from_clean_state:** ⚠️ не проверено — требует ubuntu-раннер; эквивалент: полный pytest 670 passed / 0 failed + регрессионный тест INC-6C62.

## [2026-08-02 00:26] — Реиндекс падает: lance 'Not found' (3 подряд) + 2 MCP-процесса + stale table refs

**Status:** 🔴 Open — требуется действие владельца
**Root Cause:** (1) 2 MCP-процесса на одной БД с 23:47:00 (PID 4576 активный + PID 21616 зомби, 156ms CPU, завис при старте) — rmtree/drop блокируются его залоченными файлами → таблица битая с момента старта. (2) db_manager.set_on_recreate_callback не имеет вызывающих → reset_connection() не синхронизирует table-ссылки (Indexer/runner/writer) после drop+create → stale ghost-таблица: 'known_hashes bulk load failed: Dataset at path'.
**Fix:** НЕ исправлен. Путь: закрыть 2-е окно Zed/Reload (убить 21616; §5.16 — kill MCP запрещён агенту) → intel_reset_index заново. Код-фикс (ждёт): привязать db_manager.set_on_recreate_callback → Indexer._sync_table_ref.
**Guard:** перед реиндексом проверять единственность python -m src.main (tasklist); reset_index стирает .codebase_indices/intelligence (инциденты теряются — INC-6C62 восстановлен вручную).
**Счётчики:** 4750→9451→14152 чанков (дубликаты 3 запусков); фейлы: 3 запуска trigger_reindex full / reset_index (~80%, ~194-219s).

## [2026-08-01 23:55] — Contradiction Ledger: флапающий check_commit_exists + push v3.3.11 + верификация чанков

**Status:** ✅ Fixed
**Root Cause:** verify_diary.py check_commit_exists — git cat-file с timeout=5s; при старте MCP (auto-index, embedder, reranker 499MB, Defender scan) git не укладывался в 5s → TimeoutExpired → False → ложные «коммит не найден» (эволюция 22:02: 1 → 22:37: 2 → 23:01/23:47: 3 при том же diary; хеши 48e695b8/8f799dec/95a322d6/ac6e5ba0e/5a522ead/b39ef455 реально существуют — cat-file вручную все True).
**Fix:** scripts/verify_diary.py:331 — timeout 5→30s + одна retry-попытка; синхронизировано в расширение. Ledger после фикса: 37 ✅ / 0 ❌.
**Guard:** retry+30s; при сомнении — `python scripts/verify_diary.py --skip-gate-zero` вручную.
**Также:** push v3.3.11 e2817035..59fe58b0 (FF, origin/main=HEAD); верификация чанков: 4731 chunks / 306 files / 6030 symbols, jobs running=0, search_code семантический OK (векторы не нулевые), runtime blocked 0.0%, embed-fail в логах нет (ONNX fallback на старте — штатный auto-detect, llama.cpp активен).
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh требует ubuntu-раннер; эквивалент: полный pytest (676 passed) + живой MCP: поиск/индекс/счётчики верифицированы в этой сессии.

---

## [2026-08-01] — Pre-commit hook: verify_diary cp1251-краш + SyntaxError в шаблоне git_hooks_installer

**Status:** ✅ Fixed (локально, не запушено)
**Root Cause:** (1) verify_diary.py требовал `## [YYYY-MM-DD HH:MM]` в заголовке, а записи 31.07 имели только дату → не матчились и склеивались с предыдущей записью, таская её символы (ложные 20/20; вскрыла запись 22:50). (2) Hook печатал stdout скриптов с emoji (📊) в cp1251-консоль → UnicodeEncodeError → коммит фейлился по ложной причине. (3) Мой edit после удаления generate_docs из шаблона записал голое `"""` (строка 35) → закрыло внешнюю тройную строку раньше времени → SyntaxError:36 в git_hooks_installer.py.
**Fix:** verify_diary — дата-время опционально `(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)`; negative lookbehind в `_extract_code_functions`/`_check_test_file_exists`; поле `clean_state_reason` (§0.2: «не мог» ≠ «не проверил», такие записи не фейлятся); hook-шаблон — Popen+encoding utf-8+CREATE_NO_WINDOW (§5.16) + `sys.stdout.reconfigure(utf-8)` (§9.9); git_hooks_installer.py — восстановлено `\"\"\"` экранирование в шаблоне (2 места) + убраны 3 dead-ссылки на generate_docs (скрипт никогда не существовал, `git log -- scripts/generate_docs.py` пусто).
**Guard:** `python -m py_compile` + `ast.parse(PRE_COMMIT_HOOK)` + hook прогон (verify_diary 36 ✅/0 ❌ + stale_detector OK, RC 0). Реиндекс после коммита не нужен (изменения только в scripts/).

---

## [2026-08-01 22:50] — HTTP 400 llama.cpp embedder: v1 (HF truncation) ОПРОВЕРГНУТ → v2 (native /tokenize) + полный реиндекс 4677 чанков

**Status:** ✅ Fixed (v3.3.11, локально, не запушено)
**Root Cause:** GGUF multilingual-e5-small: n_ctx_train=512 → llama.cpp капит слот до 512. HF-токенизатор ≠ GGUF-токенизатор (разные BPE): после усечения до 512 HF-токенов llama считает до 526 (замер 20 реальных чанков: макс 502, zh CHANGELOG; в прогоне 22:01 526>512) → HTTP 400 → реиндекс АБОРТИЛСЯ на 4512/4666 («Embedding failed for chunk 8», retry-loop перезапускал → симптом «вечно 4512»). Фикс 48e695b8 (v3.3.10) НЕ работал — запас 0-10 токенов.
**Fix:** remote_embedder.py — подсчёт нативным /tokenize llama-server (лимит 480, запас 32 под спецтокены) + итеративный char-proportional cut (макс 4 итерации); HF-fallback 448 при недоступности /tokenize. Попутно: llama_install.py vulkaninfo → bytes+CREATE_NO_WINDOW (§5.16, был cp1251-краш reader-потока); pylance==9.0.0 в venv расширения + requirements (known_hashes bulk load, §5.19 API проверен to_lance().to_pandas()). Инцидент «умер с клиентом» — реиндекс detached (Start-Process).
**Guard:** /tokenize-гарантия per-input ≤ 480 < 512; тест-мок плотный CJK (1 ток/симв) доказывает сходимость cut; правило: реиндекс только detached; чанки пишутся в Phase 3.
**Reindex:** 22:37→22:47, 4677 chunks, FTS5 built (1901 names, 891 docs), HTTP 400=0, Aborted=0, E2E search_code OK.
**Тесты:** 667 passed, 13 skipped, 91 deselected (slow/benchmark); truncation 10/10 (4 новых MockTransport); shadow_canary+idle_reload+install_embedder_sync 17/17; ruff clean.
**verified_from_clean_state:** ⚠️ не проверено — verify_clean_state.sh требует ubuntu-раннер; эквивалент: полный pytest tests/ (667 passed) + живой реиндекс 4677 чанков (0 errors).

---

## [2026-08-03 22:45] — Ротация дневника §4.8 (июль → docs/archive/AGENT_DIARY_2026_07.md)

**Status:** ✅ Done
**Root Cause:** дневник 861 строка (> лимит 300) — перегрузка контекста.
**Fix:** все записи < 2026-08-01 перенесены в docs/archive/AGENT_DIARY_2026_07.md (заголовок ARCHIVE — см. AGENT_DIARY.md); в живом — август + секция Key Historical Decisions сверху.
**Guard:** §4.8 п.4 — ротация при >300 строк или раз в месяц; §6.5 п.3 — единственность дневника.

---

## [2026-08-03 22:45] — P1: hub codebase — каналы write/index падали ImportError'ом

**Status:** ✅ Fixed
**Root Cause:** codebase_tool.py импортировал несуществующие модули: `symbol_write_tools.SymbolWriteTool` (реальный: `write_tools.WriteTool`) и `index_tools.IndexTool` (такого файла нет в git-истории). `codebase(action="write")`/`(action="index")` → «No module named…»; телеметрия: rename_symbol/replace_symbol errors с 20:52.
**Fix:** `_action_write` → write_tools.WriteTool (убран несуществующий kwarg project_root); `_action_index` — диспетчер по path (status|progress|timeline|health|project_dir|notify) к реальным классам system_tools/indexing_tools; docstring обновлён.
**Guard:** 37 passed (test_write_tools) + 10 passed (health/architecture/index_guard); import OK; ext синхронизирован (cp); live-проверка после Reload Window.
**verified_from_clean_state:** ✅ yes — live-подтверждено на RUN_ID e3f3aabd7186: codebase(action="index", path="status") → 4842 chunks; codebase(action="write", ...) → modification guard + impact_token.


---

## [2026-08-03 23:55] — Сессия: §1.19 Hard Triggers + аудит 29 пунктов + docs sync + commit/push

**Status:** ✅ Done
**Root Cause:** протокол требовал жёстких триггеров (§1.19), аудит audit.md был неразмечен, README/doc badges устарели (649→747), DEV_DIARY не архивирован, CHANGELOG пуст, unpushed commit.
**Fix:** (1) §1.19 Hard Triggers в личный AGENTS.md (5 блокираторов «запрещено без»); (2) 29 вердиктов в experiments/audit.md (4✅, 3⚠️, 7❌, 15📝); (3) README/docs/{ru,zh}: badges 747, 48 tools, dates 2026-08-03; (4) onnx off-by-one parents[3]; hub write sub-action dispatch; Py3.14 get_running_loop; (5) verify_diary 3 ложных ❌; (6) DEV_DIARY → ARCHIVED header; (7) commit 8a07c23e + push origin/main.
**Guard:** pre-commit (verify_diary 25✅/0❌, stale_detector OK); bump_version --check ✅ (3.3.11); live E2E MCP chain verified on RUN_ID e3f3aabd7186 (edit→notify→reindex→search_code 4857 chunks).
**verified_from_clean_state:** ✅ yes — clean clone+venv+install+pytest (747 passed) + live MCP chain verified.

---

## [2026-08-04] — Спринт: 6 пунктов аудита (5 ✅ Fixed, 1 ❌ Refuted) + docs + commit/push

**Status:** ✅ Done (5/6 FIXED, 1/6 REFUTED)
**Root Cause:** 6 ❌ P1/P2 пунктов из experiments/audit.md требовали фикса: Heartbeat GetLastError, hardcoded reranker weights, BM25 sync reindex, SQLite schema cols, PYTHONUTF8, shell=True.
**Fix:** (1) server_factory.py:57-68 SetLastError(0)+GetLastError только при handle==0; (2) settings.py SearchConfig.bm25/dense_weight из env + engine.py:86-89; (3) Item 8 REFUTED — BM25Mixin.reindex() = только инвалидация кэша `_bm25=None` под локом (bm25.py:37-40), блокировки нет; (4) server.py:266-289 PRAGMA table_info для {key,value}/{workspace,data}; (5) zed_config.py:270-273 env[PYTHONUTF8]="1"; (6) install.py _run()→shlex.split+shell=False, step_pip Popen→список, фикс stray `)` (syntax error).
**Guard:** 756 passed, 4 skipped, 0 failed; AST OK на 7 файлах; shlex.split проверен на PowerShell-команде (4 args, скрипт цел); Ledger §0.1.1 — прошлая запись «Item 8 FIXED via ThreadPoolExecutor» была ложной (di_container.py не менялся) — сверять ledger с git status (§9 pitfall 1).
**verified_from_clean_state:** ⚠️ no — pytest полный (756 passed) + AST, но verify_clean_state.sh (clone+venv) не гонялся в этой сессии.

---

