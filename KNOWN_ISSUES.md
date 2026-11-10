# KNOWN ISSUES — MSCodeBase Intelligence

> Синхронизируется из `AGENT_DIARY.md` при каждом [🏁 ИТОГ].
> Формат: дата | что было | статус | fix

---
## 2026-11-11 — `smoke_e2e` шаг 4 требует dense-индекс, дефолт репозитория — текстовый — 🟢

- **Измерено:** `python scripts/smoke_e2e.py --project .` → шаг 4
  `❌ search error: There is no vector column in the data. Please specify the
  vector column name for vector search`; `.mscodebase/` содержит только
  `chunks.db`, потому что индекс собран `scripts/reindex_text_only.py` при
  `MSCODEBASE_DENSE_OFF=true` (дефолт проекта).
- **Не регресс:** шаг не зависит от `_abstains`; `--services-only` проходит
  (`embed dim=768`, `rerank top=1`).
- **Fix:** шаг пробует вектор и при его отсутствии честно падает в текстовый
  индекс SQLite (`chunks_fts`), называя режим в отчёте. Проверка:
  `python scripts/smoke_e2e.py --project .` → `✅ SMOKE E2E: PASSED (проверок: 4)`,
  шаг 4 `режим=text (vector: …); term=…, results=3`.

---
## 2026-11-11 — 4 slow-теста LSP/VFS не проходили на `main` — 🟢

- **Измерено (не наш регресс):** на `origin/main` (`74191a5`) падали
  `tests/test_lsp_vfs_indexing.py::TestLSPVFSIndexing::test_lsp_vfs_content_indexed_without_disk`,
  `…::test_lsp_vfs_content_beats_disk`, `…::test_indexed_at_timestamp`,
  `…::test_hash_based_on_content_not_disk` — все с
  `ValueError: Indexer requires an explicit WorkspaceSource`.
- **Причина:** тесты конструируют `Indexer` без `source=`, а API требует
  explicit `WorkspaceSource`; маркер `slow` исключён `addopts`, поэтому дрейф не
  видел ни pre-commit, ни CI.
- **Fix:** тестовый хелпер передаёт `LocalFsSource(project_path)`; проверка
  `python -m pytest tests/test_lsp_vfs_indexing.py -o addopts="" -q` → `4 passed`.
  Полный прогон с slow: `pytest tests/ -m "not integration and not benchmark"` →
  `2560 passed, 10 skipped`.

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
## 2026-11-09 — RU→EN: перевод сильнее dense; ревью поймало 2 ложных доказательства — 🟢

- **Замер (12 вопросов, 2 репо):** RU-лексика 2/12, слепой EN-перевод 12/12,
  dense 768 8/12, перевод без реранка 12/12 за 14 мс — `ru_vs_dense/REPORT.md`.
- **После ревью:** матчер gold считал тест-файл реализацией (C 9→8); `dense_score
  is not None` всегда истинно → `>0`; negative control был литералом → проверяет
  текст и падает. Guard: `matcher_selftest.py`, `negative_control.py --arm A|C`.
- **Границы:** hard subset = 1/12; старые 4/5 и 5/5 superseded.
- **Gate-долги:** WISDOM test count обновлён (2317 collected). K3 `P-006` был не
  ошибкой реестра, а устаревшим путём гейта: протокол v2 перенёс реестр в
  `agent_docs/pitfalls-registry.md`, а гейт читал старый `skills/...`. Исправлено
  в `tools/knowledge/check_knowledge.py` (оба пути, новый первым; K7 читает таблицу).

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

## 2026-10-25 — E51: frozen-панель проиндексирована (panel leakage) — 🔴 P0
- `experiments/4A_unit_of_return/frozen/f5/queries.md` содержит те же probes и
  находится в `chunks.db`; BM25 возвращает его как top-1 почти на всех запросах.
- **E51b (фильтр `experiments/**`):** single 0.562/0.771; agent 0.438/0.792;
  p50 140 ms; calls 2.0; tokens 1048.
- **Следствие:** все BM25-числа E49/E50/E51 загрязнены; production 0.688 мог
  тоже быть затронут. Нужно исключить frozen-панели из индекса/retrieval и
  перепроверить baseline.
- **Agentic:** детерминированный expansion+graph ухудшает hit@1; для 95% нужен
  LLM-планировщик, а не фиксированная эвристика.

---

## 2026-10-25 — E49/E50: docs-reserve и score-router — zero-sum — 🟡
- **E49:** reserve15 0.250/0.500/0.583 (хуже base 0.271 на 1k); reserve25
  0.208/0.458/0.604; oracle 0.396/0.604/0.729; p50 245 ms.
