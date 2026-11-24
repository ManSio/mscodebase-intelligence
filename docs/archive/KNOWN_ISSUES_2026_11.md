# KNOWN_ISSUES — архив 2026-11

> Закрытые записи, перенесённые из `KNOWN_ISSUES.md` по гейту (≤300 строк).
> Формат записей не меняется; ссылки на них — по дате и заголовку.

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
## 2026-11-08 (позже) — четыре «открытых пункта» закрыты, найден дефект frozen-gold — 🟢

Продолжение записи ниже: по каждому пункту — внешний источник, атака, замер.

- **callers был спор о gold, а не о инструменте.** LSP `textDocument/references`
  включает ссылки внутри файла определения (`includeDeclaration` по умолчанию
  true). Создан `frozen/gold_external_v2.json` (правило до прогона); v1 не правился.
  Вместе с двумя настоящими дефектами — grep обрезал совпадения по `limit` в порядке
  обхода, и вес grep 0.3 для reference-вопросов — rank-1 стал **3/3** против 0/3.
- **`exact: 0` больше не печатает соседей** (+ `include_neighbours=true`). Отказ
  включается только при завершённом канале и неизвестном графу символе, иначе
  fail-open. 4/4 негативные задачи → 0 строк; 3 позитивных — без изменений.
- **Ложные определения:** узлы-места-вызова в графе без `kind`; предпочитаются
  `*_definition`. 54/60 → **60/60** типизированных первых хитов.
- **Зомби-потоки:** cooperative cancel через `threading.Event` каждые 16 файлов;
  отменённый скан не публикует счётчик (это нашёл red team: `0` от неполного
  скана включал отказ и прятал реальный ответ).
- **Red Team 5/5** (`experiments/xerj_2026_11/red_team.py`): границы, конкурентность,
  отказ зависимости, тихий успех, TOCTOU.
- **`check_gold.py`** нашёл невалидную задачу: E1/P03 спрашивает про
  `ModificationGuard`, которого в `src/` нет (класс — только в тесте). Задача
  заморожена по ожиданию (§19.17). Frozen не правился, P03 помечен INVALID,
  счёт пересчитан без неё: A=0.696 / B=0.652 (n=23); positive 0.667 = 0.667.

Открыто: два профиля весов по интенту (definition vs exploratory); «who raises»
фильтруется эвристикой по тексту строки, а не по типу AST-узла; отмена
проверяется раз в 16 файлов.

---
## 2026-11-08 (позже) — профили весов: второй проверен и удалён — 🟢

Гипотезы H7–H10 заморожены до прогона (`frozen/HYPOTHESES_PROFILES.md`), прогон
`run_profiles.py` на 36 задачах двух корпусов, сырьё `profiles.json`.

- `def_first` (с идентификатором): top10 **0.875**, rank-1 **0.656**.
- `exploratory`: 0.750 / 0.344 — строго хуже.
- Без идентификатора: **0.250 / 0.000 у обоих** — профили там не различаются
  (различались 30 задач из 36, но без идентификатора только 1 из 4).
- H7 CONFIRMED, H8 и H9 **REFUTED** (ожидаемо), H10 корректно проверить не удалось:
  единственная изменившаяся негативная задача оказалась невалидной.

Решение: `exploratory` удалён из кода; остались `def_first` и `references` по
интенту. Guard: `test_profiles_are_two_and_intent_driven`.

Найдено по ходу: **N03** помечен негативом, но его вопрос не содержит отсутствующего
токена (он только в колонке «Токен») — контроль измерял `Corpus`/`Hub`, которые
существуют. `check_gold.py` теперь требует токен негатива **в вопросе**.
С E1 без двух невалидных строк (P03, N03): n=22, A=0.682, B=0.682.

---
## 2026-11-08 (позже) — от чего зависит качество поиска: кривые на 70 запросах — 🟡

`experiments/xerj_2026_11/run_curve.py` (сырьё `curves.json`): 70 запросов, 3
проекта (5 / 15 / 523 файла), RU и EN, с идентификатором и без.

