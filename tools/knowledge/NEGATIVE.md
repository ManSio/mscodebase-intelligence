# 🚫 ОТРИЦАТЕЛЬНЫЕ РЕЗУЛЬТАТЫ — «не повторять»

**Правило:** этот класс **терминален**. Попытка воскресить опровергнутое без новых данных —
нарушение. По `CONSOLIDATION.md` §4 отрицательный результат **не повышается** в паттерн.

Полный реестр отрицательных результатов ведётся в `EXPERIMENTS_LOG.md`
(`## 🚫 Отрицательные результаты`). Здесь — **глобальный** список, выдобранный из трёх
корпусов, потому что он нужен агенту **до** чтения 2844 строк.

---

## A. Опровергнутые внутренние утверждения (мы сами были неправы)

| # | Утверждение было | Оказалось | Ref |
|---|---|---|---|
| A-01 | «xdist даёт лишь ~15% — не берём» | **×2.76** локально (197.1с→71.4с), **×7** в CI (13m44s→1m58s) | `EXPERIMENTS_LOG.md:2738` |
| A-02 | «sysmon ≈3–7% median loss» | **+19.96%** против sys.settrace +13.6% | `EXPERIMENTS_LOG.md:2276` |
| A-03 | Exp v3 на `search_lancedb` (2/13 hit) как находка | отозван: чистый dense в обход ретривера + тавтология `compressed_found` + no-op компрессор = `invalid-duplicate-E10` | `EXPERIMENTS_LOG.md:2762,2765` |
| A-04 | Exp v1 (`5e7fd2da`) как измерение сжатия | invalid by design: TF-IDF по заранее известным target files | `EXPERIMENTS_LOG.md:2762` |
| A-05 | «граф закрывает present-trap», «glm fail-open не лечится» | оба — артефакт mislabeled датасета: 4 из 6 trap-фактов **истинны**; реальный trap-FA = 0 | `EXPERIMENTS_LOG.md:1615` |
| A-06 | «git-провенанс = temporal-сигнал, qwen путает было/сейчас» | blind 48/48 у всех моделей; у qwen sighted **хуже** (43/48) — строки «existed until C» активно вредили | `EXPERIMENTS_LOG.md:1665,1646` |
| A-07 | «фильтр режет 0 выдачи» | замер на пуле, уже отфильтрованном `hybrid_search_async` (survivorship bias) | `EXPERIMENTS_LOG.md:2817` |
| A-08 | «E10: full-text chunk + e5-префиксы + reranker pool 50» улучшает | все три «выключателя» — дельты в шуме при N=10; hit@1 0% → 0% | `EXPERIMENTS_LOG.md:2306,2324` |
| A-09 | «relang: эффект языка есть» | RU 32.5% vs EN 37.5%, **CI пересекаются**; 6/16 запросов флипаются all-or-nothing | `KNOWN_ISSUES.md:11` |
| A-10 | «relang все 6 файлов — не воспроизвелось» | на 12 ядрах 197.1с→71.4с (см. A-01) | `EXPERIMENTS_LOG.md:2738` |
| A-11 | DeebounceBatch deadlock | `_flush()` вне lock — deadlock **не воспроизводится** | `EXPERIMENTS_LOG.md:1060` |
| A-12 | «механический поиск недостаточен, нужен семантический» (E7) | необоснованно дизайном: маппер **был** LLM, сравнения keyword-vs-LLM не было | `EXPERIMENTS_LOG.md:2575` |

## B. Опровергнутые внешние заявления (чужие числа)

| # | Заявление | Оказалось | Ref |
|---|---|---|---|
| B-01 | scip-python как pip-зависимость | пакета нет на PyPI (404), только CLI Sourcegraph с node/native сборкой | `EXPERIMENTS_LOG.md:1157` |
| B-02 | cypher-sqlite как готовая библиотека | нет на PyPI; свой `CypherExecutor` уже реализован | `EXPERIMENTS_LOG.md:1158` |
| B-03 | «371 язык symbol extraction» из tree-sitter-language-pack | tags.scm есть у **71 из 371** (19%); 300 языков — AST без символов | `EXPERIMENTS_LOG.md:1159` |
| B-04 | pylint-django как детектор дупликации | это Django-плагин (ForeignKey/Model), не dup-detector | `EXPERIMENTS_LOG.md:1160` |
| B-05 | NodeRAG (graph traversal) > chunked retrieval (заявление Tom Jones) | TF-IDF 8/10 (80%) против BFS 7/10 (70%); граф выигрывает только по токенам (−43%) | `EXPERIMENTS_LOG.md:66` |
| B-06 | «латентная поддержка llama.cpp режет FA» | заявление не подтверждено; статус invalid-by-design | `KNOWN_ISSUES.md:14` |
| B-07 | «5 ошибок поймал = 5/5 стена работает» (интерпретация наших) | 5 без знаменателя и без negative control = directional signal, **не rate** | `github.com/tjonesit/crystals` issue #1 (2026-09-30) |

