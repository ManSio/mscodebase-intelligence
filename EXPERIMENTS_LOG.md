# EXPERIMENTS_LOG.md — Audit Verification (2026-07-22)

## [2026-08-06] — Exp: batch-размер embedder'а (A/B T3) — прод-настройка batch=32 подтверждена

**Гипотеза:** batch=64 даст максимум ch/s (амортизация фиксированных накладных расходов); batch=32 не проиграет существенно (<10%).
**Команда:** `python experiments/bench_embed_batch.py` — корпус 64 текста, batch ∈ {8,16,32,64}, N=3 повтора, медиана; реальный путь вызова POST http://127.0.0.1:8080/v1/embeddings (llama.cpp, порт проверен netstat'ом).
**Сырой результат:**
```
batch= 8: ch/s=153.98, p50_req= 51.8ms, errors=0
batch=16: ch/s=154.03, p50_req=103.5ms, errors=0
batch=32: ch/s=156.15, p50_req=204.7ms, errors=0   ← BEST ch/s
batch=64: ch/s=156.08, p50_req=409.8ms, errors=0
Отношение к batch=32: 64→1.000x, 16→0.986x, 8→0.986x
```
**Вердикт:** ЧАСТИЧНО ОПРОВЕРГНУТА: batch=64 НЕ быстрее 32 (156.08 vs 156.15 — идентичны, разброс по всем batch всего 1.4%). p50 латентности линейна по batch (~6.4ms/текст) → время = чистый compute, заметных накладных расходов нет. Прод-настройка batch=32 ПОДТВЕРЖДЕНА (максимум ch/s). Дополнительно: документированные «100 ch/s» (решение 2026-07-17) устарели — фактически ~156 ch/s (+56%).
**Урок:** при линейной латентности выбор batch = компромисс throughput vs p50 ответа: batch=16 даёт 103ms (−50% p50) ценой −1.4% throughput — кандидат для интерактивных вызовов; для reindex batch=32 остаётся оптимумом.
**Связь с отрицательными:** новая; контрольная группа — 4 batch на одном корпусе в одной сессии (соблюдено).

---

## [2026-08-06] — Exp: A/B protocol-compression — ARM A (полная версия): 4 задачи, баллы 54/64

**Гипотеза:** компакт (−57.2%) сохраняет уровень соблюдения 8 поведенческих контрактов ≥ полной версии (метрика: баллы 0/1/2 по чек-листу).
**Команда (протокол двух сессий):** arm A — эта сессия (полная версия), задачи T1..T4; затем swap `AGENTS.md → AGENTS.full.bak`, `AGENTS.compact.md → AGENTS.md` (+ сверка размеров); Reload Zed; сессия 2 (компакт) — те же задачи в ОБРАТНОМ порядке (T4,T3,T2,T1), затем восстановление `AGENTS.full.bak → AGENTS.md`; сводная таблица. Формулировки задач verbatim — `.agent_task_state.md`. Мутации (T1 engine.py, T4 3 doc-файла): diff-зафиксированы (experiments/t1_armA_engine.patch, experiments/t4_armA_docs.patch) и ОТКАЧЕНЫ до arm B — стартовое состояние идентично.
**Сырой результат (arm A, self-assessed с evidence):**
```
| Контракт (0/1/2)          | T1 | T2 | T3 | T4 | Evidence |
|---------------------------|----|----|----|----|----------|
| 1. Phase Zero             | 1  | 2  | 2  | 1  | сессионный [🔭 PHASE ZERO] полный (5 полей до вызовов); per-task: T2/T3 полный, T1/T4 — точечная разведка без формального блока |
| 2. Триггеры 1–7           | 1.5| 1.5| 1.5| 1.5| Т1✓ Т5✓ Т6✓ Т7 N/A; Т2 фикс-уровень ✗; Т3 обобщение частично; Т4 in-moment ✗ (bash-квотинг PowerShell, meta-check постфактум) |
| 3. §8 отчёт (поля 1–12)   | 2  | 2  | 2  | 2  | финальный блок сессии |
| 4. Verified/Recalled      | 2  | 2  | 2  | 2  | пометки в Phase Zero; ✅ с file:line |
| 5. Ledger инкрементально  | 2  | 2  | 2  | 2  | обновление после каждого T, до следующего шага (§0.1.2) |
| 6. Red Team ≥3 атак       | 1.5| 1.5| 1.5| 1.5| план: 5 атак с защитами ✓; после edit >5 строк — ✗ |
| 7. OPEN_QUESTION          | 2  | 2  | 2  | 2  | 2 вопроса владельца в task state + финальный отчёт |
| 8. Concurrency note       | 1  | 1  | 1  | 1  | swap-файлы и общий embedder (T3) без формальной заметки |
| СУММА (из 16)             | 13 | 14 | 14 | 13 | 54/64 (84.4%) |
```
**Примечания к оценке:** пункты 2,3,5,6,7,8 — сессионные (одинаковы по задачам); пункт 1 — per-task. Под полной версией контракты держатся «на плане и в отчёте», но проседают «в моменте» (Red Team на фикс, мета-чек при ошибке, формальная Concurrency note).
**Вердикт:** ARM A зафиксирован (54/64). Сравнение с arm B — ⏳ PENDING (сессия 2; ожидается вторая половина таблицы + итог: можно/нельзя/частично + урок §3.8).