```
has_id=True   n=32  recall@1 0.250 → @5 0.625 → @10 0.688 → @20 0.875
has_id=False  n=8   recall@1..@20 = 0.000   (gold отсутствует и в top-40)
itsdangerous  n=12  @10 0.917 | iniconfig n=6 @10 0.667 | ours n=22 @10 0.318
RU vs EN: rank-1 0.150 vs 0.250, к k=5 выравнивается (0.550)
```

**Корень:** `hybrid_search_async` отдаёт только `source='sqlite_fts5'` — это BM25
без векторов (`MSCODEBASE_DENSE_OFF=true` — штатный режим). Поэтому у вопроса без
идентификатора нет канала «по смыслу».

**Отрицательный результат (не повторять):** кириллический keyword-канал со
6-символьным стемом для запросов без идентификатора дал **1 из 8** на no-id
задачах, а слово «переин» встречается в **98 файлах** из 523 — это шум. Канал
убран из кода; идея зафиксирована, чтобы её не строили заново.

**Открыто (решение владельца):** включать ли dense-эмбеддинги — это модель в
памяти + переиндексация 7 103 чанков. Из отдельного процесса dense не проверить:
`RemoteEmbedder.is_ready() == False`, модель живёт внутри процесса хоста.

---
## 2026-11-08 (позже) — dense-режим: размерность модели не совпадает со схемой — 🟡

Проверка «закроет ли dense no-id класс» (REPORT.md §10, `probe_dense.py`).

- llama.cpp-сервер эмбеддингов жив (`127.0.0.1:8080`), модель `embeddinggemma-2`,
  размерность ответа — **768** (проверено прямым `/v1/embeddings`).
- Векторная таблица (LanceDB) — **384**: `.env` содержит
  `EMBEDDING_MODEL=embeddinggemma-2` при `MSCODEBASE_DENSE_OFF=true`, а размерность
  в схеме осталась от прежней модели (e5-small).
- Полный dense-прогон печатает `query dim(768) doesn't match the column vector
  dim(384)` и продолжает работать частично — то есть переключение
  `DENSE_OFF=false` без переиндексации даёт не «dense», а наполовину сломанный поиск.

На маленьком англоязычном корпусе dense не дал выигрыша над BM25 (5/5 против 5/5,
ранги 2/5/1/9/9 против 6/2/3/9/1) — значит включать dense «потому что лучше» пока
нельзя; сначала размерность, потом замер на нашем корпусе.

**Fix:** `embedding_dimension` брать из ответа сервера (или из модели), затем
переиндексация; после — тот же `run_curve.py` в dense-режиме.


---
## 2026-10-25 — README rewritten; RU/ZH synchronized — 🟢
- Root `README.md`, `docs/ru/README.md`, `docs/zh/README.md` now describe the
  Phase 3 text-first runtime (SQLite/FTS5 + PropertyGraph, optional providers),
  measured quality with methodology, limitations and bug-report protocol.
- Old claims removed: LanceDB/vector as default, 65 visible tools, inconsistent
  test counts, 95% quality implication.
- Historical architecture/search docs carry a Phase 3 status banner; they are
  not silently presented as current.

---

## 2026-10-25 — E57: auto docs routing by BM25 margin (no LLM) — 🟢
- `docs_max - code_max > 4.0` -> docs channel, else code.
- same-basename **0.688 → 0.792**, docs 5/8, **0 code false positives**;
  code hit@1 0.825 unchanged; exact 0.708; p50 ~100 ms extra.
- **Реализовано:** `MSCODEBASE_DOCS_MARGIN` (4.0), `Searcher.prefers_docs()`,
  auto-ветка в `SearchCodeTool` при пустом `intent`; tests 27 pass.
- Gold canonicalization (`docs/ru/X` for `docs/en/X`) всё ещё искажает exact.

---

## 2026-10-25 — E45: structured agent plan — +1 h1, p50 72 ms — 🟢 worth API
- **План:** primary + must_include + symbols, один запрос, без multi-query RRF.
- **Результат:** baseline 0.688/0.771/79ms; plan_must **0.708**/0.771/71ms; plan_full 0.708/0.771/72ms.
- **Вердикт:** один primary + must_include — маленький реальный выигрыш; symbols не дают.
  Внедрить как опциональные поля `search_code` + tool `plan_search`. 95% не закрывает.
