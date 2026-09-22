## Key Historical Decisions

- **search_code timeouts: idle-unloaded embedder + blocking hot-reload (2026-09-22):** `llama_runner` по `EMBEDDER_IDLE_TIMEOUT=120s` сам убивает embedder (free RAM, `_process=None`), но `RemoteEmbedder` его не поднимал → `:8080` мёртв → `WinError 10061` → поштучные ретраи → `search_code` timeout (max ~27s; прод-таймауты 09-20..09-22, эмбеддер падал ~16:21). Вторая причина: `_maybe_hot_reload` ждал полную переиндексацию ВНУТРИ search_code (22 файла → 14s при живом эмбеддере). Fix: `LlamaRunner.ensure_embedder_started()/is_port_up()` + `RemoteEmbedder._revive_llama_cpp()` (revive перед поштучными ретраями) + hot-reload в фон с дедупом (`search_tools._run_hot_reload_bg`). Тесты `tests/test_embedder_idle_recovery.py` (10). Побочно: stale `.pyc` в `git_url` давал фантомные IndexError-падения (лечится очисткой `__pycache__`).
- **Resume-инкрементальная запись IndexProjectRunner (2026-09-20, 0fcb0f33):** run() копил все эмбеддинги и писал одним bulk_write в конце — краш на 330K чанков (~9ч) терял всё. Теперь файл пишется порциями (WRITE_FLUSH_FILES=32) по завершению его чанков, RAM освобождается, restart = resume по known_hashes; `_verify_and_repair_table_integrity()` в начале run() (INC-6C62); `_flat_indices_by_file` (O(1) сбор vecs); fallback per-file сохранён. Тесты test_index_resume_incremental.py (6). Red Team 5/5.
- **Умный ubatch по ролям (2026-09-20):** вместо одного `LLAMA_UBATCH_SIZE=2048` для обеих ролей — `resolve_ubatch(role)`: embed → ceil(480/128)*128=**512**, rerank → ceil(1000/128)*128=**1024**. Основание: A/B на реальных 2227 чанках — ubatch=512 → 596 MB / 18.9 ch/s vs 2048 → 1686 MB / 16.1 ch/s. Раньше llama.cpp требовал «entire input ≤ ubatch» (#25293), для b9940 целый батч делится по слотам, лимит остался на ОДИН текст/пару → клиентский трим: embed обрезает до `LLAMA_EMBED_MAX_TOKENS=480` (единый источник с remote_embedder), rerank — `_truncate_rerank_pair` до `LLAMA_RERANK_MAX_TOKENS=1000`. `LLAMA_UBATCH_SIZE` env — жёсткий override. Файлы: `llama_install.py` (resolve_ubatch), `llama_runner.py` (_ubatch_arg, 3 места запуска), `multi_provider.py` (трим пары), `remote_embedder.py` (импорт лимита), тест `test_ubatch_roles.py`. Live-check: реальный llama-server принял ubatch=512, embeddings 200 dim=384.

- **PyPI-packaging + user-data isolation (2026-08-28):** wheel теперь содержит `tools.stale_detector`, `adapters`, `locales` (норм. данные в site-packages); бинарники/модели в pip-режиме — `get_data_root()` (`%LOCALAPPDATA%\mscodebase`), гейт-маркер `__mscodebase_ext__.marker` отличает расширение от установленного пакета; CLI `--project-path/--project-dir` → env `MSCODEBASE_PROJECT_PATH` (приоритет НАД CWD, trust_self_index); `PROJECT_PATH` остался после CWD (multi-window сохранён). Live-Smoke из чистого venv: tools-ok, `en (78 ключей)`, корень резолвится. Файлы: `pyproject.toml`, `project_resolution.py`, `main.py`, `llama_install.py`. INC-C4CD.

- **Server freeze during full reindex (2026-08-25):** root cause — `begin_write()` держит `_write_lock` (RLock) весь reindex (~7.5 мин embedding), а `IndexStatusReporter.get_status()` синхронно на event-loop-потоке ждал тот же lock (intel_get_runtime_status/require_ready_project/ProjectContext) → заморозка ВСЕХ MCP-вызовов. Фикс: reindex fast-fail в get_status (кэш + status="reindexing") + asyncio.to_thread в 3 loop-точках + guard в _get_stale_warning.
- **Embedder:** multilingual-e5-small-int8 + batch=32 (100 ch/s sustained) — 2026-07-17
- **Concurrency:** AsyncInferQueue → лок (тихая гонка подмены векторов) — 2026-07-18
- **Cache:** Chunk-level content-addressed cache (skip re-embedding) — 2026-07-18
- **Windows:** subprocess.run(capture_output) в daemon-тредах = deadlock; Popen+communicate (§5.16) — 2026-07-18
- **Артефакты:** progress.json вне проекта, системная папка (Задача 4/5) — 2026-08-03
- **Hub & Spoke:** codebase(action) + DEFAULT-allowlist MSCODEBASE_MCP_TOOLS (скрытые инструменты — через hub) — 2026-07-22
- **Защита:** PID-lock + self-healing + auto-index guard (3-layer defense) — 2026-08-02
- **Security:** SQL injection fixes (alias/layer), FileGuard fail-open → fail-closed в write_tools — 2026-07-27/08-02
- **P0 reindex deadlock:** bulk-загрузка known_hashes вне RLock между потоками — 2026-07-31
- **Multi-window:** CWD-first резолв проекта (per-process сигнал вместо глобального SQLite active_workspace_id) — 2026-08-07
- **Type resolution:** query-time LSP через basedpyright (не index-time USES_TYPE) — 2026-08-06/07
- **Edge transparency:** confidence EXTRACTED/INFERRED + evidence в properties рёбер — 2026-08-08
- **Memory retraction (ADR-0002):** status ACTIVE|VERIFIED|REFUTED + `intel_retract_memory_node` (OWP lifecycle VERIFIED→REFUTED, причина обязательна) — 2026-08-11
- **Memory v2 (2026-08-12):** SUPERSEDED-фильтр в retrieval + verify-on-read не переписывает терминальные статусы + ADR-0004 Propagation Engine (каскадная ретракция) + метрика false-retraction
- **Единый PathManager + GC (2026-08-13):** crash-лог → data_root/logs/crash.json (был ~/.mscodebase_crash_log.json); логи MCP → data_root/logs (были ext/.codebase_indices/logs, стирались при переустановке); fallback моделей → data_root/models (был ~/.cache/mscodebase — Linux-путь на Windows); телеметрия скрипта → data_root; ArtifactGC (30д проекты / 90д телеметрия / 7д логи / пустые сразу); autouse-изоляция data_root в тестах (2481 папка мусора)
- **PID-reuse guard llama_runner (2026-08-13):** _InterProcessLock._is_pid_alive — OpenProcess(SYNCHRONIZE) ложно считал завершённый процесс живым (объект жив, пока у родителя handle) → stale PID блокировал запуск reranker весь день; фикс: GetExitCodeProcess==259 + имя llama-server.exe
- **Дедупликация серверов при 2 окнах (2026-08-13):** lock embedder/reranker держится ДО готовности порта (был — до Popen; llama-server bind'ит через секунды → второй MCP спавнил дубль); ONNX _wait_for_server 30→60s (модель 600MB)
- **LIVE-SMOKE (2026-08-13):** scripts/smoke_e2e.py — реальные сервисы без моков (embed llama.cpp / rerank BGE-M3 / векторный поиск по реальному LanceDB); §7 п.10b: для runtime-изменений ✅ = live-check, не только pytest (инцидент: 7 тестов зелёные по неверной причине)
- **Чёрные окна CMD (2026-08-14):** MCP запускался как `venv\Scripts\python.exe` (console-подсистема) → каждое окно Zed = своё чёрное окно; фикс: `pythonw.exe` в extension.toml + CREATE_NO_WINDOW во ВСЕХ runtime subprocess (13 файлов) — с pythonw (нет консоли) незакрытые git/wmic/netstat мигали бы окнами
- **FA=0.00 ≠ качество guardrail (2026-08-15):** Exp 1-L Day 3 — qwen3.6/3.7 (zero-shot VOR) достигают FA=0.00 ценой recall(real)=0.08–0.20 (code_first: 2/25 правды принято, 7/25 активно отвергнуто) — fail-closed политика, а не «фильтрация лжи»; выбор LLM для verify-on-read = выбор политики (fail-closed qwen vs max-coverage glm), recall(real) обязан быть в метриках. CoT (V3/Part 5) НЕ окупается: только qwen3.6 recall 0.08→0.20 при цене ×30–65

## [2026-09-22] E17 v7 — CORRECTION: AST proxies do not predict kill-rate (v6 not replicated)

**Status:** Measured (v6 REFUTED on replication).
**Method:** 24 functions (providers/mcp excluded — their tests await servers and hang under mutation), 55 tests, 4 mutations each; split by FUNCTION; decoys 0/55.
**Result:** v6's rho(exact_compare, kill_rate)=+0.54 p=0.006 did NOT replicate — train rho=+0.13 p=0.54, held-out rho=-0.01 p=0.97; rule `exact_compare>=1` precision 0.59 / recall 0.67. kill_rate spread healthy (mean 0.38; 17 zeros / 5 ones / 33 mid).
**Conclusion:** cheap AST features (assert count / density / specificity / LOC) do NOT predict whether a test catches a behaviour change. v6 was a small-sample artifact (n=24). `TEST_VERIFIES` needs actual mutation runs, not AST proxies. The TESTS *reach* edge and the decoy control (0/139 across v5–v7) stay valid.
**Files:** experiments/bootstrap/e17_strength_scaled.py, e17_strength_scaled.json

## [2026-09-22] E17 v6 — verification-strength profile: specificity beats count

**Status:** Measured (hypothesis CONFIRMED).
**Method:** 10 functions x 4 mutations (negate-if, flip-compare, bool-flip, int+1, str-append) = 40 mutants; every graph-linked test (B) and decoy (D) run under every mutant; AST features extracted from test bodies.
**Result:** 24 tests profiled; decoys killed **0/104** mutants. Predictors of kill-rate (Spearman, n=24): assertion **specificity** (`assert x == v`) rho=+0.54 p=0.006; assert **count** rho=+0.47 p=0.019; density rho=0.25 n.s.; LOC rho=0.14 n.s.
**Conclusion:** what an assertion compares against matters more than how many assertions there are. A TESTS edge is a *reach* claim; mutation kill-rate is a *verification* claim. Build a TEST_VERIFIES / TEST_STRENGTH layer on top of TESTS instead of one fat edge.
**Files:** experiments/bootstrap/e17_strength_profile.py, e17_strength_profile.json

## [2026-09-22] E17 v5 — mutation validation: signal drives verification, 40% assertion gap

**Status:** Measured (hypothesis CONFIRMED, with caveat).
**Method:** strong mutation (negate the first single-line `if`) on 10 panel functions; run the graph-linked tests (B) vs coverage-matched decoy tests (D); restore via `git checkout --` in finally.
**Result:** B killed the mutant 6/10, D 0/10, Fisher exact p=0.011. But 4/10 linked tests did NOT catch the mutation — e.g. `TestCypherLexer::test_tokenize_*` assert only `len(tokens) > 0` / `"MATCH" in values`.
**Conclusion:** TESTS edges identify *verifying* tests far better than decoys, so the signal can enrich verification — but its value is bounded by test *assertion strength*, not coverage. Pair it with an assertion-density / mutation-kill proxy, else ~40% of linked tests give false confidence.
**Files:** experiments/bootstrap/e17_mutation_validate.py, e17_mutation_results.json

## [2026-09-22] E17 pivot v4 — impact task: signal is the only source of truth

**Status:** Measured (hypothesis CONFIRMED, decisive).
**What changed:** task = "which tests cover function F" (impact/coverage); scoring = objective recall/precision of test names vs the signal's own set (no judge).
**Result:** recall A=0.000 B=1.000 D=0.000 (B-A and B-D = +1.000, 30/0/0); precision identical. Name-convention leak: A guessed a real test for 0/30.
**Conclusion:** TESTS-signal is essential for impact/coverage (the info is not in the code, and naming does not leak it), but adds nothing to answer generation / reasoning (v1-v3 ceiling). Value = retrieval / agent workflow, not answer quality.
**Report:** experiments/bootstrap/e17_pilot_report.md

## [2026-09-22] E17 pivot v3 — complex panel, ceiling persists (B even worse)

**Status:** Measured (hypothesis REFUTED again).
**What changed:** panel selected by complexity (branches >= 10; up to 332 loc / 80 branches, `IndexProjectRunner.run`); generation/judge shards packed by line budget (subagent read limit ~2000).
**Result:** accuracy A=4.93 B=4.77 D=4.83 — B-A = -0.167 (p=0.057, d=-0.36, 1 win / 6 losses); completeness/safety flat. Manipulation B 43% vs D 7%.
**Conclusion:** the ceiling is robust across task type and panel difficulty. For answer generation a strong model needs no tests; TESTS-signal value must lie in the agent workflow (which tests to run / impact), not in answer quality.
**Iterations:** v1 explain 5.00/4.97/5.00; v2 edge-case simple 4.87/4.87/4.90; v3 edge-case complex 4.93/4.77/4.83.
**Report:** experiments/bootstrap/e17_pilot_report.md

## [2026-09-22] E17 pivot v2 — edge-case task, blind judge, ceiling persists

**Status:** Measured (hypothesis REFUTED for this task/model).
**What changed:** task = edge-case outcome prediction (signature-aware input: None/""/missing path/-1); judge = blind AND test-hidden (uniform reference for all arms); metrics accuracy/completeness/safety + separate manipulation check.
**Result:** accuracy A=4.87 B=4.87 D=4.90 (p=1.00); completeness/safety flat. Manipulation check: B mentions its tests 57% vs D 10% → tests are read but not needed.
**Key correction:** v1's "completeness B>A p=0.0046" was a judge-context artifact — the judge saw each arm's own tests, inflating B/D. Removing the confound erased the effect. Rule: the judge's reference must be identical across arms.
**Conclusion:** for a strong model, neither paraphrase nor edge-case prediction benefits from TESTS-signal; need tasks where the code is insufficient, or a weaker model.
**Report:** experiments/bootstrap/e17_pilot_report.md

## [2026-09-22] E17 pilot RUN — specificity-selected panel, ceiling on accuracy

**Status:** Measured (hypothesis PARTIAL — pipeline valid, endpoint at ceiling).
**What changed:** panel re-selected by test specificity (min per-test coverage <=5); decoy = unique foreign coverage-matched tests; 90 answers via 10 shard subagents (no repo access); blind judging (opaque tokens). New/rewritten: `e17_pilot_experiment.py`, `e17_extract.py`, `e17_export_prompts.py`, `e17_export_judge.py`, `e17_merge_answers.py`, `e17_stats.py`, `e17_check_decoy.py`, `e17_verify_data.py`.
**Result:** accuracy A=5.00 B=4.97 D=5.00 (p=0.33, d=-0.18, 29/30 ties) — CEILING; completeness same; safety zero-variance. evidence_usage A=1.67 D=2.80 B=4.97 (B>A and B>D p<0.0001, 30/30) — manipulation check PASSED.
**Root Cause of null:** task too easy for the model — code alone suffices; NOT a verdict on the signal.
**Guard:** decoy audit (unique + foreign file + cov match) and verify_data before any run; blind judging with mapping kept out of judge shards.
**Pitfall:** subagent JSON output contained unescaped double quotes → invalid JSON; instruct no `"` inside answer strings.
**Open:** record position order; >=3 judge trials; harder endpoint (edge cases / impact) or weaker generator.
**Report:** experiments/bootstrap/e17_pilot_report.md

## [2026-09-22] E17 pilot — source extraction was broken (Post-Mortem)

**Status:** Fixed (experiments/bootstrap, untracked). Pilot invalidated — not the signal.
**Symptom:** `e17_pilot_answers.json` = 120/120 `Error 500`; live smoke gave `# FUNC NOT FOUND` for every class method.
**Root Cause:** naive `f"def {name}"` substring match vs graph *qualified* names — methods are `Class.method`, tests are `Class::test`. No match → `# FUNC NOT FOUND` / `# Test not found`. Compounded by `C_static` empty 30/30 (C≡A) and TESTS edges being transitive coverage (bootstrap_tests.py:216-244; `_ensure_data_root`=234 tests, 0 direct calls) → B≈D noise.
**Fix:** new `experiments/bootstrap/e17_extract.py` (AST: methods, `Class::test`, recursive `tests/`, offset-drift fallback); `e17_pilot_answers.py` + `e17_pilot_judge.py` refactored onto it; judge fake position-randomization replaced with a real before/after swap. 13 tests (`test_e17_extract.py`, incl. 4 adversarial). Untracked — no hash.
**Guard:** tests assert no `FUNC NOT FOUND` and correct class-qualified resolution; red-team covers duplicate method names, async, comment-only name, nested, syntax error.
**Open:** TESTS edges transitive → function selection by test specificity still required for a valid pilot. v3.5.0 retrieval result (hit@1) is unaffected — it used the graph directly.

## [2026-09-22] v3.5.0 Release — TESTS-signal enabled by default

**Status:** Released (pushed to main, PR #39 merged)
**Changes:**
- TESTS-signal enabled by default (MSCODEBASE_TESTS_SIGNAL default=true)
- PR #39 merged: feat(search): add opt-in TESTS-signal to graph-stage (E17)
- Article review applied: 35-query panel, Red Team 5/5, updated risks
- CHANGELOG.md created (v3.0.0 → v3.5.0)
- Version bump 3.4.0 → 3.5.0
**CI:** Running for v3.5.0 push
**verified_from_clean_state:** ✅ (PR #39 clean-state passed 13m15s)

## [2026-09-22] — Exp E16: переносимость bootstrap trace на чужие проекты (статья CoderLegion)

**Status:** Measured (hypothesis CONFIRMED)
**Hypothesis:** динамический трейс (sys.settrace, `src/core/bootstrap_trace_plugin.py`) воспроизводится на чужих Python-репозиториях без правок плагина; linked% не зависит от «нашего» кода.
**Method:** тот же плагин, `PYTHONPATH=MSCodeBase`, `TRACE_SRC_ROOT=`<проект>, TRACE_OUT в temp, запуск с venv-python целевого проекта из его workdir; анализ — фильтр src-каталогов (без venv/tests).
**Result:** gemma_agent — 2882 теста (2874 pass/3 fail/5 skip, 71.4s), **linked 97.3%** (2805/2882), пустых 77, 4020 unique src-funcs, avg 11.6/median 5, **overhead +17.4%** (71.40 vs 60.82s baseline, та же сессия). commit- — 27 теста, **100% linked**, 33 src-funcs, avg 3.1. Go (codebase-memory-mcp pkg) — pytest даёт 0 тестов (CPython-only), аналог переносим нативно: `go test` 51.0% pkg, `go test -run <1 тест>` 22.2% → per-test карта функций.
**Root Cause (почему linked ВЫШЕ на чужих):** коммит-проекты «чище» (меньше моков/фикстур вне src), наш корпус содержит 176 тестов с fixture/conftest-побочными эффектами; распределение сдвинуто: avg 5-12 против наших 10/fan-out, т.к. горячие хелперы не завязаны на tests/.
**Fix (не прод-код):** эксперимент; прод не менялся. TESTS-рёбра по-прежнему write-only (consumer не построен) — для статьи это факт-ограничение.
**verified_from_clean_state:** ⚠️ не применимо — live pytest на чужих репо с плагином из PYTHONPATH (не install), воспроизводимо командами из EXPERIMENTS_LOG Exp 16.
**Follow-up:** весь линк 97.3% — чистая задачка; связанный% со статикой (L1/L2/L3) на чужом проекте не замерялся — кандидат на продолжение статьи.
## [2026-09-22] — Exp E14: Embedder A/B — EmbeddingGemma 300M vs e5-small (production)

**Status:** Measured (hypothesis CONFIRMED)
**Hypothesis:** gemma 300M (768-dim, ctx 2048) значительно сильнее e5-small (384-dim, ctx 512) на кодовом ретривале при цене 3-4× медленнее на CPU.
**Method:** `experiments/embeddinggemma/bench.py` — прод-конфиг llama-server 1:1 (batch 2048/ubatch 512/threads 10/KV q4_0/pooling mean/raw text/L2), 27 файлов src/ в 81 чанк, 16 русских NL-запросов, cosine hit@1/hit@5/MRR + свипы батча/чанка/MRL + RAM WSS (psapi).
**Result (1 прогон/пресет):** hit@1/MRR file: e5 0.062/0.210; gemma Q8 0.688/0.774; Q4 0.625/0.695; QAT-Q4 0.562/0.653. Скорость ~420-tok чанков: e5 10.1 ch/s (3860 tok/s), gemma Q8 2.4, Q4/QAT 3.4. RAM: 91 vs 176-178MB. MRL: 256-dim сохраняет MRR (0.74 у Q8, 0.71 у Q4), 128-dim проседает на Q4.
**Root Cause (почему e5 слаб):** e5-small max ctx = n_ctx_train 512, клиент режет на 480 (LLAMA_EMBED_MAX_TOKENS); gemma 2048 ctx + 768-dim + сильнее заявленный на MTEB. Качество решает not скорость.
**Fix (не прод-код):** эксперимент, прод не менялся. Смена embedder = полный реиндекс чистого индекса (урок E10) ~32ч на 68M токенов от Q8 при 4× медленности — решение владельца, не авт.
**Plus:** ubatch=512 (прод) ограничивает ЛЮБОЙ вход эмбеддера 512 токенами — gemma в проде не получит 2048 без правки llama_install.py (resolve_ubatch). QAT-Q4 ggml-org НЕ лучше обычного Q4_0 unsloth (0.653 vs 0.695 MRR) — рекламный клэйм не подтвердился.
**verified_from_clean_state:** ⚠️ не применимо — live llama-server бенч, воспроизводится командой bench.py (сервер поднимается сам)
**Follow-up (равные прод-условия, чанки 203 ток., ubatch=512):** e5 23.9 ch/s (4091 tok/s), gemma_q4 7.2 ch/s (1314 tok/s) — gemma в 3.3× медленнее при h1f/MRR 0.562/0.691 против 0.125/0.231. «Пропажа» 18 ch/s (E12) = длина чанка: на 420-ток чанках e5 даёт 10.1 ch/s, на 203 — 23.9; tok/s постоянен.

## [2026-09-20] — Exp E13: текстовый RAG (doc-chunks) vs кодовый baseline (E10/E11)

**Status:** Measured (refuted hypothesis)
**Hypothesis:** doc-chunks (README + docs/en/ + docstrings) retrieve as well as code-chunks via search_with_mode quality.
**Method:** 16 EN doc-queries, live index (18665 rows/1197 files), Hit@1/Hit@5/MRR via direct lookup (no LLM judges).
**Result:** hit@1=12.5% (2/16), hit@5=12.5% (2/16), MRR=0.125. Кодовый baseline: hit@1=0%/20%, hit@5=50%/40%, MRR=0.200.
**Root Cause:** (1) embedder плотнее эмбедлит code-сигнатуры, doc-чанки размыты; (2) индекс bias на код (чанков >> doc); (3) queries без intent_hint="docs" маршрутизируются в code-путь.
**Fix (не код):** добавить intent_detection для doc-queries + поднять weight doc-bucket в soft-weighting.
**Guard:** перед production doc-RAG — intent routing + doc-bucket boost. Без этого текстовый RAG ненадёжен.
**verified_from_clean_state:** ⚠️ не проверено — скрипт использует live-индекс MCP (не чистый клон)

## [2026-09-18] — Фаза 1: Incremental Hot-Reload (FreshnessChecker оживлён + hot-reload + KI-109)
- **Evidence Ladder (2026-08-15, Exp 2-E E1-E3):** форма evidence — переменная; file_content = лучший recall (qwen 0.92), graph = закрытие present-trap ТОЛЬКО у evidence-честных моделей (qwen3.7 FA trap 1→0 ценой recall 0.92→0.76); fail-open (glm-4.7: FA trap 6/6) не лечится ни одной формой — свойство модели. VOR-конвейер: фрагмент файла для recall + графовая проверка субъекта отдельным сигналом; glm-семейство исключить
- **VOR MATCHED/DELIVERED (2026-08-16):** per-node накопительные счётчики matched/delivered в verify_cache.json (ключ node_id — переживают HEAD); starved = виден ≥2 циклов, ни разу не проверен — отличает голодание по бюджету от бага якорей (раунд 2 Тома; «пол Тома» = раунд 1)
- **CONTRADICTION RESOLVED [2026-08-28]:** Агент перезаписал `.agent_task_state.md` чужой задачи (`Port env-access extractor`) при запуске Red Team — нарушение §0.1 (Task State Persistence) + §4.9 (Contradiction Hunting). Исправлено: восстановлен оригинальный `.agent_task_state.md`, Red Team-задача перенесена в `.red_team_state.md`. Root cause: отсутствие проверки содержимого файла перед `write_file`. Guard: перед любым `write_file` на `.agent_task_state.md` — читать первую строку и сверять с ожидаемым заголовком задачи.

---

---

## [2026-09-18] — Фаза 1: Incremental Hot-Reload (FreshnessChecker оживлён + hot-reload + KI-109)

**Status:** Fixed (7 тестов свежести включая concurrency-стресс N=16 + 1748 полный pytest green; ветка вне PR — локально)
**Root Cause:** FreshnessChecker (freshness.py) был мёртв (0 вызовов) и СЛОМАН: `table.to_pandas(columns=)` падает на lancedb 0.34 (решение — `to_lance().to_pandas`), пропускал НОВЫЕ файлы (`if rel not in indexed_hashes: continue` → KI-109), передавал `project_path` вместо rel в `_index_single_file`. Хот-релоад уже существовал (`_index_single_file`), но оставлял дыры: FTS5 (incremental_update_fts5 только добавляет), PropertyGraph (remove_file не вызывался).
**Fix:** (1) schema + `file_mtime_ns`/`file_size` (db_manager/indexer_table/db_writer/process_file/_parse_file_only); (2) FreshnessChecker.verify переписан: stat-first (mtime+size совпали → skip без hash), hash-подтверждение, НОВЫЕ файлы индексируются, debounce + Lock + is_reindexing-гейт; (3) `_index_single_file`: +remove_file +remove_from_fts5 перед переиндексацией; (4) search-хук `_maybe_hot_reload` в search_tools (await to_thread).
**Guard:** Новые служебные колонки схемы — через int_columns миграцию (add_columns + recreate fallback); тест-файл обязан использовать real FileGuard (MagicMock не скипает .lance/_versions — verify падал на manifest) и явный embedding_dim (MagicMock truthy ломает `_target_dim = embedding_dim or 768`).
**verified_from_clean_state:** ⚠️ не проверено — ветка локальная, не запушена (видели только локальный pytest); 7/7 нов (+concurrency-стресс N=16) + 1748 полный pytest green; lsp_vfs_indexing pre-existing broken (тот же mock-баг, CI не ловит — slow).

---

## [2026-09-11] — Burst-rename: fail-closed VOR отзывает 100% при ONE rename-sweep (ответ Statewave на dev.to)

**Status:** Closed (эксперименты, ответ опубликован)
**Root Cause:** VOR (ADR-0003) проверяет ПУТЬ-якоря против текущего HEAD. Rename/move = старый путь отсутствует = SILENT_ABSENCE = отзыв, хотя файл жив. Синтетика (1-C): git mv 30 файлов одним коммитом → 30/30 REFUTED (100%); body-hash carry → 30/30 уцелели. Реальная память (1-B): 24 авто-REFUTED = 13 мусор якорей + 10 настоящих удалений + 1 ЛОЖНЫЙ отзыв (ADR-7232a6e2ba34: узел жив, отозван по старому пути src/utils/paths.py из prose «X → Y» в теле; хранимые якоря adapters/zed/zed_config.py + src/main.py существуют).
**Fix (эксперименты, не код):** burst_rename_audit.py / burst_sweep_exp.py / redteam_burst.py в experiments/1V_memory_contamination/. Решение для производства не принято (вопрос владельцу: body-hash carry-compat против стоимости).
**Guard:** Red-Team показал — «батч по коммиту» (мульти-уёдание = move) смешивает R* с D* (e661861f: init.py удалён + windows.py R083): спасал бы и настоящие удаления. Точный ревью complex: git --diff-filter=R по истории.
**verified_from_clean_state:** ⚠️ не прогонялся (скрипты экспериментов, не runtime-код)

## [2026-09-07] — Lazy-only верификация: VOR вызывается только из intel_get_project_memory, нет TTL/фона

**Status:** Open — зафиксировано как проблема + план эксперимента (10-continuous-verification.md)
**Root Cause:** По дизайну (ADR-0003) VOR ленивый, но точки вызова всего одна (layer.py:1097); IdleScheduler включается только из record_tool_call(), VOR в idle не подключён, 2 из 3 idle-задач — заглушки (_improve_summaries_batch/_check_index_health — пустые тела). Живой срез текущего проекта: 42/136 узлов ACTIVE без verified_at/TTL висят с 2026-08-11; узлы без якорей → INCONCLUSIVE → VOR не пишет ничего → «проверено» = «кто-то когда-то вызвал».
**Fix (план эксперимента, не внесён):** H1 idle-ticker VOR с budget; H2 event-driven на HEAD (ключ hash(node_id+commit_sha) уже есть); H3 TTL-гниение INCONCLUSIVE → STALE. Baseline замера: полный прогон 136 узлов = 431.6ms (fingerprint 371.6ms) — дешевле порога. Контр-риски: false_retraction не выше 0.083%, цена при нагрузке.
**Guard:** новые «проверки» проектной памяти обязаны иметь точку вызова вне ручного чтения (idle/event/ttl) — иначе это снова lazy-by-hand.
**verified_from_clean_state:** ⚠️ не прогонялся (изменения только .md, live-данные из реального сервера PID 10036)

---
## [2026-09-09] — H1: фоновый VOR-проход (IdleScheduler) — память перепроверяется без вызова агента
**Status:** Fixed (6 новых тестов + 1674 полный pytest green; ветка chore/experiments-es1-es2-0909)
**Root Cause:** VOR вызывался ровно из 1 места (intel_get_project_memory, layer.py:1097); idle-задача `_check_index_health` — заглушка → пока агент не дёрнет memory, REFUTED/VERIFIED не копились (Exhibit #23 аудит 2026-09-09; KNOWN_ISSUES 2026-09-07, дедлайн 2026-09-15).
**Fix:** (1) `set_idle_vor_callback()` в task_queue.py + вызов в `_check_index_health` (hook-инъекция: task_queue не импортирует layer → нет cycle-import). (2) `run_background_verify(budget_ms=250)` в layer.py: locked()-guard (Red Team a1 — agent-путь приоритетнее), общий `_write_lock` + `get_verifier`-регистр → idle-VOR и agent-VOR сериализуются в `_persist_transitions` без второй lock/гонки; `_build_symbol_resolver` вынесен из `intel_get_project_memory` (DRY, эквивалентный рефакторинг). (3) Регистрация hook в `server_tools._register_intelligence_tools` после создания `intel_layer` (enable_idle_scheduler вызывается раньше — layer ещё нет). Red Team 3 атаки: lock contention (защищено общим lock+budget), блокировка idle-потока (budget_ms=250 + cooldown 120s), stale hook при перерегистрации (перезапись каждый старт + try/except).
**Guard:** новые точки проверки памяти обязаны использовать существующий lock/verifier-регистр (не создавать второй) — иначе гонка записей project_memory.json.
**verified_from_clean_state:** ⚠️ не проверено — коммит не запушен, clean-state script не прогонялся; полный pytest 1674 passed локально, ruff-ошибка Fix

---
## [2026-09-09] — H2: .h заголовки C включены в AST-индексацию (PARSE_EXTENSIONS + C-парсер)
**Status:** Fixed (commit 0301fa93; KNOWN_ISSUES 2026-09-09 19:35 закрыт)
**Root Cause:** ".h" был в INDEX_EXTENSIONS (вектор-чанкинг шёл), но НЕ в PARSE_EXTENSIONS → CodeParser.parse_file возвращал [], [] (parser.py:438). C-заголовки без AST: нет импортов (#include), вызовов, присваиваний, condition_path. E-S1 live-проба (2026-09-09): curl 65/300 файлов с #include дали 0 рёбер — преимущественно .h; dart-http .c 0/9.
**Fix:** (1) extensions.py PARSE_EXTENSIONS: ".c" → ".c", ".h". (2) parser.py: регистрация `self.parsers[".h"] = <C-парсер>` (tree_sitter_c, не cpp — .h = C). (3) Карты языка по аналогии с ".c": `_EXT_TO_ENV_LANG` {".h": "c"}, IMPORT_NODE_MAP (preproc_include), ASSIGNMENT_NODE_TYPES (init_declarator, assignment_expression), CONDITIONAL_NODE_TYPES (if/for/while/do/switch/case/conditional_expression). (4) +1 тест `test_h_header_preproc_include` (57 passed в файле; full gate-zero через pre-commit). Red Team: прототип-only .h → fallback-line-chunking (не ломается), пустой .h → 0, .hpp остаётся CPP (другая карта не тронута).
**Guard:** интервал "вектор индексируется, AST нет" (INDEX_EXTENSIONS \ PARSE_EXTENSIONS) — проверять BATCH-check'ом при добавлении языка; тест на каждый новый suffix в PARSE_EXTENSIONS.
**verified_from_clean_state:** ⚠️ не проверено — повтор E-S1 live-пробы на curl отложен (требует внешний клон); unit-проверка: CodeParser.parse_file(.h) real tree-sitter → chunks≥1, symbols=[helper]

---
## [2026-09-07] — Cypher-движок: анонимные узлы/рёбра ломали MATCH; ActionReceipt не писался из write-пути
**Status:** Fixed (оба блока закрыты, тесты зелёные)
**Root Cause:** (1) Cypher: `from_node_alias` дефолтил в `n1`, а генератор создавал `n{path_idx*2}` для анонимного узла → `no such column: n0.id`; переменная ребра `[e:]` не регистрировалась → `no such column: e`. (2) Receipts: `_contract_record` (ChangeIntent) вызывался только в rename-fallback и safe_delete; replace/insert/move/workspace_edit писали файл напрямую → ни ChangeIntent, ни ActionReceipt.
**Fix:** (1) cypher_sql.py: alias левого узла резолвится в `n{path_idx*2}`, `edge_vars` + `edge_prop_map` (type/source_id/target_id → колонки, остальное → json_extract), `count(e)` → COUNT(e.id). 10 регресс-тестов + 5 Red Team атак. (2) write_tools.py: новый `_contract_receipt()` (build_receipt + ActionReceiptStore) вызывается из `_contract_record`; сам `_contract_record` добавлен во все write-пути (replace/insert/rename-LSP/move включая refs). Receipt-запись warning-only, не валит write. +1 тест (JSONL создаётся, verdict VERIFIED).
**Guard:** write-операция без ChangeIntent+ActionReceipt = дефект; правило «каждый write пишет оба артефакта». collect() остаётся open (сочтён отдельной записью KNOWN_ISSUES).
**verified_from_clean_state:** ⚠️ не прогонялся (изменения в 2 файлах, pytest tests/ 1629 passed + ruff clean)

---
**Status:** Fixed (branch closed, artifact merged into main)
**Root Cause:** experiment/lab-2026 branch (spike exp-lab-2026-01: NL->LLM->Cypher->parser+schema->PropertyGraph) was orphaned - its artifact experiments/neuro_symbolic_spike.py and EXPERIMENTS_LOG entry never landed on main. Findings C1-C4 were already fixed on main via D1 (CypherExecutor schema layer).
**Fix:** Re-ran spike from clean main (VERDICT: HYPOTHESIS SUPPORTED, parse_ok=8, rejected_by_schema=2 - schema layer correctly rejects hallucinated :SERVICE label and cycle() empty-RETURN). Carried only the useful artifact (spike script + EXPERIMENTS_LOG entry 848fdf33), avoiding a blind merge that would have conflicted in 3 doc files. Deleted orphaned local branch experiment/lab-2026.
**Guard:** When a long-lived experiment branch diverges, carry only the result artifact, never blind-merge doc files that evolved on main.
**verified_from_clean_state:** ✅ yes - spike re-run from clean working tree on main (MockLLM, no network); pre-commit gate-zero green (verify_diary/stale_detector/check_tool_names/negative_controls/check_layer_boundaries).

## [2026-09-02] - PR #20 merged green; issues #21/#22 auto-closed
**Status:** Fixed (merged to main, CI fully green)
**Root Cause:** PR #20 (two-pass symbol resolution) introduced 4 CI failures:
1. git_hooks_installer.py:54 - premature """ closed the PRE_COMMIT_HOOK literal -> 91 invalid-syntax (escaped-quote bug; surrounding escaped quotes are intentional, this one wasn't).
2. graph_resolver.py - 5 F401 unused imports + 1 BLE001 (except Exception).
3. test_graph_adapter_node_selection.py tie-test asserted hardcoded Windows path D:/.../pkg_a/impl.py; adapter normalizes file_path via Path.resolve(), so on Linux CI the value differed -> clean-state job failed.
4. test_modification_guard.py:505 - E731 lambda in class attr (ruff lints src/ AND tests/).
**Fix:** reused escaped quotes; trimmed imports + narrowed except; tie-test asserts chosen.file_path.endswith(pkg_a/impl.py) (platform-stable); lambda->def (4cb1b695, 9659f591).
**Guard:** CI Lint(ruff) runs `ruff check src/ tests/` -> verify BOTH incl. tests, not just src/ (checked src/ only first pass).
**Result:** PR #20 merged; issues #21 (ambiguous writes refuse) & #22 (fail-closed anchors / head-freshness) auto-closed via Fixes footer in commit B (cb88c961).
**verified_from_clean_state:** ✅ yes - CI on head 9659f591: test(ubuntu 3.14) PASS, test(windows 3.14) PASS, clean-state PASS, ruff check src/ tests/ PASS; full pre-commit gate-zero for both fix commits.

## [2026-09-02 20:51] — drift_gate заблокировал коммит: контроль остановил самого автора
**Status:** ? Fixed (коммит A 08281f37 приземлился; B — отдельная незакоммиченная квитанция)
**Root Cause:** предсуществующий BROKEN drift_gate: GitBash bin/ (C:\Program Files\Git\bin) НЕ в PATH процесса > shutil.which("bash") резолвит System32\bash.exe (WSL-шим) > _resolve_bash возвращает None > negative_controls BROKEN. Доказано предсуществование: файлы drift_gate не тронуты в этой сессии (git log), gate был зелёным 2026-08-12 (AGENT_DIARY:723-724) > деградация среды, НЕ вечный UNAVAILABLE.
**Fix:** commit A (08281f37, fixes #21/#22) выполнен процессом с prepend PATH "C:\Program Files\Git\bin;C:\Program Files\Git\usr\bin" > negative_controls все 3 PROVEN, все 5 hook-проверок OK. **--no-verify НЕ использовался** (запрещён): устранена причина (bash в PATH), незаглушена проверка.
**Guard:** паттерн в WISDOM: «hook блокирует > чини среду, не пропуск» (PATH-фикс делает контроль работающим и коммитит ПОД ним; --no-verify оставляет контроль мёртвым).
**Сопутствующее:** пере-стейдж дрейфнувших fail-closed файлов (layer/verify_on_read/test) — стейдж отставал от рабочего дерева после поздних эдитов; пойман повторным git diff --staged (привычка: сверять перед каждым коммитом). Многострочный PS heredoc ломает git commit > использовать -F <файл>.
**verified_from_clean_state:** да (на рабочем дереве = стейдж A): 126 тестов A-зоны passed; hook 5/5 OK; git show --stat 08281f37 = 7 файлов 328+/16-, footer Fixes #21/#22.

---

## [2026-09-02 21:40] — COMMIT B (head-freshness) приземлился: cb88c961; + cp1251 encoding-инцидент
**Status:** ✅ Fixed (коммит B cb88c961; все 5 pre-commit hook'ов OK; рабочее дерево чистое)
**Root Cause 1 (B):** после A (fail-closed symbol, никогда REFUTED) свежесть индекса не проверялась — отсутствие референта не доказывало удаление (stale-индекс). Требование fresh-индекса для честного REFUTED.
**Fix 1 (B):** (1) `evaluate_freshness(build_head,current_head,dirty)` + `resolve_head_dirty(root)` (git rev-parse HEAD + git status --porcelain, Popen+communicate, CREATE_NO_WINDOW, timeout 5s, fail→None) в verify_on_read.py; (2) `index_project` пишет `build_head` в graph meta ТОЛЬКО на успешном completion; (3) freshness-gated `_symbol_resolver` в layer.py — False (REFUTED) только при build_head==HEAD на чистом дереве, иначе None (INCONCLUSIVE); (4) `_classify` снял fail-closed symbol-ветку (резолвер несёт freshness); (5) test_verify_on_read fail-closed-тест → unverifiable-None→INCONCLUSIVE. +8 тестов `tests/test_symbol_freshness.py`.
**Root Cause 2 (encoding):** PowerShell `Set-Content` записал мою русскую запись дневника (эм-даши «—») в cp1251 → AGENT_DIARY.md стал смешанным UTF-8+cp1251 → verify_diary упал (index 0x97). §9 п.9.
**Fix 2 (encoding):** декодировал cp1251-блок (с маркера `## [2026-09-02 20:51]` до EOF) как cp1251, префикс как UTF-8, переписал файл UTF-8 (strict-валиден). Пере-стейджил. verify_diary 5/5 OK. **Урок: никогда не писать русские .md через PS — только edit/write tools (UTF-8) или Python `encoding="utf-8"`.**
**Guard:** WISDOM B-DONE-блок; паттерн §9 «PS cp1251» (запись); чистый-A-прогон (worktree 08281f37): test_verify_on_read 47/47 → A не зависит от B; полный clean-A pytest = 158 среда-fail (embedder/reranker в изолированном worktree), ортогонально B.
**verified_from_clean_state:** ✅ да — полный pytest 1608 passed (hook verify_diary, рабочий B-дерево) / 1602 passed (ручной B-прогон); ruff clean; git show --stat cb88c961 = 10 файлов 343+/42-, создан tests/test_symbol_freshness.py.

## [2026-09-03] — Fake reindex ETA "~8s" + frozen progress in Finalizing (both fixed)
**Status:** ✅ Fixed (commit 32f11662; 5 pre-commit hooks OK; full pytest 1587 passed, 2 pre-existing unrelated env_extractor failures)
**Root Cause 1 (ETA "~8s"):** `_enrich_job_response` had a dead history branch — `job.project_size` is never assigned → always false — and fell into a broken linear extrapolation of the first 2 simulated seconds: `int(2/0.2*0.8)=8` → fake "~8с". History-ETA path (`store.py:249`) was unreachable.
**Fix 1:** single source-of-truth parser `_embed_progress_from_log()` (layer.py) reads the real `[embed] done/total batch=…ch/s` line within the job window → real ETA = `remaining/speed` (verified: 992/1339, inst=16 → ETA 21s, eta_phase="embed"). No data → honest `None` (UI "расчёт…/определяется…") instead of a fabricated number. Reworked `intel_trigger_reindex`/`intel_reset_index` ETA to handle `None` (was a `TypeError` passing None into the stdlib `timedelta` seconds arg).
**Root Cause 2 (frozen Finalizing):** `_safe_ivf_index` (up to ~1min) emitted no progress-callback → bar stuck at 0.8 (embed scale max), chank counter showed stale last-embed line.
**Fix 2:** emit a `finalizing` progress-callback before/after IVF in index_project_runner.py; `_index_progress_callback` maps "finalizing" → 0.8→0.95; `get_job_status` shows honest "⚙️ Finalizing: optimize + IVF index" when done>=total.
**Guard:** 2 new honesty tests in test_job_history.py (ETA None when no data; real rate from mocked `_embed_progress_from_log`). §9: "trust the log speed, never linear-extrapolate simulated early progress".
**verified_from_clean_state:** ⚠️ не проверено — clean-clone verification not run this session; full pytest 1587 passed (2 pre-existing unrelated env_extractor failures), targeted set 51 green.

## [2026-09-03 19:30] — CI RED: circular import layer ↔ tools_reg (architecture_linter)
**Status:** ✅ Fixed (commit f210ed7c; CI all-jobs green on ubuntu+windows)
**Root Cause:** My ETA refactor added `tools_reg → layer` import for `_embed_progress_from_log`, closing an existing `layer → tools_reg` (re-export `register_intelligence_tools`) cycle. `scripts/architecture_linter.py` caught it as `[CIRCULAR]`.
**Fix:** Extracted `_embed_progress_from_log` into neutral `src/core/intelligence/embed_progress.py`. Both layer and tools_reg import from it. Zero cycle, single source of truth preserved.
**Guard:** `architecture_linter.py` is a CI gate — any future circular import will be caught before merge. §9: "before adding a cross-module import, check if the target already imports back."
**verified_from_clean_state:** ✅ да — CI clean-state job (ubuntu clone+venv+install+tests) passed; full pytest 1587 passed (2 pre-existing); ruff clean; architecture_linter all OK.

## [2026-09-04 11:15] — CI RED: ruff lint errors caught only after push (3 commits)
**Status:** ✅ Fixed (commit 986c9be7)
**Root Cause:** Pre-commit hook did not run ruff. CI (`ruff check src/ tests/` in ci.yml) caught F401/W292 only after push, forcing fix-commits. Repeated 3 times (5a771789, b121ab19, 3dd79ba2). Also discovered pre-existing SyntaxError in hook template from bb05d9af (stray `\"\"\"` in PRE_COMMIT_HOOK docstring) — hook never compiled, was installed via MCP after commits pushed so never caught.
**Fix:** Added `scripts/ruff_gate.py` (step 9 in PRE_COMMIT_HOOK, run via `run_script()`). Graceful skip when ruff not installed (advisory). Removed stray `\"\"\"` in template. 3/3 negative control tests passed.
**Guard:** ruff_gate.py now blocks commits locally when ruff finds lint errors. test_ruff_gate.py prevents regression (happy/fail/no-ruff paths). KNOWN_ISSUES.md#2026-09-04-CI-RED-ruff.
**verified_from_clean_state:** ⚠️ не проверено — clean-clone не гонялся; локально подтверждено: ruff clean (3 файла), py_compile hook OK, 3/3 unit tests, hook template .format() verified.

## [2026-09-05 09:15] — Process leak: hung git cat-file leaks git+git.exe+conhost chains (RAM 81%, ~200 procs)
**Status:** ✅ Fixed (code only, не запушено) — verify_diary.py + git_hooks_installer.py
**Root Cause:** `check_commit_exists` (verify_diary.py:361): `proc.communicate(timeout=30)` на таймауте в Python НЕ убивает процесс, `except Exception: pass` глотает TimeoutExpired → Popen утекает навсегда. Git for Windows делает re-exec (git → git.exe), теряя DETACHED_PROCESS → каждый зависший `git cat-file` = 3 вечных процесса (git + git.exe + conhost). Наблюдение: цепочка 9660→24156→24428 жила 6+ часов; триггер — стартовая Contradiction Ledger-проверка (main.py:62, server_factory.py:547) при CPU/Defender contention.
**Fix:** `_kill_git_tree()` — `taskkill /F /T /PID` (снимает re-exec дерево; верифицировано на живой цепочке: исчезли все 3 процесса) + `except subprocess.TimeoutExpired` вокруг communicate в check_commit_exists; тот же kill-tree в run_script (git_hooks_installer.py:93). Новые except — конкретные `(OSError, subprocess.SubprocessError)`, ноль новых ruff-нарушений.
**Guard:** правило §9: communicate(timeout=) на Windows ОБЯЗАН сопровождаться kill на TimeoutExpired (иначе Popen утекает вечно); unit-мок не ловит (мок не бросает TimeoutExpired) — факт подтверждён реальным прогоном (test_contradiction_ledger slow, 2 passed за 10s). Тесты: commit_guard 5 + test_subprocess_windows 2 + ledger slow 2 = 9 passed.
**verified_from_clean_state:** ⚠️ не проверено — clean-clone не гонялся; full local: 9 passed, ruff clean по новым строкам.

## [2026-09-05 12:30] — FIX: stale_detector + predict_change стабильно таймаутили через MCP (-32001): блокирующий sync-код в async-контексте
**Status:** ✅ Fixed (code only, не запушено) — src/mcp/tools/doc_tools.py + predict_tools.py
**Root Cause:** `error_boundary` применяет `asyncio.wait_for(timeout_ms)` вокруг `execute`, но внутри `execute` вызывается **синхронный блокирующий код** (`stale_run` 10-29s, `static_predict`/`ChangePreview` с git-subprocess). На Windows `asyncio.wait_for` НЕ может отменить работающий синхронный блок → event loop заблокирован, клиент (opencode) отваливается по транспортному таймауту `-32001` ДО того, как сервер вернёт ответ.
**Эксперименты (EXPERIMENTS_LOG#2026-09-05):**
1. `stale_run` напрямую: 10.06s (73 файла, 609 дрейфов) — впритык к `timeout_ms=10000`.
2. `asyncio.wait_for(10000ms)` вокруг синхронного `stale_run` → НЕ прервал, вернулся через 24.7s (loop заблокирован).
3. `asyncio.to_thread(stale_run)` + `wait_for` → РЕАЛЬНЫЙ таймаут на 5.0s/10.0s, event loop жив; `wait_for(30000ms)` успевает за 28.96s.
4. `static_predict` из терминала: 0.53s (быстрый!) — таймаут predict_change -32001 из opencode — артефакт транспортной обвязки, не логика.
**Fix:** оба инструмента обернули синхронные блоки в `asyncio.to_thread` (doc_tools.py `_scan_docs`, predict_tools.py `static_predict` + `ChangePreview.run`); таймауты подняты: stale_detector 10s→60s, predict_change 60s→120s. `asyncio.wait_for` теперь реально прерывает операцию при превышении, event loop остаётся живым.
**Guard:** §9: в async-MCP-инструменте синхронные subprocess/filesystem блоки ОБЯЗАНЫ жить в `asyncio.to_thread`, иначе `error_boundary.timeout_ms` иллюзорен. Правило «таймаут без возможности прерывания = фарс».
**verified_from_clean_state:** ⚠️ не проверено — MCP-процесс в Zed не перезапущен (нужен reload окна для применения); прямой вызов `StaleDetectorTool.execute({})` → OK 13.0s (0 дрейфов), `PredictChangeTool.execute({'mode':'static'})` → OK 1.4s (7 files, risk); 62 теста (вкл. subprocess_windows) passed.

## [2026-09-06 21:00] — Починка lock_guard: таймаут 60s ломал весь .locks-протокол

**Status:** ✅ Fixed / **Root Cause:** `scripts/lock_guard.py` `_run` default timeout=60s — любой `git commit` прогоняет pre-commit hook (verify_diary → полный pytest 5-10 мин на Windows), поэтому acquire/release падали с TimeoutExpired, хотя коммит создавался в фоне. Это делало неработоспособным протокол координации параллельных агентов (§10), который мы внедряем (запрос владельца «проверить, что не конфликтуют параллельные агенты»).
**Fix:** timeout 60→900s (+комментарий-обоснование) в `scripts/lock_guard.py`. **Incident:** INC-CD6E. **Guard:** любой новой «быстрой» утилите с git-commit внутри — развязка на время hook'ов; T3-обобщение: `context_tool.py:280`, `git_tools.py:52-99`, `system_tools.py:370/408/446` — кандидаты sync-subprocess в async (не подтверждены замером, KNOWN_ISSUES ⏳). **verified_from_clean_state:** да — полный цикл acquire→status→release on README/lock_guard/probe прошёл под hook'ами; 1608+ tests passed full run; HEAD=origin/main, активных локов нет.

## [2026-09-06 21:30] — sync-subprocess в async-MCP (context_tool, system_tools) — fixed

**Status:** ✅ Fixed (code only) / **Root Cause:** системная проверка после фикса stale/predict: нашлись ещё sync `subprocess.run` внутри async `execute`. `GetContextTool._section_git` (git log через subprocess, 15s) блокировал event loop async `get_context` (timeout_ms=30000); `DualArmHealthCheckTool.execute` держал sync wsl_check + `_run_mutmut_in_wsl` (до 180s WSL) + `_verify_mutmut_can_fail` — wait_for иллюзорен, тот же паттерн P-флага.
**Fix:** `_section_git` → async + `await asyncio.to_thread(subprocess.run, ...)`; вызов в `_collect_sections` → `await`; system_tools: три sync-вызова → `await asyncio.to_thread(...)`. `git_tools._git_run` уже был эталонным async (`create_subprocess_exec` + `wait_for`) — не тронут. **Guard:** §9-правило расширено глобально — любой sync subprocess в async-MCP обязан жить в `asyncio.to_thread` (git_tools — эталон переиспользования). **verified_from_clean_state:** да — test_context_tool 2 passed, ruff clean, imports OK, реальный `_section_git` вернул git-history (2 коммита по config.py). KNOWN_ISSUES синхронизирован (из ⏳ → ✅).

## [2026-09-06 22:00] — P-001 рецидив: cmd-окна при запуске/открытии проекта (powershell/nvidia-smi без CREATE_NO_WINDOW) — FIXED

**Status:** ✅ Fixed / **Root Cause:** повтор инцидента 2026-08-14 (P-001, «чёрные окна CMD»). Фикс 2026-08-14 добавил CREATE_NO_WINDOW для git/netstat/wmic/taskkill в runtime, но ПОЗВОЛИЛ дыру: `resource_monitor.py:303` (powershell Get-CimInstance — RAM-монитор детей) и `:503` (nvidia-smi), `llama_runner.py:1338/1366/1394` (powershell Get-NetTCPConnection, Get-CimInstance CommandLine, taskkill в kill_process_on_port). Под pythonw (no console) каждый такой вызов из фонового сервиса при открытии/запуске проекта создавал видимое окно cmd → «опять появляется cmd и виснет».
**Fix:** CREATE_NO_WINDOW во все 5 сайтов. Guard: `tests/test_subprocess_windows.py` — placeholder (assert True) заменён на реальный статический тест: grep по src/**/*.py за консоль-спавнами (powershell/wsl/wmic/netstat/taskkill/nvidia-smi) без флага → fail; + тест «daemon-потоки без capture_output (pipe-deadlock §5.16)». Оба passed. **verified_from_clean_state:** ✅ да — test_subprocess_windows 2 passed (реальный прогон с диска, не мок): guard находит дыры, ruff clean (все 4 файла), syntax OK.


## [2026-09-08] — B3: grammar-карты parser.py (imports/calls/assigns/conditions) внесены + живые фиксы

**Status:** ✅ Fixed / **Root Cause и итог:** внесены из study 05 карты CALL_NODES/IMPORT_NODE_MAP/ASSIGNMENT_NODE_MAP/CONDITIONAL_NODE_MAP (пер-язычные) в `src/core/indexing/parser.py`. Живые tree-sitter пробы вскрыли недопонимания raw-грамматик, исправлено: CALL_IDENTIFIER_TYPES + simple_identifier (Swift/Kotlin/Dart callee); имя функции + simple_identifier/type_identifier + Dart function_signature и подъём имени из сиблинга function_body (Dart: signature/body — сиблинги, не parent-child); TARGET_NODES + method (Ruby); assignment left + variable_name (PHP $a) и directly_assignable_expression (Swift), right + name-узлы (PHP/Rust); _extract_import_target + regex #include <...>; IMPORT_KEYWORDS + дедуп импортов по (target,line) (Kotlin keyword-дубль, Dart library_import+import_specification); Ruby-imports через call с фильтром require/include.
**Tests:** 94 passed (assignments+calls+imports) > полный прогон 1646 passed. Новые live-тесты: TestMultiLangCalls (7) + TestMultiLangImports (9) в test_symbol_index_call_graph.py, PHP-assign в test_assignments.py. Red Team 5 атак отражены. temp probe-скрипты удалены.
**Guard:** grammar-факты — только через живые tree-sitter пробы (raw grammar_kinds_raw.txt ненадёжен: Go short_var_declaration не перечислен, но существует).
**verified_from_clean_state:** ⚠️ не проверено — чистый clone не гонялся (нет сети в сессии); локально полный pytest 1646 passed / 5 skipped / 91 deselected (Windows).
## [2026-09-08 12:35] — B4: import-экстракция через language_imports (деривация карт + флаг-гейт)

**Status:** ✅ Fixed / **Root Cause:** два источника node-типов импортов (parser.IMPORT_NODE_MAP и литерал LANGUAGE_IMPORT_NODES) расходились (kt/dart/php); ungated fallback-2 в мосте.
**Fix:** LANGUAGE_IMPORT_NODES — производная IMPORT_NODE_MAP (вариант B); fallback-2 только в else-ветке _walk_file (ext без карты) за двойным гейтом MSCODEBASE_LANGUAGE_PACK (else-ветка + is_enabled в iter_import_candidate_nodes); extract_imports_from_file читает флаг через language_pack.is_enabled; дедуп общий. (коммит B4, main)
**Tests:** целевые 103 passed; полный прогон 1651 passed / 5 skipped / 91 deselected (169.2s); ruff clean ×4 файла. Новые: TestMapConsistency (3), TestFallbackImports (4), гейт-тесты флага.
**Guard:** TestMapConsistency структурно ловит любое расхождение карт; ungated-путь закреплён негативными тестами (флаг off → пусто). Lazy-цикл parser⇄language_imports (статика) — осознанный техдолг в _ALLOWED_CORE_CYCLES (KNOWN_ISSUES 2026-09-08), деривация карты переведена на module __getattr__ (PEP 562), на import-time ничего не исполняется.
**verified_from_clean_state:** ⚠️ не проверено — чистый clone требует сети (нет в сессии); локально полный pytest зелёный.

## [2026-09-08 19:40] — collect() в Cypher: json_group_array + типизированный декод (fixed)

**Status:** ✅ Fixed. / **Root Cause:** KNOWN_ISSUES 2026-09-07 ⏳ — `_translate_return_expr` заявлял `collect` как Supported, но SQLite не имеет функции COLLECT («no such function»); ни одного теста на `RETURN collect(...)` не было.
**Fix:** `cypher_sql.py` — COLLECT(expr) → `json_group_array(<sql>) FILTER (WHERE <sql> IS NOT NULL)` (семантика Neo4j: null-игнор, пустой матч → []); `collect(*)` и вложенный obtain → явные ValueError; DISTINCT — SyntaxError из парсера (не наш уровень). Маркер `collect_cols` на трансляторе, в `cypher_executor.py` step5 декодится json.loads ТОЛЬКО помеченных колонок со str-значением (try/except → warning, не роняет весь результат).
**Tests:** 13 новых (SQL/E2E/errors incl. decode-collision `'["not_a_list"]'`); файл 93 passed; полный 1663 passed / 6 skipped / 91 deselected (168.6s). ruff clean, verify_diary 15/0. Эксперименты Г1/Г2 (sqlite 3.50.4, Python 3.14.3) — FILTER и empty→[] подтверждены сырым прогоном, см. .agent_task_state.md.
**Guard:** тест «collect() без алиаса → имя колонки = выражение», decode-collision guard (не-decode не-marked колонок), Red Team 5/5 (empty, null, unicode/quotes, DISTINCT, nested/*).
**verified_from_clean_state:** ⚠️ не проверено — чистый clone требует сети (нет в сессии); локально полный pytest 1663 passed green.

## [2026-09-09] — Аудит «Active MSCodeBase» (Exhibit #23: MCP tool available but never invoked)

**Status:** Open — зафиксирован гэп (исследование + план, код НЕ вносился)
**Root Cause:** фундамент (VOR / DebounceBatch / ConsistencyTracker / IdleScheduler / PropagationEngine) существует, но компоненты изолированы: цепь «файл изменён → STALE → VOR → alert агента» не собрана ни в одном звене. VOR вызывается ровно из 1 места (layer.py:1097, intel_get_project_memory); 2 из 3 idle-задач — пустые заглушки; ConsistencyTracker.mark_stale("memory") never called; system_alerts/precondition contract отсутствуют; FS-event-watcher отсутствует (только heartbeat-Watchdog).
**Fix (план, не внесён):** H1 — подключить VOR в `_check_index_health` (idle-ticker, cooldown 120s уже есть; ~15 строк). Затем optional: mark_stale("memory") в notify_change; system_alerts в ответы MCP-тулов. НЕ добавлять watchdog lib сейчас (notify_change = тот же event).
**Red Team:** (1) lock contention idle-VOR vs agent-VOR — один `_write_lock`, обёрнут asyncio.to_thread, добавить locked()-check; (2) H3 TTL-гниение НЕ применимо к INCONCLUSIVE (42 узла зависнут «навечно») — нужен H1; (3) import cycle — локальный import внутри try/except; (4) alerts токены — низкий риск (одноразовые); (5) concurrent FS при VOR — защищено freshness gate (commit B). 5/5 атак с защитой.
**Guard:** правило §9: перед интеграцией по чужому плану — верифицировать КАЖДЫЙ API через get_symbol_info/search_code (чужой план дал 3 несуществующих API: self.context, vor.run(nodes=), get_active_nodes()).
**verified_from_clean_state:** ⚠️ не прогонялся (изменения только .md; факты из MCP, не из запуска)

## [2026-09-10] — H1 idle-VOR + system_alerts (цепь «файл изменён → STALE → VOR → alert агента» собрана)

**Status:** ✅ Fixed / **Root Cause (Exhibit #23, 2026-09-09):** компоненты цепи существовали по отдельности, но VOR вызывался ровно из 1 места (layer.py:intel_get_project_memory), mark_stale("memory") никогда не вызывался, system_alerts не было.
**Fix (два коммита в ветке chore/experiments-es1-es2-0909):**
- **H1:** `set_idle_vor_callback()` в task_queue.py + вызов из `_check_index_health` (idle-тик, cooldown 120s); `run_background_verify(budget_ms=250)` в layer.py с locked()-guard против agent-VOR (общий `_write_lock`, `get_verifier`-регистр); `_build_symbol_resolver` вынесен из `intel_get_project_memory` (DRY); регистрация hook в `server_tools`.
- **system_alerts:** `AlertStore` (src/core/intelligence/alert_store.py, JSON вне проекта в <data_root>/projects/<hash>/intelligence/, threading.Lock т.к. несколько event-loop'ов, дедуп по kind+payload, атомарный collect_and_clear limit=5). Источники: (a) stale — `mark_stale("memory")` в notify_change ТОЛЬКО при переходе →STALE (не спамим на каждый save; reason меняется и дедуп по payload не спасёт); (b) starved — idle VOR-проход и `intel_get_project_memory` для узлов видимы ≥2 циклов (MATCHED>0, DELIVERED=0). Доставка: `format_system_alerts` prepend в `intel_get_project_memory` (tools_reg) + секция в `intel_explain_project_state` (server_tools, try/except — алерты не роняют диагноз).
**Tests:** 11 в test_alert_store.py (push/collect/clear одноразовость/дедуп/limit/corrupt-json/гонка 2 threading-потоков 20 alerts/per-project изоляция/синглтон по resolved path/orphan) + 3 в test_ui_formatter_memory (empty/alerts render/payload limit 3). Полный pytest 1689 passed / 5 skipped / 91 deselected (180.8s); ruff clean после --fix; architecture_linter «Все инварианты соблюдены».
**Red Team:** (1) дубль-доставка при гонке двух MCP-тулов — collect_and_clear атомарный (первый забрал, второй — пусто); (2) спам на каждый notify_change — alert только при первом переходе →STALE; (3) токен-оверхед — limit=5, payload до 3 ключей; (4) коррапт JSON — graceful reset; (5) multi-window — per-project store. 5/5 с защитой.
**Guard:** дедуп в push + лимиты, single-threaded write под lock. .h-хедеры (H2) — отдельный коммит 0301fa93 (см. KNOWN_ISSUES «`.h` не парсился AST» → Fixed).
**verified_from_clean_state:** ⚠️ не проверено — чистый clone не гонялся (нет сети в сессии); локально полный pytest 1689 passed / 91 deselected (Windows, без e2e/shadow-маркеров — llama недоступен, slow/benchmark отсечены addopts).

## [2026-09-11] — VOR read-path fix (PR #34) + «8-минутный коммит» = НЕ баг (решение владельца)

**Status:** ✅ PR #34 создан, hooks green; скорость тестов — осознанное решение, код НЕ менялся.
**Root Cause:** (1) read-path VOR ре-сканировал prose тела ADR через `_PATH_RE`, хотя явные `data.anchors` уже были захвачены на write-path. Исторические «X → Y» пути из прозы (R083: src/utils/paths.py → adapters/local_fs/windows.py) оживали при rename-sweep и ложно REFUTEDали живой узел ADR-7232a6e2ba34. (2) «Коммит 8 мин» — gate-zero полный pytest ~178s standalone + 2 llama-server (embed+rerank) contention при коммите. Измерено: 1704 passed / 177s; hook-скрипты остальные 8 ≈10s; total ~189s standalone.
**Fix:** (1) `extract_anchors(read_path=True)` в verify_on_read.py — при непустых явных якорях prose НЕ сканируется; legacy-узлы без якорей сохраняют проза-скан (backward compat, дрифт-детект жив). Write-path (layer.py:1250/1555) не тронут (default False). 3 новых regression-теста; 53+28 passed. PR: https://github.com/ManSio/mscodebase-intelligence/pull/34. (2) Владелец: pytest single-thread остаётся, ~178s — норма; xdist/smart-selection НЕ вносить. Зафиксировано в WISDOM.
**Guard:** read-path проверяет ТОЛЬКО якоря, существовавшие на момент записи (не re-derives единственные из прозы); тест `test_read_path_prose_history_legacy_node_keeps_refuting` закрепляет обе ветки. basetemp-гонка (2 параллельных pytest → 452 ложных FileNotFoundError) — известна, не чиним.
**verified_from_clean_state:** ✅ да, локально — PR #34 не merged (ждёт ревью), но: hooks 9/9 OK, полный pytest 1704 passed / 177s, VOR+retraction 53+28 passed.
## [2026-09-10] — Exp 1 (Catch-up Rate) + Exp 3 (HEAD polling): VOR масштабирование и внешний дрифт

**Status:** ✅ Fix (замеры, кода не менялось). **Root Cause (KNOW ISSUES «Lazy-only верификация»):** вопрос, успевает ли VOR проверить ACTIVE-узлы в рамках budget_ms=50 (read-path) / 250 (background idle), и детектит ли он внешнее git-pull изменение без notify_change (H3).

**Команда:** `venv/Scripts/python.exe %TEMP%/opencode/exp1_vor_catchup.py` и `exp3b_head_polling.py` (scratch, изолированные temp-репо/project dirs, бэкапы restore в finally). Венв: `C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence\venv`.

**Сырые результаты (Exp 1, synthetic stale nodes, budgets 50/250ms):**
```
N=200  : 50ms→200/200 (0 exceeded, 36ms) | 250ms→checked=0 (cache-hit артефакт)
N=500  : 50ms→492/500 (8 exceeded)      | 250ms→8 (cache)
N=2000 : 50ms→420/2000 (1580 exceeded)   | 250ms→1580/2000 (0 exceeded, 311ms)
N=5000 : 50ms→457/5000 (4543 exceeded)   | 250ms→1889/5000 (starved=2654, 560ms); catch-up 2 прохода
```
**Вердикт:** H1 CONFIRMED с оговоркой — реальный проект ~247 узлов покрывается за 1 проход (2× бюджет); систематическое голодание (MATCHED>0/DELIVERED=0) начинается при ~5000 узлов. Артефакт: второй прогон при том же HEAD даёт checked=0 — вердикт-кэш persist в verify_cache.json, не баг. → KNOWN_ISSUES «Lazy-only» закрыт полностью, риск бюджета снят.

**Сырые результаты (Exp 3, изолированный temp-репо v1→v2, без notify_change):**
```
run#1: verified=2 → A=VERIFIED B=VERIFIED (якоря foo.py + gone.py живы)
внешн. change: foo.py модифицирован, gone.py удалён, HEAD сменился (v1→v2)
run#2 (fresh verifier): verified=1 refuted=1 cache_hits=0 → A=VERIFIED B=REFUTED
VERDICT H3: CONFIRMED
```
**Вердикт:** H3 CONFIRMED — HEAD-инвалидация per-node cache key (hash(node_id|head)) сама перепроверяет узлы при внешнем git-изменении; OS-watchdog не нужен для коммиченных правок. Открытый интервал: незакоммиченная правка (dirty tree, HEAD прежний) остаётся на fingerprint/mtime + notify_change — до 30s TTL.

**Урок (мера ошибки):** первый прогон exp3 дал ложный REFUTED — статусы читались из memory ДО применения transitions, а не из store после. «Измеритель молча возвращает непроверенное состояние» → читать вердикты только после персист-шага run(). Плюс: вставка новых JSON-объектов `,\r\n`-join'ом сломалла JSON (запятая в начале блока) → переписал корректно, guard-тест `pnpm test tests/lab.test.ts tests/evidence-eval.test.ts` 26/26 прошёл.

**Кросс-триггер (исследование):** веб-поиск показал, что inform-the-agent (alerts/STALE 55.2% на STALE-бенчмарке, PlanFence 30/30 провалов) слабее server-side blocking; кандидат — Fail-Closed Read+Write Gate (SSGM read-filter + PlanFence action-validation). Решение A/B/C — за владельцем.

**Связи:** KNOW ISSUES «Lazy-only» (закрыт), ADR-0003, EXPERIMENTS_LOG (exp 1 и exp 3), MSPortfolio exp-33/exp-34 (26/26 тестов), README badge d8dcbd9f (unpushed).

## [2026-09-10] — Exp 2 (Agent Behavior) + Exp 4 (Fail-Closed Freshness Gate)

**Status:** ✅ Fixed. **Root Cause (Exhibit #23, 2026-09-09):** inform-the-agent approach insufficient — agent can ignore STALE alerts; PlanFence 30/30 failures confirms action-validation unreliable; server-side blocking required.

**Exp 2 (s1 sandbox):** H1 delivery CONFIRMED, H2 enforcement REFUTED, H3 subagent REFUTED (opencode Task tool = isolated context). Key insight: **trust = false security**. Server-side gate is primary enforcement.

**Exp 4 implementation (4 files):**
- **Read gate (layer.py):** intel_get_project_memory: STALE + full VOR pass → mark_consistent("memory"); incomplete → blocked + stale_unverified on unverified nodes
- **Write gate (layer.py):** intel_add_memory_node: STALE → refuse with instruction to call intel_get_project_memory
- **Dirty fix (verify_on_read.py):** fingerprint rebuilds every dirty pass (never cached); verdict cache bypassed during dirty; dirty cache key = sha256(node_id|head|1)
- **Config (settings.py):** MemoryConfig.freshness_gate via field(default_factory=...) for testability

**Tests:** 9 new (test_freshness_gate.py); 1713 passed full suite; ruff clean ×5 files. ConsistencyTracker singleton leak fixed via conftest.py autouse reset.

**Red Team:** 5/5 attacks with defense (dirty-cache-persistence, stale-verified-flood, config-reload, non-git-dirty, consistency-singleton-leak). 

**Guard:** dataclass default=os.getenv() evaluated at import time — use field(default_factory=...) for monkeypatch. ConsistencyTracker singleton requires autouse reset in conftest.py.

**verified_from_clean_state:** ⚠️ не проверено — чистый clone требует сети (нет в сессии); локально полный pytest 1713 passed green.

## [2026-09-11] — H3 TTL-гниение: last_checked для всех проверенных + label stale_ttl (doc 10 closed)

**Status:** Fixed (9 новых тестов + 1725 полный pytest green; doc 10-continuous-verification H1+H2+H3 done)
**Root Cause:** INCONCLUSIVE/непроверенные узлы «висят вечно» без следа проверки: live-срез 2026-09-11 — 70 ACTIVE без verified_at (KNOWN_ISSUES «42» устарел), verified_at VERIFIED median 22/max 31; VOR писал дату ТОЛЬКО при VERIFIED-переходе, INCONCLUSIVE — ничего.
**Fix:** (1) `verify_on_read.py`: `last_checked` пишется для КАЖДОГО реально проверенного узла (cache-hit и fresh check, включая INCONCLUSIVE), физ-запись rate-limited `VOR_LAST_CHECKED_INTERVAL_SEC=6h` (H1 idle не переписывает project_memory.json каждый тик); `stale_ttl_nodes` в stats — ACTIVE/VERIFIED, не проверен в проходе, след старше `VOR_TTL_DAYS=30`; без следа (новый узел) → НЕ stale. (2) layer.py: `verification="stale_ttl"` прямым присваиванием (сильнее budget_exceeded, как stale_unverified). (3) ui_formatter.py: render + ресипт (`⏳ stale_ttl: N узлов не подтверждались > N дней`, lazy-import TTL). (4) Тесты tests/test_verify_on_read_ttl.py — 9 кейсов.
**Guard:** узел не переписывается в терминальный статус меткой (Red Team a2: INCONCLUSIVE неотзываем, false_retraction 0.0968% цел); порог N измерен, не угадан.
**verified_from_clean_state:** ✅ да — CI run 34737070903 на 7429daad: clean-state PASS, full-suite PASS (ubuntu+windows), ruff/layer/linter/pip-audit PASS, transport-equiv PASS, manifest-parity PASS; локально полный pytest 1725 passed, 5 skipped.
**Связи:** doc 10-continuous-verification.md (closed), KNOWN_ISSUES «Lazy-only» (2026-09-07, закрыт), EXPERIMENTS_LOG Exp 5 (2026-09-11).

## [2026-09-13] — H4: agent-memory lifecycle в масштабе dev.to KB — бутылочное горлышко = сетевой capture, не граф

**Status:** Fixed (эксперимент подтверждён; сопровождение задачи closed)
**Root Cause:** при росте базы 3,989 → 13,519 статей (3.4x), refresh own занял 10м38с на 13.5k статей/82.5k комментов (134 сетевых вызова dev.to API). Гипотеза «бутылочное горлышко — локальная пересборка графа» ОПРОВЕРГНУТА измерением.
**Fix:** (а) локальный граф НЕ bottleneck: rebuild_derived собрал 50,498 тред-объектов за ~3с (snapshot 17). Узкое место — сетевая фаза capture (rate-limited dev.to API за 10м38с). (б) Точность: comment_status live=2,030 / gone=80,494 (97.5% хранимых комментов отсутствуют против live dev.to) — read-путь verify-on-read на частично свежем графе пропускает реальные обновления до следующего capture. Верифицированные узлы точность сохраняют.
**Guard:** snack: не оптимизировать сборку графа (уже 50k/3с); улучшение = инкрементальный/осознанный refresh + метрика свежести снапшота по «gone»-доле. exp-37 записан в portfolio lab.
**verified_from_clean_state:** ⚠️ N/A — эксперимент на живой dev.to базе (community-memory MCP), код mscodebase не менялся; portfolio guard-тесты 26/26 green локально.
**Связи:** exp-37 (portfolio lab, EN/RU конгруэнтны), EXPERIMENTS_LOG Exp 6 (2026-09-13), KNOWN_ISSUES H4, community-memory snapshots 16-17.

## [2026-09-15] - Bootstrap Pipeline: Exp 7/38 — test->function linking static vs dynamic (KNOWN_ISSUES FEATURE, iter-точка)

**Status:** Fixed (эксперимент закрыт: CONFIRMED partial; реализация НЕ начата — зафиксирована задача, iter-точка по решению владельца)
**Root Cause:** Для шага 3 конвейера (тесты как ground truth) статическое связывание бесполезно: имя теста↔функция = 0% (выборка 109 тестов, 0 hits), импорты дают только файловый уровень (127/163 = 77.9%). Нужен динамический запуск.
**Fix/Exp:** pytest-плагин `experiments/bootstrap/dynamic_trace_plugin.py` (sys.settrace внутри pytest_runtest_call, фильтр src-функций по SRC_ROOT). Полный прогон 1727 тестов: 1551 (89.8%) исполняют ≥1 src-функцию; 1212 уникальных; avg 10.1 (median 6, 1-118); точное имя-попадание в dynamic-выборке 2.7%; 176 тестов (10.2%) не исполняют src (моки). A/B та же сессия: no-trace 174.8s vs trace 198.6s → +13.6%. Побочно: @mcp_app.tool (22) в src НЕ эмитится как DECORATES-ребро; dataclass=46 чистых, pydantic/TypedDict=0, Table( — шум 90%; шаг 4 (intel_auto_collect_adrs) уже работает.
**Guard:** link-эвристика должна ранжироваться импортами файла/класса (не именем теста); plugin не должен влиять на результат (1725 passed/5 skipped как baseline).
**verified_from_clean_state:** ⚠️ не делал — эксперимент требует установленного пакета + работающих llama-серверов; портфолио guard 26/26 green (exp-38 EN/RU, chart, links=exp-37).
**Артефакты:** experiments/bootstrap/dynamic_trace_plugin.py + trace_result.json; EXPERIMENTS_LOG Exp 7; KNOWN_ISSUES 2026-09-15 [FEATURE] Bootstrap Pipeline; exp-38 portfolio lab.

## [2026-09-15] - Bootstrap Pipeline: веб-исследование слабых мест (расширение записи FEATURE)

**Status:** Open (бэклог дополнен выводами; код не начат)
**Root Cause/Проблема:** Владелец запросил по протоколу исследовать «где использовали в других проектах/реализации, проблемы и решения — максимально выявить гиблые места» перед реализацией.
**Findings (5):** (1) **sysmon+dynamic_context — гипотеза опровергнута эмпирически**: на Python 3.14.3 + coverage 7.14.1 `core=sysmon` даёт верные контексты вида `<файл>.<функция>` (TODO «unused» в sysmon.py:201-204 устарел); контексты не пишутся только при ручном switch_context вне pytest. (2) Нужен повторный A/B замер sysmon-подхода против наших +13.6% sys.settrace. (3) Precision — главное гиблое место: TCTracer (MAP 85/92) использует Tarantula-ранжирование (часто данным тестом/редко другими) + ensemble — достижимо из trace_result.json без мутаций; LLM-трейсебилити F1~79-80% страдает от naming false-positives. (4) Mutation testing как оракул дорог/хрупок (эквивалентные мутанты неразрешимы, флаки +5-10% score, масштаб Google 33M/400k) — годен только для валидации выборки. (5) pytest-testmon (1012★) подтверждает реализуемость через coverage, но цели другие (test selection, line-level), наш TESTS-edge для LLM-контекста остаётся самостоятельной ценностью.
**Guard:** перед реализацией — решить: coverage.py dynamic_context как штатный драйвер (минус самописный sys.settrace) + Tarantula-ранжирование в кандидатах.
**verified_from_clean_state:** ⚠️ не проверено — исследование внешних источников + инспекция установленного coverage (вендор C:\Python314), а не код-пробег; эмпирика контекстов — во временной папке, вне репозитория.
**Связи:** KNOWN_ISSUES 2026-09-15 [FEATURE] Bootstrap Pipeline (дополнен), EXPERIMENTS_LOG Exp 7.

## [2026-09-15] Bootstrap Pipeline: Exp 7b Tarantula ranking + dev.to cross-check (C-шаг плана C→A→B)

**Status:** опровергнуто как recall-метрика, подтверждено как precision-аннотация.

**Exp 7b (C-шаг):** Tarantula-ранжирование на trace_result.json (1212 уникальных src-символа, 1551 тест с трассой). Ванильный Tarantula: 76.9% тестов имеют唯一 best-кандидат по аргминимуму, НО rank≤3 только 22.6% (дальше от 60-70% плана). Фильтрация «глобального шума» (cutoff по числу тестов) не помогает — specific<=3 стабильно ~16%. Ручная валидация 5 примеров: precision на низких рангах 100% (все rank1-3 = верные цели). Файловый уровень ещё хуже (1.8%). Причина: safe_mkdir/get_data_root/project_hash = autouse-фикстуры, 200+ вызовов each.

**dev.to cross-check:** Две статьи подтверждают нашу архитектуру и слабые места: (1) TRUE Coverage (Dawson 2026) — независимо: все статические подходы провалились, per-test coverage → file→tests, shared utilities = основной шум (43→4 min CI); (2) Empirical Failure Modes (adevbelgium 2026) — Pass-Through Mirage = наш phantom code, sys.monitoring = тот же бэкенд что core=sysmon. Ниша TESTS-ребра для LLM-контекста незанята (оба project используют для selection, не для графа).

**Implication для плана C→A→B:** Шаг A (core pytest plugin + TESTS-edges) proceed без изменений — TESTS-ребро ground truth из трассы, ранжирование = bonus-аннотация для ~16% тестов. Tarantula не блокирует A, но замерит только partial confidence.

**verified_from_clean_state:** ⚠️ не проверено — аналитические скрипты (experiments/bootstrap/tarantula_*.py) на существующем trace_result.json, не код-пробег.

**Связи:** KNOWN_ISSUES 2026-09-15 [FEATURE] Bootstrap Pipeline (пункты 3+6 дополнены), EXPERIMENTS_LOG Exp 7b.

## [2026-09-16] Bootstrap Pipeline: Exp 8 — sysmon overhead REFUTED, остаёмся на sys.settrace (A1-шаг)

**Status:** гипотеза опровергнута (overhead sysmon +19.96% > sys.settrace +13.6%)
**Exp 8 (A1):** Полный A/B в методике Exp 7 (warmup + 2 чередующиеся пары, min): baseline 184.88s vs coverage run 221.78s → **+19.96%**. Цель <5% (KNOWN_ISSUES:249) не достигнута. Качество контекстов при этом отличное: 1548/1549 непустых, 75.5% src-строк привязаны к тестам (`test_action_receipt.test_...`, `TestCypherAccess.test_decorates_queryable`), пустой контекст — только import-time строки (24.5%).
**Решение:** шаг 3 `mscodebase bootstrap` строим на `dynamic_trace_plugin.py` (sys.settrace, +13.6%), coverage.py не берём как драйвер. coverage остаётся валидационным оракулом для выборок (A/B cross-check на сэмплах).
**Root Cause/Guard:** заявка «sysmon ≈3-7%» из прошлого исследования не подтвердилась на полном наборе — исправлена в KNOWN_ISSUES:249. Замечено: корневой `.coveragerc` раньше не читался (`configs_read: pyproject.toml`) — потому что файла не было; после создания конфиг подхватывается верно.
**verified_from_clean_state:** ⚠️ не проверено — замер в рабочем дереве (`python experiments/bootstrap/a1_sysmon_ab.py`), не git clone; методология та же, что Exp 7.
**Связи:** KNOWN_ISSUES 2026-09-15 [FEATURE] (пункт 2 обновлён verdict'ом Exp 8), EXPERIMENTS_LOG Exp 8. PR #35 MERGED + CI SUCCESS (закрыт).

## [2026-09-16] Bootstrap Pipeline: A2 реализован — TESTS-рёбра из trace_result.json в PropertyGraph

**Status:** Implemented (src/core/bootstrap_tests.py + 6 unit-тестов; live-прогон на реальной БД)
**Атрибутика вывода:** для тестов индексатор даёт 6.2% узлов (160/1727, label=Function), TESTS-рёбер 0; функции в графе матчатся на 95.9% (15029/15669). Значит bootstrap ДОЛЖЕН создавать Test-узлы.
**Fix:** `build_tests_edges(trace, project_root, graph_db)`: (1) Test-узел — `get_node` (reuse, label не перетирается — add_node с ON CONFLICT перезаписал бы Function→Test) иначе `add_node(label=NodeLabel.TEST)`; qname-конвенция та же, что у индексатора `{project}.{abs_posix}.{name}` (project=D: для abs-пути). (2) src-функции из `func@rel_path` — матч по file_path + суффикс имени (метод в графе `Class.method`, co_name голый). (3) `add_edge(TESTS, weight=1, properties={trace:dynamic_trace})` идемпотентен (UPSERT source/target/type). Live: **1595 Test-узлов создано**, 132 reused, 14985/15669 src-функций (95.7%), **16172 уникальных рёбер TESTS**; пропуски 684 = `<lambda>`/`<genexpr>` (не имеют узлов). Red Team 5/5: границы (пустой trace→skip), дубли имён (рёбра ко всем матчам file), перезапись label (get_node-первый), повторы (UPSERT), параметры (`[param]`→имя без скобок).
**Guard:** (1) никогда `add_node` до `get_node` для тестов — label-перезапись; (2) Test-узлы не трогают индексаторные Function-узлы тестов. Осталось: команда `mscodebase bootstrap`, DECORATES (Шаг 2), CI-гейт TESTS.
**verified_from_clean_state:** ⚠️ не проверено — live-прогон на рабочей БД (`experiments/bootstrap/a2_live_smoke.py`), не git clone; unit-прогон 6/6, полный pytest 1731 passed, ruff clean.
**Связи:** KNOWN_ISSUES 2026-09-15 [FEATURE] (пункт «Прогресс Step A» добавлен), tests/test_bootstrap_tests.py, experiments/bootstrap/a2_*.py.

## [2026-09-16] Bootstrap Pipeline: Exp 9 — static score vs dynamic ground truth (Шаг B пересмотрен)

**Status:** Experiment (verdict PARTIALLY REFUTED в положительную сторону); решение по Шагу B уточнено фактами
**Exp 9:** `python experiments/bootstrap/static_vs_dynamic.py` (v2, per-test; v1 file-level был методологически неверен — завышал L1 hit вызовами соседних тестов). против trace_result.json (1727 тестов): L1 (прямые вызовы из тела теста) hit 88.4% / recall 30.3% / **precision 68.0%** (avg 2.9 кандидата); L2 (токены имени) 17.7% / 3.8% / 12.1% (слабый — подтверждает Exp 7 «имя=0%»); L3 (импорты) 91.6% / 72.0% / 21.8% (avg 41.4); union 90.4% / 70.0% / 20.6%. Fallback для динамически-пустых: 88/176 мок-тестов имеют стат. кандидатов.
**Вывод (Root Cause/Guard):** динамика остаётся драйвером TESTS-ребра (recall 100% на linked); статика ≠ замена (hit≠recall: union recall 70% < 100%); L1 — точный и узкий якорь (tier-1 для ранжирования), L3 — широкий кандидат-пул, L2 — игнор. **Шаг 2 (DECORATES @mcp_app.tool) — ЗАКРЫТ фактом:** живая БД уже содержит рёбра mcp.tool→14, mcp_app.tool→20 (источник `19378296`). KNOWN_ISSUES:245 «tool-рёбер нет» устарел. Остаётся: Шаг 1 как companion-слой (L1+L3 fallback для мок-тестов и pre-filter ранжирования) и Шаг 3 (`mscodebase bootstrap`).
**verified_from_clean_state:** ⚠️ не проверено — аналитический скрипт на неизменяемом ground truth (`trace_result.json`), не git clone; воспроизводимо одной командой.
**Связи:** KNOWN_ISSUES [FEATURE] (Прогресс Step A → добавлен блок Exp 9), EXPERIMENTS_LOG Exp 9, experiments/bootstrap/static_vs_dynamic.py, exp-41 portfolio lab (pending).

## [2026-09-17] Bootstrap Pipeline: Шаг 1 (Data structures) реализован — детектор сущностей

**Status:** Implemented (src/core/bootstrap_entities.py + 8 unit-тестов)
**Задача:** найти чистые data structures нового проекта через AST-сигналы `@dataclass`/`NamedTuple`, НЕ регекс — последний даёт 90% шума `Table(` (это вызовы `db.open_table(...)`, LanceDB), а AST-детектор по классам их априори не видит.
**Fix:** `detect_entities(project_root, src_dir, ignore_dirs)` — обход src/*.py через `ast.parse`, детект декоратора dataclass в 3 формах (Name/Call/Attribute, покрывает `@dataclass` со скобками и `@dataclasses.dataclass`) + базы NamedTuple (Name/Attribute). Счётчик `open_table_calls` — подтверждение, что регекс-шум не становится сущностями. Read-only, идемпотентно, без shared state (concurrency-safe). Ограничения документированы: импорт-алиасы (`NamedTuple as NT`) и pydantic/TypedDict не резолвятся.
**Live-проверка:** `/b1_compare.py` — детектор 49 vs живая БД 46 dataclass Class-узлов; разница ровно 3 = наши bootstrap-классы (EntityShape/EntitiesBootstrapStats/TestsBootstrapStats), потерь 0 (46 из графа покрыты полностью), NamedTuple 0. Расхождение — не баг детектора, а не-переиндексированные новые файлы.
**Red Team 5/5:** формы декоратора (Name/Call/Attribute), SQL-классы с именем Table (не попадут — нет сигнала), алиасы импортов (документированный non-target), битые файлы (SyntaxError→errors[], не падает), пустой src_dir (пустой stats).
**Guard:** (1) любой «детектор сущностей» в дальнейшем обязан использовать AST, не регекс по `Table(`; (2) порог «46 чисто» теперь воспроизводим скриптом, а не из памяти.
**verified_from_clean_state:** ⚠️ не проверено — unit 8/8 + bootstrap-тесты 14/14 в рабочем дереве, live-сверка на рабочей БД; полный pytest не гонял (targeted прогон затрагиваемых модулей).
**Связи:** KNOWN_ISSUES [FEATURE] (блок «Шаг 1 реализован» добавлен), tests/test_bootstrap_entities.py, experiments/bootstrap/b1_*.py.

## [2026-09-17] Bootstrap Pipeline: внешняя валидация на чужих Python-проектах (anti-sleeveness)

**Status:** Implemented (параметризация dynamic_trace_plugin.py) + валидация на внешних репо
**Контекст:** ревизия всех 18 репо в D:\Project (субагент): кандидаты «чистого» кода — gemma_agent (1102 py, 464 test_*.py, git), 456789/ARCLUX (TS), bench_projects (black/httpbin/headroom). Цель — не быть слепым: детектор и TESTS-рёбра проверялись только на собственном репо.
**Find Units:** bootstrap_entities.detect_entities на чужих: black(src)=16 dataclass/2 NT/73 classes, gemma_agent/core=65 dc/228 classes, gemma_agent/modules=1 dc, httpbin=0 (старый код без dataclass). Обнаружена слепота: детектор жёстко завязан на src/ (gemma_agent использует core/, libraries/, modules/ → нужен явный src_dir).
**Fix:** dynamic_trace_plugin.py параметризован: TRACE_SRC_ROOT/TRACE_OUT (env, дефолт=свой repo). Иначе чужой проект нельзя трассировать.
**Трассировка чужих:** black → НЕ работает: скомпилированный .pyd wheel, settrace не видит нативные кадры (0% всех тестов). gemma_agent (2882 теста) → 2737/2882 (95.0%) тестов имеют ≥1 src-функцию, 3827 уникальных src-функций, ~11.6 функций/тест — подтверждает обобщаемость A2 TESTS-рёбер на чужих проектах.
**не забыть (KNOWN_ISSUES):** плагин не ловит .pyd-модули (скомпилированный wheel) — для бинарных проектов (black, некоторые пакеты) нужен другой механизм (это ограничение settrace, документальное).
**verified_from_clean_state:** ⚠️ не прогонялся (изменение research-плагина experiments/, не runtime-код; тест trace_result.json дефолтный путь не менялся).
**Комит:** параметризация плагина 11 insertions.

## [2026-09-17] Web-исследование: тест→код маппинги (для «не быть слепым»)

**Status:** Research (открытая нить)
**Find Units (verified по websearch 2026-09-17):** covtracer (R-пакет, cran) — tra-функция covr::record_tests — маппинг тест→трасса (аналог нашей TESTS-идеи в R); CoverUp (LLM-генерация тестов с измерением покрытия); TELPA (LLM+coverage). НИКТО из них не строит граф-ребро TEST→код для LLM-контекста — наша ниша подтверждается.
**Не изучено:** dev.to-поиск, CoverUp подробно.
**не забыть:** фишка (не эксперимент) → портфолио-синк не требуется для этого коммита.

## [2026-09-17] Bootstrap Entities: устранён хардкод src/ — автоматическое определение корня исходников

**Status:** Implemented (src/core/bootstrap_entities.py + 6 новых тестов)
**Problem:** детектор сущностей жёстко завязан на project_root/src (строка SRC_DIR_NAME="src"), а реальные раскладки чужого кода иные (gemma_agent→core/, httpbin→имя-проекта) — требовался ручной src_dir.
**Fix:** `resolve_src_root(project_root, src_dir=None)` — детерминированный приоритет: (1) явный src_dir, (2) env MSCODEBASE_BOOTSTRAP_SRC_DIR, (3) известные раскладки src/lib/python/packages/app/core/libraries/modules (первый с .py), (4) каталог с именем проекта (httpbin-стиль), (5) статистический fallback — top-level каталог с максимумом .py, ИСКЛЮЧАЯ tests/docs/scripts/venv/etc._NON_SRC_DIRS (иначе tests/ с большим числом .py — ложный выбор). stats.src_root — новый факт, куда реально ходили. RED TEAM 3/3: venv+tests(10+5 .py) не захватываются статистикой; битый env → fallback на автодетект; относительный src_dir резолвится от корня.
**Валидация (live, реальные проекты):** MSCodeBase→src (49 dc), gemma_agent→core (65 dc, ранее ручной src_dir!), black→src (16 dc), httpbin→httpbin (0 dc). Совпадение 1:1 со старыми ручными прогонами.
**Guard:** (1) _NON_SRC_DIRS как отдельный список от _IGNORED_DIRS — статистика не выберет tests/; (2) тесты 14/14, включая статистический fallback с docs/tests-ловушкой.
**verified_from_clean_state:** ⚠️ не прогонялся (логика конфиг-резолва, не runtime-сервис; полный pytest в verify_diary-gate ниже).
**Связки:** KNOWN_ISSUES [FEATURE] (блок «РЕШЕНО auto-src-root»), tests/test_bootstrap_entities.py (14 тестов), src/core/bootstrap_entities.py.

## [2026-09-18] Bootstrap Pipeline Шаг 3: команда bootstrap_pipeline (dynamic trace → TESTS-рёбра) — MCP + CLI

**Status:** Implemented (src/core/bootstrap_pipeline.py + bootstrap_tool.py + bootstrap_trace_plugin.py)
**Problem:** Шаг 3 фичи «bootstrap» (заноминирован в KNOWN_ISSUES как «команда mscodebase bootstrap») отсутствовал — плагин лежал в experiments/, no единой точки запуска ни для агента (MCP), ни для скрипта.
**Fix:** `git mv experiments/bootstrap/dynamic_trace_plugin.py src/core/bootstrap_trace_plugin.py`; новый `run_bootstrap_pipeline(...)` (resolve_src_root → detect_entities → pytest subprocess с плагином → index_src_functions → build_tests_edges), `BootstrapPipelineStats()` JSON; MCP-тул `bootstrap_pipeline` (asyncio.to_thread, multi-window резолв project_root) + CLI allowlist.
**Подводные камни (2 инцидента):**
1. **Namespace shadowing пакета `src`:** PYTHONPATH=корень репо убивал `src/`-layout трассируемого проекта (test `from src.mathz import add` → ModuleNotFound). Guard: PYTHONPATH добавляем subprocess-у ТОЛЬКО по авто-детекту `_plugin_importable()` с тем же cwd=project_root (не « вычислять из cwd процесса» — первый вариант давал ложно-True и pytest падал с невидимым плагином). Тест-проекты используют `sys.path.insert(parents[1]/'src')` + bare import.
2. **BOM:** PowerShell/Блокнот пишут BOM (U+FEFF) → SyntaxError в ast.parse. Guard: чтение .py через `utf-8-sig`.
3. **Чистый граф:** build_tests_edges матчит trace по Function/METHOD-узлам; на пустом графе рёбра не строились. Guard: `index_src_functions()` статически поднимает узлы из AST (Class.method-конвенция, суффиксный матч).
**RED TEAM:** класс/метод/функция раздельно; методы не дублируются как FUNCTION; BOM-файл читается; идемпотентность через ON CONFLICT UPSERT.
**verified_from_clean_state:** ⚠️ не прогонялся (полный pytest 1753 passed — verify_diary-gate ниже; live-check CLI на мини-проекте: entities=1, tests=1 (100% linked), TESTS-edges=1, 672ms).
**Связки:** KNOWN_ISSUES [FEATURE] (блок «Шаг 3 РЕАЛИЗОВАН 2026-09-18»), tests/test_bootstrap_pipeline.py (5 интеграционных), tests/test_bootstrap_tests.py (+3 на index_src_functions), src/core/bootstrap_pipeline.py, src/mcp/tools/bootstrap_tool.py.

## [2026-09-19] Прод-инцидент миграций lanceDB (silent ImportError + destructive rebuild) + Exp E10 REFUTED

**Status:** Fixed (миграции) + Research closed (E10 REFUTED, откачено)
**Problem:** во время E10-исследования поиска индексировали свежую БД, когда миграция колонок молча не срабатывала, и вылезли ДВА реальных бага (эмуляция HEAD подтвердила, это не мусор):
1. `db_manager` импортировал `_migrate_text_full_inplace` / `_migrate_add_metadata_columns` как module-level функции (`from src.core.indexing.indexer_table import _migrate_text_full_inplace`), а они — методы класса `IndexerTableMixin` (DEFINED_IN indexer_table.py:17,66,94) → ImportError → миграция НЕ выполнялась, схема разъезжалась с кодом.
2. `db_writer.is_table_missing` трактовал `"in table schema"` (schema-mismatch) как «таблица отсутствует» → ПОЛНЫЙ rebuild (drop + re-embed ~13 мин) вместо soft-миграции при каждой смене схемы.
**Fix:** локальные `_migrate_text_full_inplace(table)` / `_migrate_add_metadata_columns(existing_fields, table)` с `pa.field(name, field.type)` из `self.schema`; `is_table_missing` исключает `"in table schema"` — recreate только при реальном отсутствии таблицы. +200 строк регрессионных тестов (`tests/test_lancedb_recreate.py`): миграция legacy→file_mtime_ns/file_size, идемпотентность, «НЕ пересоздавать при schema-mismatch». test_lancedb_recreate 12 passed; фокус-группа 43 passed.
**Exp E10 (затрачено ~2ч, результат отрицательный):** E10a full-text-эмбеддинг + e5-префиксы (llama.cpp-ветке их не хватало — ONNX/OpenVINO имели _ensure_prefix) + пул 50. Чистый прогон 599 файлов / 9514 чанков за 799.9s: fast hit@1=0% hit@5=50%; quality hit@1=20% hit@5=40%; baseline автора 0/50% и 30/30% → **REFUTED (N=10, шум)**. Изменённый код откален к HEAD; выжил только нейтральный env-тумблер `MAX_RERANKER_INPUT` (default 30).
**RED TEAM (атака на решение «оставить E10 под флагом»):** переключение требует полного реиндекса (~13 мин) ради нуля → впустую; флаг «50» может незаметно поднять latency хитов; откат = безопасный «поведение клиента = HEAD» (единственный diff settings — env-гейт default 30, тумблер нейтрален).
**verified_from_clean_state:** ⚠️ не прогонялся (ветка → PR; полный pytest 1753 passed — verify_diary-gate при коммите).
**Next:** AST/Graph-hybrid re-ranking (graph_query scope_id + text-match) вместо эмбеддинговых твиков; live-check полного реиндекса на прод-БД после миграции (запрос владельцу).
**Связки:** KNOWN_ISSUES 2026-09-19 (2 записи), EXPERIMENTS_LOG Exp E10, tests/test_lancedb_recreate.py, scripts/e2e_quality_search.py, experiments/search_quality/E10_full_text_embed.py, exp-43 portfolio lab.
## [2026-09-19] Exp E11 (Graph-hybrid re-ranking): CONFIRMED-сигнал — подъём graph-хитов +40% hit@5

**Status:** Research closed (E11 CONFIRMED, прод-интеграция — вопрос владельцу)
**Exp E11 (read-only зонд + руки, ~40 мин):** baseline quality (live embed/rerank, та же сессия) hit@1=2/10 hit@5=2/10 MRR=0.200. Руки поверх тех же top-k: A-prepend (graph-файлы в топ) hit@5=4/10 MRR=0.253; B-RRF 3/10 MRR=0.225; C-graph 4/10 MRR=0.253 (2 стабильных прогона). Спаслись #7 project_indexer_registry и #8 indexing_tools (оба target подтверждены в graph_files, шум остаётся). graph-lookup 6ms vs baseline 1978ms.
**Root Cause (почему растёт):** embedding/BM25 теряют детерминированные кодовые идентификаторы (file_mtime_ns, notify, bm25); SymbolIndex знает их точно, но engine._graph_stage триггерится только на чистый identifier-токен — NL-запросы его не проходят.
**RED TEAM:** (1) шум в graph-файлах (multi_rag_ablation и т.п.) — MRR растёт слабо, hit@1 ровно, потому нужна фильтрация (def-first / min use-count) перед продом; (2) N=10 — уровень шума: сигнал, не доказательство — расширенная панель 30+ обязательна; (3) переключение ниши: прод-стадия за флагом, поведение клиента = HEAD при off.
**Паттерн:** P-recurring «симметричный поисковый путь» — search_symbols уже есть, но недоиспользуется: одна точка инжекции (engine.hybrid_search_async post-fusion) может дать +2 хита за 6ms.
**verified_from_clean_state:** не требуется (эксперимент read-only, src/ не тронут; portfolio 26/26 passed).
**Next:** кандидат в прод — стадия «извлечь символы из NL → search_symbols → top-k подъём (A-prepend)» за флагом; решение владельца + расширенная панель перед фиксацией кода.
**Связки:** EXPERIMENTS_LOG Exp E11, experiments/search_quality/E11_graph_hybrid_probe.py + E11_graph_hybrid_arms.py, exp-44 portfolio lab; E10 REFUTED (2026-09-19) — точка отсчёта.

---

## [2026-09-20] Resume-��������������� ������ � IndexProjectRunner.run (330K-�������� ������)

**Status:** Fixed (6 ����� resume-������ + ������ pytest 1774 passed; �� ����������� � ��� �������)
**Root Cause:** run() ����� ��� ���������� � _all_embeddings (330K x 1024d x 4B ? 1.3GB) � ����� ����� bulk_write � Phase 3. ���� �� ������� ������� ����� ��� ������: ������� ����� > known_hashes ���� > ������ ����-embed ��� �����������. index_guard.py:123: ������ ������� > needs_reindex > ������ �����.
**Fix:** (1) _verify_and_repair_table_integrity() � ������ run() �� known_hashes (INC-6C62 integrity �� skip-�������; ���� ��� �� ������); (2) Phase 2+3 �����: ���� ���������� (��� ����� �������������) > prepare_records > _pending_prepared > bulk_write �������� �� WRITE_FLUSH_FILES=32; ����� ������ _all_embeddings/_parsed_list ���������� + gc.collect (RAM-����); (3) ������� vecs �������� (������������� _flat_chunks) � ������ ������ ������ ���������; (4) _flat_indices_by_file � O(1) ���� vecs, �� O(N?); (5) fallback per-file write ��� db_writer=None ��������.
**Guard:** 6 ����� ������ (tests/test_index_resume_incremental.py): ������� �������, ����������������� (bulk_calls>=4), ���� ��������� ���������� (>=32), resume ������� ���������� (<=68), no double-write, RAM-������������ ����� spy �� ������. Red Team: 5 ���� ��������� (concurrency/idempotent, ������� ���� / BATCH_SIZE, TOCTOU crash ����� bulk_write, ��������� run, integrity-recreate ����� skip � ������� ������ check).
**verified_from_clean_state:** ?? �� ���������� (uncommitted; ������ pytest 1774 passed/5 skipped). Live-smoke �� ���������� (embedder fallback � CI-���������) � resume-��������� ��������� �� �������� ��������, �������� ������ ?1000 ������ �� ����-�� � ��������� ���.
**Next:** ������ (2 ������ pending: ubatch-resolve + resume) �� ������� ���������; live-���ume �� ������� �������; KNOWN_ISSUES: ��� �� ������ flush (10K ������ = 10K ���-����� �� 330K ������) � rate-limit ��� debug.


## [2026-09-20] — Поисковое качество / E13: исследовательские задачи (6 пунктов)

**Status:** Plan (задачи занесены в ISSUE.md KI-R1..R6, код не тронут)
**Контекст:** исследование поиска/RAG — что именно измерять, прежде чем утверждать результат.
**Решение (приоритет):** KI-R1 (перезапуск exp-5 + gold_chunk_id) → KI-R2 (два прогона E13) → остальное.
**Пункты:**
1. KI-R1 (P1): fix measurement — exp-5 restart после KI-101, gold_chunk_id Recall@5, наборы 10→16+.
2. KI-R2 (P1): E13 до нормы — intent_hint=docs + doc-only индекс, два дешёвых прогона.
3. KI-R3 (P2): интерфейс «найдено N / использовано M» + eligible_seen.
4. KI-R4 (P2): регрессионный тест дедупликации (MMR vs финальный sort, SCT/SCT Inst).
5. KI-R5 (P2): гибрид — фильтр лексической ветки вместо RRF (threshold по чанкам/терминам).
6. KI-R6 (P2): housekeeping — 7 копий exp-29 на Lab, дубли в архиве дневника, README числа.
7. KI-R7 (P2): авто-замер — gold_chunk_id из индекса → Recall@5 в get_health_report.
8. KI-R8 (P2): дедупликация по хешу, оба пути в цитате.
9. KI-R9 (P2): не подбирать один режим — vector+BM25 снизил recall у нас, hybrid проиграл vector у автора.
10. KI-R10 (P2): слабый запрос → не молчать, fallback grep (exp-26).
11. KI-R11 (P2, первым): «найдено N / использовано M» + «проиндексировано ли».
**verified_from_clean_state:** ⚠️ не проверено — записи в ISSUE.md/AGENT_DIARY.md, код не менялся.


## [2026-09-22] E17 — TESTS-consumer в graph-stage (контроль/лечение A/B)

**Status:** Verified (реальный Searcher на live графе; 102 pytest green + live-smoke)
**Root Cause:** не было — фича: включённые покрывающие тесты в выдачу symbol-поиска.
**Fix:** флаг SearchConfig.tests_signal (env MSCODEBASE_TESTS_SIGNAL, off по умолчанию);
Searcher._append_tests_signal() — incoming TESTS-рёбра (get_tests_for_symbol), sentinel
chunk_index -(20_000_000+line), graph_score=0.4 (ниже функций 1.0). E17 шаг 1 (consumer).
**Guard:** +7 юнит-тестов tests/test_graph_stage_e4.py (флаг off/on, def-first, get_tests_*).
**A/B.** off vs on на 7 golden-функциях: hit@1/MRR = 1.0 оба; новые тесты в 6/7; overhead не
выделяется (3.37 vs 3.21ms). Re-traкция: 0 битых ссылок.
**verified_from_clean_state:** нет (uncommitted; pytest 102 green local).
**Шаг 3 (закрыт):** флаг оставлен off по умолчанию (экспериментальный тумблер, паттерн late_enrichment) — прод не меняется. Воспроизводимый A/B-скрипт перенесён в experiments/bootstrap/e17_ab_tests_signal.py (stable: hit@1=7/7, MRR=1.0, 6/7, 0 битых). Описана статья-draft docs/blog/bootstrap-pipeline.md (+ строка в docs/blog/README.md). Портфолио синхронизировано: exp-46 EN+RU, guard pnpm test 26/26 passed. Ruff clean. 102 pytest green.
**Статья (draft, полная история, английский):** docs/blog/bootstrap-pipeline.md — полная история на английском (отредактированная версия владельца): Exp 7→7b→8→9→16→E17. **Критические данные добавлены:** широкая панель 35 запросов (hit@1=94.3%, TESTS-signal=97.1%, overhead +15.3%), языковое покрытие (Python 34.0%, Other/TypeScript 0%), red team 5/5 атак отражено. **Вывод:** TESTS-сигнал не улучшает hit@1 (off=on), только добавляет контекст для LLM. Раздел «What Could Go Wrong»: 12 рисков. Experiment Matrix обновлена. Воспроизводимо: e17_wide_panel.py, e17_redteam.py, e17_ab_tests_signal.py. Verified: pytest 34 green, ruff clean. Проверка: PR нужен для clean-state и prod-решения.
**Next:** owner: панель 30+ запросов с embedder → решение прод-включения → PR (для verified_from_clean_state).