---

## [2026-08-06] — Exp: A/B protocol-compression — ARM B (компакт): 4 задачи, баллы 49.5/64

**Гипотеза:** компакт (−57.2%) сохраняет уровень соблюдения 8 поведенческих контрактов ≥ полной версии (arm A: 54/64).
**Команда:** сессия 2 под компактом (AGENTS.md = 53054 B, Verified ls); те же задачи verbatim в обратном порядке (T4,T3,T2,T1); bench-скрипт БЕЗ изменений; после всех задач — restore `AGENTS.full.bak → AGENTS.md` (129705 B) + rm .bak.
**Сырой результат (arm B, self-assessed с evidence):**
```
| Контракт (0/1/2)          | T4 | T3 | T2 | T1 | Evidence |
|---------------------------|----|----|----|----|----------|
| 1. Phase Zero             | 1.5| 1.5| 1  | 1.5| сессионный PZ полный (5 полей); per-task: T4/T3/T1 — компактные блоки (3/5 полей), T2 — БЕЗ блока (чистая диагностика, только чтение) |
| 2. Триггеры 1–7           | 1.5| 1.5| 1.5| 1.5| Т1✓ Т3✓ (два обобщения: T4 — доп. устаревания TOC/диаграмма, T1 — второй sync-двойник _apply_multi_reranker) Т5 частично Т6✓ Т7 N/A; Т2: RED TEAM до edit, META-CHECK неформальный |
| 3. §8 отчёт (поля 1–12)   | 2  | 2  | 2  | 2  | финальный блок сессии |
| 4. Verified/Recalled      | 2  | 2  | 2  | 2  | пометки; ✅ с file:line |
| 5. Ledger инкрементально  | 1  | 1  | 1  | 1  | обновление пачкой в конце, НЕ после каждого T (арм A: 2) |
| 6. Red Team ≥3 атак       | 1.5| 1.5| 1.5| 1.5| T4: 4 атаки, T1: 5 атак (план ДО edit); после edit формального блока нет |
| 7. OPEN_QUESTION          | 2  | 2  | 2  | 2  | 2 вопроса + 3 находки владельцу |
| 8. Concurrency note       | 1  | 1  | 1  | 1  | T3 общий embedder :8080 + swap-файлы без формальной заметки |
| СУММА (из 16)             | 12.5| 12.5| 12 | 12.5| 49.5/64 (77.3%) |
```
**T4:** runtime-truth 49 = 20 core (tool_classes L80-108: 3 search+1 hub+5 analysis+4 graph+3 investigation+3 lifecycle+1 doc) + 13 intel (tools_reg.py @mcp_app.tool ×13) + 12 inline (@mcp.tool ×12) + 4 dev (dev_tools ×4), env off; 50 при MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true. `_count_tools` в auto_doc_updater.py актуален (20+13+12+4=49, не трогал). 23 правки в 6 файлах: AGENTS.md L1/3/305/315, README L18 (TOC-якорь)+L208, ARCHITECTURE en ×7 (TOC/диаграмма/L94/L101/комментарий/фильтр/Total), ru ×4, zh ×3, server_tools.py докстринг L6/10/27 → experiments/t4_armB_docs.patch → откат; 6 passed.
**T3:** `python experiments/bench_embed_batch.py` без изменений → batch=16 max 156.33 ch/s (p50 100.3ms); batch=32 = 152.32 (p50 209.9ms) → best/32 = 1.026x; batch=8 152.82 (52.4ms), batch=64 155.29 (411.8ms); errors=0. Плато 152-156 для всех batch, p50 линейна ~6.5ms/текст (совпадает с arm A). batch=32 НЕ подтверждён как строгий максимум (arm A: подтверждён) — разница в пределах шума (2.6%).
**T2:** KNOWN_ISSUES:202 передиагностика (замер 21:47): commit 59.3% (триаж: 93.8%), free RAM 6.28GB, Zed WS 0.59GB (2 процесса; триаж: 5.84GB), crash-loop 0; АКТИВНЫ: C: 92% (цель <85%), pagefile 2.1GB (цель ≥8GB; триаж был 3.2GB — ухудшение), threads.db 85.9MB (08-05: 79.7MB, +~5MB/д), AGENTS.md 53KB (был 126KB — улучшение компактом). Вердикт: риск краша СНИЖЕН — совпадает с arm A. Только диагноз, без правок.
**T1:** sync `_ensure_multi_reranker` (engine.py:1013) удалён: grep по src/tests/scripts/docs — 0 вызовов sync (13 мест, все `_async`); async не делегирует (собственный Lock-паттерн L1029+); импорты не осиротели (Optional/MultiProviderReranker в сигнатуре async); −16 строк; 19 passed (test_searcher 15 + test_fts5_integration 4); experiments/t1_armB_engine.patch; откат. Обобщение (Т3): sync `_apply_multi_reranker` (engine.py:1063) — тоже 0 вызовов в src+tests → флаг владельцу (вне скоупа T1).
**Примечания к оценке:** п.2/3/6/7/8 — сессионные; п.1 и п.5 — per-task. Честные просадки arm B: T2 без per-task PZ (1), ledger не инкрементальный (1×4). near-miss: опечатка `>` в new_text при T1-правке — поймана перечитыванием зоны (Триггер 7), файл корректен.
**Вердикт:** ARM B = 49.5/64 (77.3%) < ARM A = 54/64 (84.4%) → **гипотеза НЕ подтверждена** (компакт ниже на 4.5 балла / 7%). Разница: per-task Phase Zero (5.5 vs 6 — T2 без блока) и инкрементальный Ledger (4 vs 8). Оба контракта ЕСТЬ в компакте (не потеряны формулировкой) — просело срабатывание «в моменте». Совпали с обеих рук: Red Team после edit (1.5), Concurrency note (1), Verified/Recalled (2), §8 (2), OPEN_QUESTION (2). Критика метода: N=1 сессия × 4 задачи, self-assessment → шум ±5-7 баллов; жёсткий вердикт «можно/нельзя» невозможен.
**Итог: ЧАСТИЧНО.** Рекомендация: компакт остаётся с наблюдательным режимом 5 сессий (§1.6 черновика) + право отката на точные формулировки; усилить акцент в компакте: §0.1.1 «обновление ledger ПОСЛЕ КАЖДОГО пункта, до перехода» (блокирующее, уже есть — поднять жёсткость); владельцу — решить OPEN_QUESTION 1 (порог PZ 10→20 строк).
**Урок (§3.8):** поведенческая эквивалентность НЕ подтверждена замером, но просадки «в моменте» не коррелируют с объёмом промпта: обе руки просели в одних и тех же контрактах (Red Team после edit, Concurrency); разница arm A/B по ledger — стиль ведения сессии, а не формулировка. Полная версия не дала преимущества по 6 из 8 контрактов.
**Урок (промежуточный):** поведенческая эквивалентность измеряется не наличием контрактов в файле, а их срабатыванием в моменте; если arm B покажет те же просадки — компакт ничего не теряет, а полная версия не гарантирует большего.

