# KNOWN ISSUES — MSCodeBase Intelligence

> Синхронизируется из `AGENT_DIARY.md` при каждом [🏁 ИТОГ].
> Формат: дата | что было | статус | fix

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
## 2026-10-25 — AUDIT: graph=0, leakage, docs=0 — P0 graph fixed

- **Graph:** production `graph.db` был 0 nodes; `index_project` блокируется
  `DENSE_OFF`. Fixed: `scripts/rebuild_graph.py` → **12,753 nodes / 45,762 edges**.
  Требуется рестарт MCP, чтобы сервер открыл новый graph.db.
- **Leakage:** `experiments/frozen` индексировался (19/48 BM25). Fixed:
  `SystemArtifacts` исключает `experiments/**`; index очищен (0 experiments,
  7,314 chunks, FTS synced).
- **Docs:** E53/E54 — lexical/explicit intent не дают docs hit@1 (0). Нужен
  отдельный docs-only FTS канал (E48: 0.75/1.00), без LLM-router.
- Baseline clean: **0.688/0.750**; code 0.825/0.900; docs 0/0.

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
## 2026-10-25 — E45: structured agent plan — +1 h1, p50 72 ms — 🟢 worth API

- **План:** primary + must_include + symbols, один запрос, без multi-query RRF.
- **Результат:** baseline 0.688/0.771/79ms; plan_must **0.708**/0.771/71ms; plan_full 0.708/0.771/72ms.
- **Вердикт:** один primary + must_include — маленький реальный выигрыш; symbols не дают.
  Внедрить как опциональные поля `search_code` + tool `plan_search`. 95% не закрывает.
- **Артефакты:** `experiments/e45_agent_plan/`.

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
## 2026-10-25 — E36-audit: symbol_name пуст, P3 мёртв, graph-stage synthetic — 🟢 FIXED (index rebuilt)

- **Root cause:** `write_text_records` читал `symbol_name` из `chunk_metadatas`, где его не было →
  **0/16 158** чанков с symbol_name. FTS5/BM25 boosts, exact-name, graph hydration — мертвы.
- **Fix:** AST-symbol→line-range mapping в `IndexPipeline.process_file`; reindex →
  4 772/16 347 с symbol_name. Graph-stage: hydration + relative paths + line fallback.
  P3: чтение `SQLiteChunkStore.get_file_head` вместо мёртвого `_bm25_df`.
- **Corrected E36:** full h1 0.688/h5 **0.771**/p50 183 ms; no_p3 87 ms (P3 +96 ms без качества);
  no_bucket 0.562; no_o1 0.667; no_demote 0.625; minimal 0.542/0.750.
- **Остаток:** P3 отключать при выключенном reranker; E32/E33/E35 пере-прогнать на исправленном
  индексе (E33 demote всё ещё +3 h1; E32/E35 без изменений).
- **Артефакты:** `experiments/e36_ablation/`.

---
