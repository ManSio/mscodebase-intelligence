# Experiment 1 Design: Multi-RAG Component Ablation

> Статус: **DESIGNED** — 2026-08-11. Реализация: `multi_rag_ablation.py` (v2).
> Вопрос из задачи: «Multi-RAG (Vector + Keyword + Graph + Memory) > Single RAG?»
> Статья-источник: «Building an AI-Native Second Brain with Multi-RAG, Knowledge Graphs, and MCP».

## 0. Research Question и гипотезы (явные, фальсифицируемые)

**RQ1:** Даёт ли мультикомпонентный ретривал (Vector + BM25 + FTS5 + Graph) измеримо
лучший evidence-recall, чем каждый компонент по отдельности, на ground-truth задачах
о кодовой базе?

| # | Гипотеза | Ожидание | Критерий подтверждения |
|---|----------|----------|------------------------|
| H1 | Multi-RAG recall > single-component recall | full (V+B+F+G+rerank) recall > каждого single | paired Δrecall > +0.05 И CI95 не пересекает 0 |
| H2 | Каждый компонент даёт инкрементальный вклад | V+BM25+FTS5+Graph рекорд по сумме парных Δ | ≥3 из 4 инкрементов (BM25, FTS5, Graph на базе V) значимы |
| H3 | Graph сильнее всего на задачах связей | Δrecall(graph) макс. на klass ∈ {find_caller_callee, find_impact} | подвыборка klass: Δrecall > +0.10 |
| H4 | Single-компоненты дешевле по токенам, hybrid точнее | tokens: single < hybrid; precision: hybrid ≥ single | монотонность tokens по числу компонентов |
| H5 | FTS5 и BM25 избыточны (оба keyword) | V+BM25+FTS5 ≈ V+BM25 по recall (Δ ≤ +0.05) | CI95 включает 0 |

**Не тестируем (scope):** Memory-компонент — это Experiment 2 (Memory Contamination,
по плану DEFERRED). Memory-рука исключена из матрицы, помечена как будущая.

## 1. Найденный дефект текущего черновика (multi_rag_ablation.py v1)

Черновик (v1) определяет 14 рук, но **руки неразличимы**:

- `run_search_arm` (v1, L200-232): руки с `mode="fast"` ВСЕ вызывают
  `searcher.search_with_mode(mode="fast")` — один и тот же путь.
- Флаги `use_bm25 / use_fts5 / use_graph / use_reranker` **нигде не используются**
  (мёртвый конфиг). `bm25_only`, `fts5_only`, `graph_only`, `vector_bm25`,
  `vector_bm25_fts5` и т.д. возвращали бы **идентичные** результаты.
- Реальность `mode="fast"` (engine.py L899-946): embed + vector + FTS5 + exact-boost
  + dedup + graph-expansion + bucket weights — НЕ «vector only» (докстринг устарел).
- `mode="deep"` (L948-959) сейчас **код-идентичен** `quality` (L961-972): оба
  `hybrid_search` + `_expand_graph_context` + reranker → рука «deep» избыточна.

**Вывод:** v1 непригоден как абляция; нужна изоляция компонентов на уровне методов.

## 2. Механика изоляции компонентов (v2)

Компоненты ретривала — методы `Searcher` (установлены миксинами/модулем):

| Компонент | Метод | Источник |
|-----------|-------|----------|
| BM25 (sparse) | `_bm25_search_async(query, limit)` | `src/core/search/bm25.py` (BM25Mixin) |
| Vector (dense) | `_vector_search_async(vec, limit, filter_expr)` | `src/core/search/engine.py` |
| FTS5 (full-text) | `_fts5_search_async(query, limit)` | `src/core/search/fts5_mixin.py` (FTS5Mixin) |
| Graph (symbol graph) | `_expand_graph_context(results, query)` (enrich) + SymbolIndex для graph-only | `src/core/search/engine.py` + `graph_adapter.py` |
| Reranker | `_apply_multi_reranker_async(query, results, top_n)` | `src/core/search/engine.py` L1305 |

**Принцип:** каждая рука = патч инстанса `Searcher` (monkey-patch на время вызова,
restore после): отключённый компонент заменяется на `async def _noop(...) -> []`
(или passthrough для reranker). Все руки идут через **один и тот же**
`hybrid_search_async(query, limit, use_rrf=True, expand=False)`:

- `expand=False` — **обязательно**: query expansion добавил бы варианты запроса и
  замазал изоляцию (синонимы входят в BM25/vector обоих рук неодинаково).