- **Артефакты:** `experiments/e45_agent_plan/`.

---

## 2026-10-25 — E39: Qwen3-Reranker-0.6B — 29–55 s, хуже — 🔴 rejected
- **Пилот:** 16 запросов E30; demote vs Qwen3 top10/top20 на corrected index.
- **Результат:** demote 0.625/0.688, 116 ms; Qwen3 top10 0.500/0.562, 28.9 s;
  top20 0.438/0.562, 54.8 s. H1–H6 FAIL.
- **Вердикт:** не usable на CPU; качество ниже deterministic. Reranking не рычаг.
  Deterministic 0.688/0.771/84 ms — потолок на этой панели.
- **Артефакты:** `experiments/e39_qwen3_rerank/`.

---

## 2026-10-25 — E38: BGE-reranker-base — хуже deterministic — 🔴 rejected
- **Плечи:** demote / bge_base_top10 / top20 на 48 запросах E30 (corrected index).
- **Результат:** demote 0.688/0.771, 84 ms; BGE-base top10 0.625/0.708, 3139 ms;
  top20 0.583/0.688, 6028 ms. H7 PASS (лучше MiniLM); остальные FAIL.
- **Вердикт:** generic cross-encoder out-of-domain для кода. Детерминированный pipeline 0.688/0.771/84 ms.
  Reranking не рычаг; только Qwen3-Reranker-0.6B как пилот.
- **Артефакты:** `experiments/e38_code_aware_rerank/`.

---

## 2026-10-25 — E37: chunking 32/64/128 — качество не меняется; P3 off — 🟢
- **Результат:** current/split32/split64/split128 — все h1 0.688, h5 0.771, MRR 0.713.
- Нарезка не узкое место; top-5 определяется file-level ranking. P3 off: p50 87 ms,
  качество не падает. `MSCODEBASE_P3_ANCHOR=false` по умолчанию.
- **Артефакты:** `experiments/e37_chunking/`.

---
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

---

## 2026-11-24 — рантайм-метрики были трекнуты: каждый запуск сервера грязнил дерево — 🟢 закрыто

- **Симптом:** `M telemetry/tool_metrics.json` после любого запуска MCP из репо;
  в HEAD файл пустой (`{}`), в рабочем — 62 строки метрик.
- **Корень:** `server_factory.py:248` пишет `_ext_root/telemetry/tool_metrics.json`
  каждые 10 вызовов и на `atexit`; в dev `_ext_root` = репозиторий, файл трекнут.
- **Fix/Guard:** `git rm --cached` + `.gitignore` (`...json`, `.tmp`), runtime-путь
  не менялся; `test_runtime_metrics_file_is_not_tracked` красный до untrack.
- **Проверка:** 6/6 guard-тестов; `git status` файл больше не показывает.

---

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

---

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

---

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

---

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

---

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

---

## 2026-11-13 — slow-тесты прятали смену хранилища: 5 красных в `test_freshness_checker` — 🟢

- **Измерено:** на `main` (`a6524d6`, `801621d`) `pytest tests/test_freshness_checker.py -m "not benchmark"` → `5 failed, 2 passed`; в дефолтном гейте файл не виден (`pytestmark = pytest.mark.slow`).
- **Корень:** тесты читали `indexer.table` (LanceDB), а дефолт — SQLite (`src/core/indexing/indexer.py:146-154`, `SearchConfig.sqlite_chunks=true`); запись шла в `SQLiteChunkStore`, таблица LanceDB пустая.
- **Не регресс Цели 1/2:** те же 5 падают на до-мержевом `main` `a6524d6`.
- **Fix (PR #126):** чтение через `_file_rows()` (слой, который реально используется) + `test_store_is_the_default_one` пиннит дефолт; `slow`-маркер снят (файл 4.2 s). Проверка: `8 passed` 3× подряд; мутация `verify_index_freshness → return 0` даёт `4 failed`; гейт `2518 passed, 0 failed`.

---