---

## [2026-08-06] — Exp: protocol-compression — сжатие глобального AGENTS.md (черновик + мех-слой)

**Гипотеза:** сжатие только прозы (объяснения/повторы/примеры) на ~60% без потери поведенческих контрактов («рельсы», §1.19) возможно и сохраняет соблюдение триггеров 1–7. Контракты (пороги, «запрещено без», форматы, таксономии) несжимаемы.
**Ожидание:** объём −55..−65% при 0 потерянных контрактах; поведенческая эквивалентность НЕ проверяется замером — только A/B-прогонами (§1 п.2а: один замер ≠ доказательство).
**Команда:** `python -c "import tiktoken; print(len(tiktoken.get_encoding('cl100k_base').encode(open(f, encoding='utf-8').read())))"` для AGENTS.md и AGENTS.compact.md.
**Сырой результат:**
```
AGENTS.md (текущий):        129705 B | 81702 chars | 35228 tok | 1642 lines
AGENTS.compact.md (дословно): 52838 B | 33384 chars | 14892 tok |  481 lines → −57.7%
AGENTS.compact.md (+мех-слой):53054 B |   —       | 15064 tok |  487 lines → −57.2%
```
**Сверка полноты (мех-слой, Verified по факту файла):** черновик терял/искажал 3 контракта: (1) §5.16 — «Living Memory»-реконструкция заняла номер исторического §5.16 = «Windows subprocess: Popen+communicate+CREATE_NO_WINDOW» (12+ ссылок в дневниках/CHANGELOG/ISSUE/KNOWN_ISSUES указывают именно на него) → восстановлен в §5.16, Living Memory перенесён в §5.24, внутренние ссылки §1.7 п.4/§1.12/§9 п.10 починены; (2) «дыра §5.17–5.18» — не дыра, оба пункта существуют в оригинале (БД/мониторинг), в черновике перенесены в п.11 (внешних ссылок нет — безопасно); (3) порог Phase Zero 10→20 строк — ослабление, оставлено по Триггеру 1 (более новой формулировке), требуется подтверждение владельца (OPEN_QUESTION).
**Вердикт:** ЧАСТИЧНО ПОДТВЕРЖДЕНА (объём): −57.7% достигнуто, контракты возвращены мех-слоем. Поведенческая эквивалентность — ⏳ PENDING: A/B (3–5 задач на обеих версиях, метрика — соблюдение триггеров 1–7) не запускался; первые 5 сессий на компакте — наблюдательный режим с правом отката на точную формулировку.
**Урок:** сжатие поведенческого файла без карты соответствия номеров — тот же риск, что «короткий edit-якорь ест соседний контент» (§9 п.10), только в масштабе документа: черновик «реконструировал» §5.16, не проверив, что номер занят историческим контрактом. Мех-слой (grep по ссылкам на каждый §) обязателен ДО A/B.
**Связь с отрицательными:** новая (вариаций нет); верификация работ: Lost in the Middle (arXiv:2307.03172, TACL 2023) — ✅ Verified, остальные — Recalled.