## C. Технические гипотезы, не подтвердившиеся

| # | Гипотеза | Результат | Ref |
|---|---|---|---|
| C-01 | Multi-RAG > Single-RAG по recall | `fts5_only 0.825 ≥ full 0.775`; BM25≈FTS5 **не** избыточны (разные профили) | `EXPERIMENTS_LOG.md:1466,1470` |
| C-02 | текстовый RAG (doc-chunks) не хуже кодового | hit@5 12.5% против 50%/40%; doc не в топ-5 для 14/16 | `EXPERIMENTS_LOG.md:2388` |
| C-03 | гибрид file+graph evidence аддитивен | acc 0.900 **<** file-only 0.940; граф полезен только без фрагмента | `EXPERIMENTS_LOG.md:1598,1600` |
| C-04 | Tarantula как селектор целевой функции | rank≤3 лишь у 22.6% (порог 60–70%); noise-filter не помогает (15.7% при любом cutoff) | `EXPERIMENTS_LOG.md:2212,2239` |
| C-05 | coverage.py `dynamic_context` (sysmon) как драйвер | overhead +19.96% против sys.settrace +13.6%; цель <5% **не достигнута** | `EXPERIMENTS_LOG.md:2250,2274` |
| C-06 | детерминированный keyword-роутер по классам | recall 0.200 против каскада 0.233, klass_acc=0.40 | `EXPERIMENTS_LOG.md:1875` |
| C-07 | grep-парсинг TOML-массивов по якорю `^` в drift-гейте | PINNED всегда пуст → ветка DRIFT **недостижима** для всех 3 пакетов | `EXPERIMENTS_LOG.md:615` |
| C-08 | `Future.result(timeout)` как защита от зависания потока | `shutdown(wait=True)` в finally перекрыл: 6.00с вместо 1.0с | `KNOWN_ISSUES.md:110` |
| C-09 | HF-truncation 512 гарантирует лимит llama.cpp | запас 0–10 токенов; плотный CJK даёт 526>512 (разные BPE) | `EXPERIMENTS_LOG.md:1091` |
| C-10 | in-process Searcher при живом MCP (Benchmark 2.0) | PID-lock fail-closed блокирует второй Indexer — это **защита**, не баг | `EXPERIMENTS_LOG.md:1251` |
| C-11 | суита вакуумных тестов как доказательство проходимости гейта | гейт напечатал бы PASSED для 0 asserts — reproducibility без falsifiability | `EXPERIMENTS_LOG.md:611` |
| C-12 | redaction = граница безопасности | новый формат / многострочный секрет проходят; не продаётся как safe | `EXPERIMENTS_LOG.md:2647` |
| C-13 | restraint (anti-numbing) как ограничитель | best-effort, fail-open при сбое чтения | `EXPERIMENTS_LOG.md:2670` |

## D. Проверка самих гейтов (метод, а не результат)

| # | Проверка | Чему научились | Ref |
|---|---|---|---|
| D-01 | Сканер простаивания сам заглох на несуществующем каталоге | Guard надо проверять на **живом** дефекте, а не на гипотезе | `experiments/misc_probes/exp_vacuous_scan.py` |
| D-04 | Ссылки на несуществующие строки проходили валидацию, пока файл был временно длиннее | `KNOWN_ISSUES.md` — 153 строки; рефы на 327–444 указывали на контент, **которого на диске не было**. Валидатор проверяет границу файла, а не то, что строка несёт утверждение. Проявилось только когда авто-синк (+267 строк) откатили по §19.9 | `knowledge/repoint_stale_refs.py` |
| D-05 | Формально валидная строка ≠ строка по смыслу | Первая попытка починки подставила `KNOWN_ISSUES.md:70` вместо 437 — строка существует, но про Haiku-судью, а не про silent zero. Хуже оригинала: проходит валидацию и врёт | `knowledge/repoint_stale_refs.py` |
| D-02 | `max(len(x),1)` принят за защиту populations | Спасает от деления на ноль, но всё равно печатает «0%» с rc=0 | `tests/test_audit_protocol_guards.py` |
| D-03 | Один regex считал «Ожидаем ПРОВАЛ» за фальсификатор | Ветка проверки оказалась **слепой**; selftest это доказал | `scripts/audit_protocol_guards.py --selftest` |
| D-04 | Grep по кириллической `Т` (U+0422) не находит латинскую `T` | Мои же триггеры — `Т1…Т12` кириллицей; проверка была Latin-only и врала | `C:\Users\misha\.config\opencode\AGENTS.md` |