- `use_rrf=True` — единый фьюжн для всех рук (production-путь).
- Кэш `search_with_mode` не участвует (вызов идёт напрямую в `hybrid_search_async`),
  что исключает cache-pollution между руками (v1: все fast-руки делили `cache_key`).
- Пост-обработка (bucket weights, co-change boost, MMR, exact-name boost, dedupe,
  security-stamp, token savings) — **константа для всех рук** (не компонент ретривала).

**Graph:** для рук с `use_graph=True` — после `hybrid_search_async` вызываем
`searcher._expand_graph_context(results, query)` (как в production quality).

**graph_only рука** — отдельный путь (enrichment невозможен без seed-результатов):
прямой запрос SymbolIndex по имени символа задачи:
`si.find_definitions(sym)` → секция «definition», `si.get_callers(sym)` /
`si.get_callees(sym)` → секции «graph» (формат `{file}:{line} {symbol}`).
Это соответствует «Graph retrieval» из статьи (запрос по имени символа). Если
SymbolIndex недоступен → рука возвращает пустой результат (замеряет покрытие).

**deep рука — удалена** (== quality в текущем коде, задокументировано выше).

## 3. Матрица рук (13 → 12)

| # | arm | bm25 | vector | fts5 | graph | rerank | Комментарий |
|---|-----|------|--------|------|-------|--------|-------------|
| 1 | `vector_only` | ✗ | ✓ | ✗ | ✗ | ✗ | dense baseline |
| 2 | `bm25_only` | ✓ | ✗ | ✗ | ✗ | ✗ | sparse baseline |
| 3 | `fts5_only` | ✗ | ✗ | ✓ | ✗ | ✗ | full-text baseline |
| 4 | `graph_only` | ✗ | ✗ | ✗ | ✓ (SymbolIndex) | ✗ | symbol-graph baseline |
| 5 | `vector_bm25` | ✓ | ✓ | ✗ | ✗ | ✗ | |
| 6 | `vector_fts5` | ✗ | ✓ | ✓ | ✗ | ✗ | |
| 7 | `vector_graph` | ✗ | ✓ | ✗ | ✓ | ✗ | |
| 8 | `bm25_fts5` | ✓ | ✗ | ✓ | ✗ | ✗ | H5-пара |
| 9 | `vector_bm25_fts5` | ✓ | ✓ | ✓ | ✗ | ✗ | H5-пара |
| 10 | `vector_bm25_graph` | ✓ | ✓ | ✗ | ✓ | ✗ | |
| 11 | `full_no_rerank` | ✓ | ✓ | ✓ | ✓ | ✗ | полный без реранкера |
| 12 | `quality` | ✓ | ✓ | ✓ | ✓ | ✓ | **prod** (search_with_mode quality) |

Исключено: `deep` (дубль quality), Memory-руки (→ Experiment 2).

## 4. Метрики (определения)

На задаче `task` с `required_facts` (паттерны, обычно 4) и `wrong_patterns`:

| Метрика | Формула | Смысл |
|---------|---------|-------|
| `recall` | `#required_facts, найденных в выдача` / `#required_facts` | evidence-полнота (главная метрика) |
| `precision` | токены с required / (токены с required + wrong + irrelevant) | точность по токенам |
| `wrong_rate` | токены wrong-паттернов / всего токенов | доля «неправильных» свидетельств |
| `dup_rate` | повторные факт-токены / всего | дублирование фактов |
| `tokens` | len(текста)/4 | бюджет контекста агента |
| `agent_latency_ms` | wall-clock вызова | стоимость агента |
| `result_count` | число чанков в выдаче | |

Реализация: `evidence_metrics()` (уже в multi_rag_ablation.py v1 — корректна,
дефект был только в изоляции рук).

## 5. Статистический протокол (урок D-v3: N=30, paired)

- **N = 30 задач** (tasks_v3.json, 9 klass) — paired-дизайн: каждая рука на каждом
  task, Δ считается внутри task.
- Инкрементальные пары (ответ на «что даёт компонент»):
  - BM25 на базе V: `vector_bm25` vs `vector_only`
  - Vector на базе BM25: `vector_bm25` vs `bm25_only`
  - FTS5 на базе V+BM25: `vector_bm25_fts5` vs `vector_bm25`
  - Graph на базе V+BM25: `vector_bm25_graph` vs `vector_bm25`
  - Graph на базе V+BM25+FTS5: `full_no_rerank` vs `vector_bm25_fts5`
  - Rerank на базе full: `quality` vs `full_no_rerank`
  - Single vs single: `bm25_only` vs `fts5_only` (H5-часть)