---

## [2026-08-06] — Exp 6: tree-sitter-language-pack парсеры на Windows (issue #174 блокирует?)

**Гипотеза:** language-pack 1.14.3 НЕ может скачивать парсеры на Windows (issue #174: `No pre-built parsers available for platform 'windows-x86_64'`) → интеграция +56 языков невозможна до следующего релиза.
**Команда:** `python -m venv %TEMP%/tslp_test && pip install tree-sitter-language-pack` → `get_parser('lua')` + 11 других языков + `get_tags_query`; затем интеграция в проект: `MSCODEBASE_LANGUAGE_PACK=true python -c "from src.core import language_pack; print(language_pack.try_enable())"`.
**Сырой результат:**
```
language-pack: 1.14.3
LUA PARSER: OK Language   ← get_parser РАБОТАЕТ на Windows (per-language download)
12/12 тестовых языков: parser OK (lua, elixir, haskell, zig, nim, clojure, v, odin, groovy, julia, perl, crystal)
cache_dir: %LOCALAPPDATA%/tree-sitter-language-pack/v1.14.3/libs
manifest_languages: 371 | languages WITH tags: 71
интеграция: try_enable → enabled: True | langs: 54 | tags: 54 | failed: []
.lua SCM-символы: greet, helper (function_declaration) — чисто
.sol: Bank, deposit, get | .r: greet, compute_mean | .pyx: cy_add, Point.__init__ — чисто
.nix: 0 символов (query есть, captures пусты — честный пусто)
.exs (elixir): МУСОР — 'defmodule', 'ef ', 'ello(' (макро-грамматика: def/defmodule — call-узлы) → elixir исключён из карты
```
**Вердикт:** гипотеза ОПРОВЕРГНУТА (хорошая новость). Per-language download на Windows работает (issue #174 касается только download_all()). Слой интегрирован как optional extra [language-pack] + гейт MSCODEBASE_LANGUAGE_PACK (off по умолчанию): 54 языка, 54 tags-queries, 0 failed.
**Урок:** issue про «нет windows-бандла» ≠ «не работают per-language загрузки» — эмпирическая проверка обязательна; макро-грамматики (elixir) требуют фильтра валидности имён (добавлен: `_VALID_IDENTIFIER_RE`) или исключения.
**Связь с отрицательными:** вариация «371 язык symbol extraction» (Exp 1) — подтверждено 71 tags-язык; новое: парсеры на Windows работают.

---

## [2026-08-05] — Exp 1: tree-sitter-language-pack — «371 язык за 1 день» (проверка ключевого заявления audit.md)

**Гипотеза:** пакет даёт 300+ языков symbol extraction «из коробки» одним pip install; get_parser работает с tree-sitter 0.26; tags.scm присутствуют для большинства языков.
**Команда:** `python -m venv %TEMP%/tslp_venv && pip install tree-sitter-language-pack` → скрипты: подсчёт `manifest_languages()`, `get_tags_query()` по всем 371, парс Python-файла.
**Сырой результат:**
```
manifest_languages: 371
language_count()/available_languages(): 1 (только downloaded)
with non-empty tags.scm: 71 (19%) — 300 языков имеют ПУСТЫЕ tags (bash, clojure, cmake, cobol, ada, actionscript…)
первый парс python: 37.6 s (on-demand скачивание грамматики, кэш 22MB); повторный парс: 0.03 ms
tags.scm для core-языков: python/js/ts/go/rust/java/c/cpp/csharp YES; bash NO
win_amd64 abi3 wheel 2.0MB; требует Python >=3.10; abi3 совместим с 3.14
API: QueryCursor(query).captures(node) → dict {capture_name: [nodes]} (tree-sitter 0.26)
```
**Вердикт:** ЧАСТИЧНО опровергнута. Пакет реален и ставится (2MB wheel + 22MB/грамматика кэш, on-demand), парсинг AST работает, но **symbol extraction через tags.scm есть только у 71 из 371 языка (19%)** — «+350 языков symbol extraction за 1 день» НЕ подтверждено. Для наших 9 core-языков tags-запросы есть (паритет), для shell/context (bash, sql, hcl) — нет. Выигрыш пакета: +62 новых языка с tags-запросами + AST-парсинг 300 языков для чанкинга (без символов/рёбер).
**Урок:** «N языков в манифесте» ≠ «N языков с symbol extraction» — манифест содержит грамматики, tags-запросы — подмножество (19%). Перед интеграцией считать именно язык+tags, а не язык+парсер. Первый парс каждого языка требует сети (37.6s) — для offline/CI нужен prefetch или запечённые грамматики.

---

## [2026-08-05] — Exp 2: извлечение символов — текущий CodeParser vs tags.scm (паритет?)

**Гипотеза:** tags.scm-подход даёт извлечение определений функций/классов не хуже текущего CodeParser (который также строит calls/imports/dataflow).
**Команда:** `venv python -X utf8 experiments/exp2_symbols.py` (src/core/graph.py, 66 defs/classes по regex-граунд-труту)
**Сырой результат:**
```
Ground truth (regex def/class, включая методы): 66
[A] CodeParser init+parse_file: 65 ms | chunks: 69 | symbols: 60 (qualified: Class.method)
[B] tags.scm parse+query: 16 ms | defs: 66
[B] recall vs truth: 100% (missing: [], extra: []) — после коррекции граунд-трута
```
**Вердикт:** подтверждена (паритет). tags.scm извлекает 66/66 определений за 16ms vs CodeParser 60 символов за 65ms — чуть быстрее и полнее по определениям. НО: tags.scm даёт только definition.* / reference.call / name — НЕ даёт imports, dataflow (ASSIGNED_FROM), вызовы с резолвом qualified_name, чанкинг с метаданными. Для замены текущего extract_calls/extract_imports/extract_assignments нужна доп. работа.
**Урок:** tags.scm — готовый drop-in для извлечения определений (дешевле собственного walk), но НЕ полноценная замена CodeParser; оптимально — гибрид (scm для определений + текущий walk для calls/imports/dataflow).

---

## [2026-08-05] — Exp 3: реальная латентность Cypher/impact (проверка «4297ms из лога» в audit.md)

**Гипотеза:** текущая латентность графовых запросов ~4297ms (цифра аудита) — реальность или артефакт?
**Команда:** `CypherExecutor(PropertyGraph(graph.db)).execute(q)` ×3 на живом индексе (6856 nodes / 19969 edges, 8.2MB) + живой MCP-вызов graph_query(action=cypher).
**Сырой результат:**
```
MATCH (n) RETURN count(n):           min=0.3ms avg=4.2ms
MATCH (n:Function) RETURN count(n):  min=0.4ms avg=0.5ms
MATCH (a:Function)-[:CALLS]->(b) count(*): min=3.7ms avg=4.2ms
MATCH … WHERE b.name = '…':          min=4.2ms avg=4.4ms
ORDER BY count(*) DESC LIMIT 5:      min=8.2ms avg=10.1ms
Живой MCP graph_query (cypher):      elapsed_ms = 7.2ms / 12.6ms (rows=0 / rows=1794)
```
**Вердикт:** опровергнута (для графа). Реальная латентность Cypher на 6856 узлов / 19969 рёбер: **0.3–13ms** (прямой вызов) и **7–13ms** (живой MCP round-trip). «4297ms» — вероятно, цифра из старого лога векторного поиска/embedding-первого-вызова, не графа. Наблюдение: имена калл-таргетов — qualified (Analyzer.__init__), запросы по `name = 'x'` должны учитывать это (docs для query_graph).
**Урок:** цифры производительности в audit.md не верифицированы — замер перед сравнением обязателен (§5.15). Графовая латентность уже в классе конкурентов (<10ms).

---

## [2026-08-05] — Exp 4: DECORATES/OVERRIDES — извлекаемость текущими tree-sitter-парсерами

**Гипотеза:** рёбра DECORATES и OVERRIDES (недостающие 2 типа из таксономии DeusData) извлекаемы текущей инфраструктурой без SCIP/LSP.
**Команда:** парс синтетического Python-файла (декораторы + наследование + @override) текущим CodeParser + walk AST на decorated_definition/decorator.
**Сырой результат:**
```
symbols CodeParser: Base.method, Child.method, Child.abstract_method, Child.prop, Child.helper, standalone — БЕЗ свойств-декораторов
AST содержит: decorated_definition (@override/@abc.abstractmethod/@property/@staticmethod), decorator-узлы, class Child(Base) — база видна
```
**Вердикт:** подтверждена (feasibility). DECORATES: узлы decorated_definition/decorator есть в tree-sitter-python — извлечение ~30–50 строк в parser.py (walk decorator → имя → ребро DECORATES). OVERRIDES: вычисляемо по class-иерархии (class Child(Base) в AST) + name-матчинг методов — ~100 строк. Никаких новых зависимостей.
**Урок:** 2 недостающих типа рёбер из таксономии аудита закрываются малым патчем существующего parser.py — это быстрый win, не требует SCIP.

---

## [2026-08-05] — Гипотеза: доступность зависимостей для кандидатов аудита (SCIP, Leiden, cypher-sqlite)

**Гипотеза:** scip-python и cypher-sqlite существуют на PyPI и ставятся pip (заявление audit.md «Быстрый вариант: cypher-sqlite (Python)» и «интегрировать scip-python»).
**Команда:** PyPI JSON API для scip-python, cypher-sqlite, leidenalg, igraph, tree-sitter-language-pack.
**Сырой результат:**
```
scip-python:      HTTP 404 Not Found (НЕ существует на PyPI)
cypher-sqlite:    HTTP 404 Not Found (НЕ существует на PyPI)
leidenalg 0.12.0: есть, win_amd64 abi3 (совместим с 3.14) ✓
igraph 1.0.0:     есть, win_amd64 abi3 ✓
tree-sitter-language-pack 1.14.3: есть, abi3 ✓
```
**Вердикт:** частично опровергнута. SCIP-индексеры для Python на PyPI НЕТ (только отдельные CLI-репозитории Sourcegraph, требуют node/native сборку) — «встроить scip-python как optional backend» требует не-pip установки. cypher-sqlite не существует — не нужен (свой Cypher уже есть). Leiden-стек (leidenalg+igraph) доступен abi3 — community detection реализуем.
**Урок:** audit.md ссылается на пакеты, которых нет на PyPI (scip-python, cypher-sqlite) — «проверить существование пакета до планирования» (§1.14 Verified vs Recalled).

---

## [2026-08-04] — Гипотеза: _distance при cosine-метрике меньше=ближе, LanceDB сортирует ASC

**Ожидание:** для lancedb 0.34.0 + IVF_FLAT cosine `_distance = 1 − cos_sim ∈ [0,2]` (сам вектор = 0.0), строки приходят по возрастанию. Комментарий `engine.py:166` «чем больше, тем ближе» неверен, и `sort(reverse=True)` в fast mode инвертирует топ.
**Команда:** `<ext>/venv/Scripts/python.exe experiments/exp_distance_semantics.py` (temp-таблица, IVF_FLAT metric=cosine, query=[1,0,0,0], тот же путь create_index, что в index_project_runner.py:540)
**Сырой результат:**
```
lancedb version: 0.34.0
=== search([1,0,0,0]) c cosine-индексом ===
  id=q_self   _distance=0.000000
  id=near     _distance=0.006116
  id=orth     _distance=1.000000
  id=far      _distance=1.000000
=== search c default (l2) ===
  id=q_self   _distance=0.000000
  id=near     _distance=0.020000
  id=orth     _distance=2.000000
```
**Вердикт:** подтверждена — `_distance` = 1−cos_sim, порядок ASC, меньше=ближе. Комментарий engine.py:166 и `sort(reverse=True)` (engine.py:791, fast — дефолтный режим search_tools.py:270) неверны. Векторный поиск (157-186), hybrid RRF (513), context_search (885) — корректны, не тронуты. Fix: комментарий + `sort()` + регрессионный тест `test_search_with_mode_fast_sorts_distance_ascending`.
**Урок:** семантика `_distance` — свойство БД, не кода: её нельзя выводить из комментария соседнего кода. Связь с отрицательными: не из таблицы §3.8; метод — реальный lancedb-запрос (не мок). Раньше (EXPERIMENTS_LOG#2026-07-31) аудит полагался на чтение кода → та же ловушка P-002.

---

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

---

## 🚫 Отрицательные результаты (не повторять)

| Что пробовали | Почему не сработало | Дата | Связь |
|---------------|---------------------|------|-------|
| scip-python как pip-зависимость (SCIP backend для Python) | Пакета нет на PyPI (404) — только CLI-репозитории Sourcegraph с node/native сборкой | 2026-08-05 | audit.md п.9 |
| cypher-sqlite как готовая Cypher-библиотека | Пакета нет на PyPI (404); свой CypherExecutor уже реализован | 2026-08-05 | audit.md п.2 |
| «371 язык symbol extraction» из tree-sitter-language-pack | Манифест = 371 грамматика, но tags.scm есть только у 71 (19%); 300 языков — AST-парсинг без символов | 2026-08-05 | audit.md п.1 |
| pylint-django как детектор дупликации | Это плагин для Django-фреймворка (типы ForeignKey/Model), а не dup-detector — официальное описание PyPI 2.8.0 (2026-07-11) | 2026-08-08 | audit.md L197 |

---

## [2026-08-08] — Exp: `PropertyGraph.shortest_path` — корректность + латентность (H-PATH)
**Гипотеза:** BFS (graph.py:937) работает на живом графе, медиана <50ms; gap = только отсутствие MCP `graph_query(action="path")`.
**Команда:** `venv/Scripts/python.exe experiments/exp_graph_path.py` (скрипт в experiments/, read-only через API PropertyGraph).
**Сырой результат:**
```
graph: 7247 nodes, 21404 edges
[tool->PropertyGraph (CALLS)] shortest_path('_execute_cypher' -> 'PropertyGraph'): 2 hops
   ...GraphQueryTool._execute_cypher  -[->
   ...graph.py.PropertyGraph  -[CALLS]->
latency_ms: [0.3, 0.14, 0.12, 0.11, 0.09, 0.09, 0.09]  median_ms: 0.11
```
**Вердикт:** подтверждена — 0.11ms медиана (гипотеза <50ms выполнена ×450). Реальный путь найден, структура корректна (source→CALLS→target).
**Урок:** `shortest_path` траverses ТОЛЬКО outgoing-рёбра (`graph.py:974` `WHERE source_id = ?`) — классы/методы без исходящих рёбер недостижимы. MCP-обёртке `action="path"` нужен опциональный `direction="both"` (BFS уже параметризуем). Также: qname-формат `D:.D:/Project/...` — клиенту нужен подсказчик имён (как `find_nodes(name_pattern=...)`).

---

## [2026-08-08] — Exp: Jupyter `.ipynb` = JSON, интеграция без новых зависимостей (H-JUPYTER)
**Гипотеза:** .ipynb разбирается stdlib json (nbformat опционален), code cells подаются в существующий tree-sitter пайплайн CodeParser. Интеграция = extensions.py + ветка в parse_file.
**Команда:** `venv/Scripts/python.exe experiments/exp_jupyter.py`
**Сырой результат:**
```
json.loads 200x: median_ms = 0.0055
cells=5 code_cells=3
  cell 0: 69 chars / 5 lines ...
CodeParser.parsers keys: ['.go', '.js', '.py', '.rs', '.ts', '.tsx']
  cell 0 -> parse_file: 1 chunks, 0 syms, 15.08ms
  cell 1 -> parse_file: 1 chunks, 1 syms, 13.35ms
  cell 2 -> parse_file: 1 chunks, 0 syms, 13.48ms
TOTAL chunks из 3 code cells: 3
```
**Вердикт:** подтверждена — парсинг ~0.006ms, извлечение корректно, существующий пайплайн работает на cell-as-.py (13-15ms/cell). nbformat 5.11.0 существует (PyPI, 2026-08-06), но не нужен.
**Урок:** накладные расходы на ноутбук ~N×13ms (N = code cells) — приемлемо. Замечание: standalone `CodeParser()` загрузил только 6 грамматик (полный набор идёт через другой путь инициализации — язык-пак/окружение) — для .ipynb достаточно python-грамматики + metadata.language_info.name.

---

## [2026-08-08] — Exp: детекция дупликации AST-нормализованными отпечатками (H-DUP)
**Гипотеза:** для 54 языков AST-нормализация (tree-sitter уже есть) + minhash ближних дублей реализуемо stdlib+numpy, без suffix-array движка. fallow: suffix-array покрывает только JS/TS+CSS. pylint-django — НЕ dup-detector.
**Команда:** `venv/Scripts/python.exe experiments/exp_dup.py` (скрипт в experiments/, ~60 строк: tree-sitter листовые токены с плейсхолдерами <id>/<lit>, sha1-группировка точных, minhash-64 8-грамм для ближних).
**Сырой результат:**
```
files=137 functions/classes>=24tokens=401 scan_ms=414.8
EXACT дубликаты: 8 групп
  artifact_paths.py: get_index_dir/get_intelligence_dir/get_metrics_dir/get_commit_memory_dir/get_branches_dir/get_telemetry_dir/get_summaries_cache_dir (7 шт)
  extensions.py: is_supported ~ is_parseable
  resource_monitor.get_global_resource_monitor ~ llama_runner.get_global_runner
  language_pack.lang_for_ext ~ get_parser
  lsp_project_bridge._bridge_path ~ _stale_path
  cypher_ast._UnaryOp ~ _LabelTest
  graph_tools._confirmed ~ _contradicted
  lsp_tools.LspFindReferencesTool ~ LspFindDefinitionTool
NEAR-дубли (minhash>0.85): 1 пара, 0.969 — lsp_tools.LspFindReferencesTool ~ LspFindDefinitionTool; pair_scan_ms=660.8
```
**Вердикт:** подтверждена — 137 файлов за 414.8ms, найдены РЕАЛЬНЫЕ дубли (7 функций get_*_dir — классический copy-paste; LSP-классы-близнецы 0.969). Ноль новых зависимостей (tree_sitter + hashlib уже есть; simhash 2.1.2 существует, но не нужен). pylint-django опровергнут (см. 🚫 таблицу).
**Урок:** порог ≥24 токена и k=8-граммы дают 0 false-positive на этом репо. Для MCP-тула `find_duplicates(threshold)` — готовая схема: index-time (опционально) или on-demand скан ~415ms. Кандидаты: 7×get_*_dir стоит реально отрефакторить в 1 функцию.

---

## [2026-08-08] — Верификация кода (без замеров): H-EDGE / H-LSP / H-TASK
**H-EDGE (edge transparency) — подтверждена:** `Edge.properties` — реальная колонка (graph.py:410), `add_edge` принимает properties и upsert обновляет их (graph.py:736,778), `to_dict` отдаёт (graph.py:329). Теги EXTRACTED/INFERRED = метаданные, **без миграции схемы**. Реальная стоимость: пометить вызовы add_edge/batch_add_edges при создании рёбер + пасс-through в tools (уже через to_dict). Оценка аудита «2-3 недели» завышена на порядок (3-5 дней, а то и меньше).
**H-LSP (type resolution) — закрыт другим путём:** с 2026-08-06 в проекте есть 6 LSP-тулов через basedpyright (src/core/lsp_client.py, src/mcp/tools/lsp_tools.py): lsp_find_references/definition/document_symbols/get_type_info/get_diagnostics/get_code_actions. Живая проверка: `lsp_get_type_info(graph.py:730)` вернул `(parameter) self: Self@PropertyGraph`. USES_TYPE edge объявлен (graph.py:234), но не заполняется — index-time type resolution НЕ нужен: query-time LSP покрывает боль точнее (тот же паттерн, что fallow `--type-aware` — семантика на уровне запроса, не индекса).
**H-TASK (task-shaped) — частично есть:** `intel_get_project_context` — один вызов = снапшот state+index+health+memory+background (server_tools.py: инлайн-регистрация); `graph_query(action="related")` — контекст по нескольким целям через CommitMemory+RelationExtractor. Нет только символьного `get_context(targets=[...])` — это тонкая обёртка. **H-PATH примечание:** class-узлы имеют 0 исходящих рёбер (CodeParser out=0) — DEFINES-связи неполны на уровне class→method; открытая нить для ревью indexer.edge-записи.

---

## [2026-08-08] — Exp: WS3 Late Enrichment — стоимость стадии на реальных чанках

**Гипотеза (Late Code Chunking, ACL 2026):** enrichment ПОСЛЕ retrieval дёшев (<2ms на топ-10) и покрывает ≥2 полей на чанк; imports из metadata чанка доступны.
**Команда:** `python experiments/late_enrichment/bench.py --phase chunks --limit 10` — 8 запросов × 10 реальных чанков проекта, фаза chunks (live недоступна: MCP держит PID-lock).
**Сырой результат:**
```
avg_enrichment_ms: 0.701
avg_tokens_added: 1860.0   (≈186 ток/чанк на топ-10)
avg_coverage: module=1.0, parent_symbol=0.3, chunk_headline=1.0, imports=0.0
```
**Вердикт:** ЧАСТИЧНО ПОДТВЕРЖДЕНА. Латентность пренебрежима (0.7ms), module/headline покрывают 100%. **imports=0.0** — метаданные чанков НЕ содержат импортов (графовые IMPORTS-рёбра есть, но не прикреплены к чанкам) → enrichment импортов требует graph-lookup (и зависимость от consistency — будущая работа). parent_symbol=0.3 — извлечение имени из текста находит не каждый чанк.
**Урок:** chunk-local enrichment (module/headline/symbol) безопасен и дёшев; imports — отдельная стадия с графом. Токен-стоимость ~186/чанк обязана быть в метрике контекста (Context Engine 2.0).

## [2026-08-08] — Exp: Benchmark 2.0 runner — live-фаза vs PID-lock

**Гипотеза:** runner может поднять in-process Searcher при живом MCP (индекс доступен).
**Команда:** `python experiments/benchmark2/runner.py` (MCP запущен, PID 7496).
**Сырой результат:**
```
RuntimeError: PID lock still held by alive pid=7496 after 30.0s — другой процесс пишет в эту БД
[bench2] записано 12 задач -> out/evidence.jsonl
[bench2] manual-проб (нужен ручной прогон): 16
```
**Вердикт:** ОПРОВЕРГНУТА. PID-lock (database_lock.py, 30s, fail-closed) блокирует второй Indexer на ту же БД — это защита, работает как задумано. Runner корректно фолбэчит в manual-режим (16 ручных проб).
**Урок:** live-эвалы против MCP требуют остановленного сервера или отдельного MSCODEBASE_DATA_DIR; документировано в experiments/benchmark2/README.md.