- **E50:** route@0.8–2.0 = 0.104/0.125/0.167; docs 8/8 при любом пороге;
  code route 0; oracle 0.375/0.583/0.729.
- **Вывод:** docs/code конкурируют за один бюджет; лексический score не
  маршрутизирует. Нужен semantic classifier/agentic loop; статическая map
  даёт потолок ~37–40% на 1k, 95% недостижимо.

---

## 2026-10-25 — E48: two-channel map — docs BM25 сильный, routing ломает — 🟡
- **base** 1k/2k/4k = 0.271/0.458/0.562; **route** 0.292/0.458/0.562;
  **oracle** 0.396/0.625/0.729; p50 323 ms.
- Docs-gold (8): bm25_docs 0.75/1.00/1.00; route 0.125 (2/8).
- **Потолок 1k = 39.6%**, 2k 62.5%, 4k 72.9%; 95% недостижимо.
- **Решение:** всегда docs BM25 (без keyword classifier) + top-docs под
  token-reserve; code 1k улучшать BM25-top-files + PageRank hybrid.

---

## 2026-10-25 — E47: docs в PageRank разбавляют code-граф — 🔴
- **base** (code-only) 1k/2k/4k = 0.271/0.458/0.562; **docs** = 0.042/0.188/0.458;
  **docs_bm25** = 0.042/0.229/0.479; p50 1,113 ms.
- Code-only 1k 32.5% → 5%; docs-only 1k 0 → 37.5% (только BM25).
- **Вывод:** docs не в тот же PageRank; два канала (code PageRank + docs BM25),
  слияние по бюджету; один PageRank на запрос. H1–H7 FAIL.

---

## 2026-10-25 — E46/E46b: PageRank repo map — работает, но не 95% — 🟡
- **Граф:** 9,315 nodes / 47,286 edges / 759 code files (docs нет).
- **E46 personalized:** 1k/2k/4k = 0.271/0.417/0.521; code-only 0.325/0.500/0.625; docs 0.
- **E46b +RU→EN:** 0.271/0.458/0.562; code-only 0.325/0.550/0.675.
- **Вердикт:** PageRank ≫ degree/global, но 95% на 1k недостижимо; docs-gold вне графа.
  Нужны docs-узлы, персонализация RU→EN+symbols, BM25 top-files до PageRank.
- **Артефакты:** `experiments/e46_pagerank_map/`, `e46b_pagerank_ru/`.

---

## 2026-10-25 — E44: agent rewrites — keywords +1 h1; fusion/identifiers хуже — 🟡
- **Плечи:** baseline / keywords / identifiers / agent_all на 48 запросах E30.
- **Результат:** baseline 0.688/0.771, 84 ms; keywords **0.708**/0.771, 78 ms;
  identifiers 0.583/0.750; agent_all 0.688/0.771, 147 ms.
- **Вердикт:** одна чистая формулировка лучше флуда; агентский план должен выбирать primary query,
  а не фьюзить все варианты. **Артефакты:** `experiments/e44_agent_rewrite/`.

---

## 2026-10-25 — E41–E43: chain audit — docs intent, experiments, concept tags — 🟡 open
- **Диагностика:** RRF top5 35/48; 13 misses (8 docs gold, 5 recall).
- **E41:** исключение `experiments/` — 0.688/0.771 → 0.688/0.750, p50 81→43 ms.
- **E42:** intent-aware demote — без изменений; `auto_detect_intent` не распознаёт docs.
- **E43:** concept tags ×0.9 — без изменений; ×1.1 — 0.188/0.250 (precision collapse).
- **Вывод:** нужен точный symbol-level concept layer (аннотации), а не keyword-count boost.
- **Артефакты:** `experiments/e41_no_experiments/`, `e42_intent_demote/`, `e43_concepts/`.

---

## 2026-10-25 — E40: RU→EN синонимы — ноль — 🟡 neutral
- **Плечи:** baseline / ru_synonyms на 48 запросах E30; `synonyms_ru.py`.
- **Результат:** оба 0.688/0.771, p50 159/176 ms. H6 PASS; H1/H2/H3/H4/H5 FAIL.
- **Вердикт:** варианты дают те же top-5; RRF схлопывает дубликаты. Словарь — утилита,
  не рычаг. 95% на панели недостижимо.
- **Артефакты:** `experiments/e40_ru_synonyms/`.

---