- Для каждой пары: `Δ = mean(arm_a - arm_b)`, `sd`, `CI95 = 1.96·sd/√N`,
  `wins_a`, `wins_b`, ничьи.
- **Правило вердикта** (из D-v3): если |Δ| < CI95 или ничьи ≥ 2/3 задач →
  «НЕРАЗЛИЧИМО» (не «равно», не «лучше»). Только Δ > 0.05 с CI95 ∌ 0 и
  wins ≥ 2/3 → «компонент добавляет recall».
- Токен-стоимость: paired Δtokens с тем же CI95 (trade-off recall/tokens).

## 6. Контроль конфаундов

| Конфаунд | Контроль |
|----------|----------|
| Разное состояние эмбеддера | Один процесс, одна сессия, llama.cpp фиксирован |
| Снапшот индекса | Артефакт-БД копируется в temp (паттерн bench_v2), `.write_lock*` удаляются |
| FTS5 lazy build (~0.5s) искажает latency первой руки | warmup-вызов FTS5 до тайминга (1 прогон вне замера) |
| Query expansion замазывает изоляцию | `expand=False` для всех рук (задокументировано) |
| Кэш search_with_mode между руками | Прямой вызов `hybrid_search_async` (кэш не участвует) |
| Реранкер-кэш | no-rerank руки: `_apply_multi_reranker_async` → passthrough |
| Порядок рук (усталость/кэши embed) | Один и тот же порядок для всех задач; embedding-cache общий (не влияет на корректность, только latency) |
| `limit` | `limit=10` для всех рук (как v1) |
| Реранкер недоступен в эксперименте | quality-рука вернёт RRF-результаты (fallback в `_apply_multi_reranker_async` L1331) — отметить в отчёте |

## 7. Ожидаемые результаты (до запуска — предсказания, потом замер)

- `graph_only` recall низкий (4-6 паттернов из 4 требуют исходника/вызовов), но
  precision высокий → подтверждает «graph — дополнение, не замена».
- `bm25_only` > `fts5_only` по recall (BM25 токенизация лучше для кода) → H5.
- `vector_bm25_fts5` ≈ `vector_bm25` (FTS5 избыточен при наличии BM25) → H5.
- `quality` vs `full_no_rerank`: rerank улучшает precision, recall может упасть
  (top-N сужение) → интересный trade-off для прод-вывода.
- Токены: монотонно растут с числом компонентов; `graph` добавляет ~0 токенов
  (enrichment метаданных, не текста) — важный аргумент «graph бесплатен».

## 8. Артефакты

1. `multi_rag_ablation_tasks_v3.json` — raw: task × arm × (метрики + sections).
2. Консольный summary: AVG-таблица + PAIRED-таблица (уже в v1, L320-373).
3. Запись в `EXPERIMENTS_LOG.md` (формат §1.6: гипотеза → команда → сырой вывод →
   вердикт; урок).
4. Вердикт-таблица по §5 в `.agent_task_state.md` (Verification Results).

## 9. Команда запуска

```bash
cd /d/Project/MSCodeBase
# из проекта или venv расширения (нужен lancedb + deps):
venv/Scripts/python.exe experiments/context_engine/multi_rag_ablation.py tasks_v3.json
# полный прогон: 30 задач × 12 рук ≈ 10-15 мин (fast-руки ~1-2s, quality ~4-6s)
```

Smoke-проверка (валидация изоляции): 3 задачи × 3 контрастные руки
(`vector_only`, `bm25_only`, `fts5_only`) — результаты ОБЯЗАНЫ отличаться;
если recall идентичен во всех трёх — изоляция сломана, не запускать полный прогон.

## 10. Ограничения

- Ground-truth — паттерн-матчинг по тексту выдачи (не семантика); recall может
  занижаться на коротких чанках.
- `required_facts` строились для оценки context-движка (D-эксперименты), не для
  ретривала — возможен систематический сдвиг в пользу рук с большим числом
  чанков. Проверка: dup_rate и result_count в отчёте.
- Graph-only рука зависит от качества PropertyGraph (D1-D3 фиксы уже применены).
- `quality`-рука в эксперименте без реранкера ≠ prod (реранкер BGE-M3 поднимается
  только в MCP-процессе); если реранкер доступен в сессии — отметить.

---
*Дизайн следует §1 AGENTS.md (гипотеза до замера), уроку D-v3 (N=30, paired CI95)
и §5.13 (контроль корректности, а не только скорости). Реализация — multi_rag_ablation.py v2.*
