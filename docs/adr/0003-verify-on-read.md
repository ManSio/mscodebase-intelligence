# ADR-0003: Verify-On-Read — ленивая валидация ACTIVE-узлов при извлечении (Вариант B)

**Status:** ⏳ Proposed — ожидает одобрения владельца (реализация начнётся после явного «одобряю», §1 Шаг 4)
**Дата:** 2026-08-11
**Автор:** агент (по итогам Exp 1-R и архитектурной спецификации владельца)

## Context

ADR-0002 ввёл статус-модель `ACTIVE | VERIFIED | REFUTED` (`docs/adr/0002-retraction-receipt.md`),
инструмент `intel_retract_memory_node` и фильтрацию REFUTED при чтении
(`store.py:94-124`, `layer.py:914-916`, L918+). Вектор проверки — **на стороне
записи/отклика**: ложь отзывается только если агент её заметил и вызвал отзыв.

Exp 1-R (`EXPERIMENTS_LOG#2026-08-11-1-R`, аналог v3 с ретракцией, 50 фактов):
- ретракция удаляет **опровержимую** часть заражения: persistent false 25→3 (-88%),
  memory_first adoption 1.0→0.12, токены контекста -45%;
- но **SILENT-факты неотзывны**: adoption честного агента застрял на **0.12** (3/25) —
  код молчит, отозвать нечем, а неверная запись продолжает читаться в каждую сессию.

Вывод: до нуля заражение доведёт только сдвиг вектора проверки с «момента
исполнения/откликов» на **момент извлечения из памяти (retrieval)** — проверка
до формирования системного промпта.

## Decision (архитектура владельца, Вариант B)

### Поток Verify-On-Read

```
load_memory() ──► Retrieval candidate ──► Is Node UNVERIFIED/SILENT?
                                                    │
                                     ┌──────────────┴──────────────┐
                                     ▼                             ▼
                                [NO: Active]                 [YES: Lazy Check]
                                     │                             │
                                     ▼                      AST / File Check
                               Include Context                     │
                                                    ┌──────────────┴──────────────┐
                                                    ▼                             ▼
                                              [Found in Code]           [Not Found]
                                                    │                             │
                                              Status: VERIFIED            Status: REFUTED
                                                    │                             │
                                             Include Context             Exclude & Retract
```

(Схема владельца. «UNVERIFIED/SILENT» = ACTIVE-узлы: любой ACTIVE-узел по
определению не проверен; REFUTED уже скрыт фильтром ADR-0002, VERIFIED — пропуск.)

### Три ключевых положения

1. **Lazy Validation Layer.** При вызове `load_memory()` ACTIVE-узлы проходят
   лёгкую ленивую проверку на чувствительность локального контекста:
   - **файлы** — `file:`/`dir:` пути из `data`/`claim` → `Path.exists()`;
   - **импорты** — имена модулей → проверка по импортам кодовой базы
     (переиспользование `CodeParser._extract_imports_recursive`, `parser.py:1362`,
     или PropertyGraph `IMPORTS`-рёбер);
   - **конфиг-ключи** — имена ключей → поиск в `.env`/`.env.example`/`config`.
2. **Автоматический переход в REFUTED.** При нечувствительности среды
   (ни один якорь не найден) узел помечается `status=REFUTED` с причиной
   **`SILENT_ABSENCE_ON_READ`** и отсекается **до формирования системного
   промпта**. Переход пишется тем же путём, что и ручной отзыв
   (`retract_reason`/`retracted_at` + маркер `retract_source="verify_on_read"`) —
   переходы видны в аудите через `include_retracted=True`.
3. **Latency Budget & Caching.** Результаты Verify-On-Read кэшируются **по хешу
   коммита** (`git rev-parse HEAD`; fallback без git — максимальный mtime
   `src/`-дерева): неизменившийся репозиторий не перепроверяется между сессиями.
   Кэш — `verify_cache.json` в `intelligence/` (рядом с `project_memory.json`),
   ключ `HEAD → {node_id: verdict}`. Смена HEAD → перепроверка ACTIVE-узлов
   (cache miss). **Бюджет задержки:** ≤5 мс на узел, общий ≤50 мс; cache hit ≈ 0 мс;
   при превышении бюджета — пропустить оставшиеся проверки (оставить ACTIVE),
   залогировать (graceful degradation).

### Хук и границы

- **Хук:** `intel_get_project_memory` (`layer.py:914-916`) — применение слоя ДО
  возврата результата. `store.load_memory()` остаётся чистым фильтром
  (внутренние чтения — dedup `intel_auto_collect_adrs` с `include_retracted=True`
  — не триггерят проверку).
- **VERIFIED persist**: найденные узлы получают `status=VERIFIED` — вторая сессия
  на том же HEAD не перепроверяет их (cache + статус).
- **Консервативность (INCONCLUSIVE)**: узел без **ни одного** checkable-якоря
  (в `data`/`claim` нет `file:`/имени модуля/конфиг-ключа) не может быть
  «не найден» осмысленно — он получает вердикт INCONCLUSIVE, **остаётся ACTIVE**
  и включается как раньше. Это защита от ложных REFUTED истинных фактов о
  внешнем окружении (Redis/Celery — код молчит, но факт верен). Без этой ветки
  verify-on-read превратится в машину ложных отзывов.

## Alternatives considered

### Вариант C: TTL для `intel_auto_collect_adrs`
- **Как работает:** срок жизни для авто-собранных ADR; по истечении — исключение.
- **Минусы:** не закрывает SILENT-факты из других секций (known_issues/tech_debt);
  TTL «молча убивает» и полезные записи без верификации (противоречит ADR-0002
  «невозможно тихо скрыть»).
- **Вердикт:** ортогонален B; возможен позже как дополнение для stale-VERIFIED.

### B на полном семантическом индексе (search_code против каждого claim)
- **Как работает:** каждый ACTIVE-узел сверяется через семантический поиск.
- **Плюсы:** ловит и «присутствие по смыслу», не только наличие якоря.
- **Минусы:** дорого на чтении (1.2с/запрос), латентность неприемлема в hot path
  `intel_get_project_memory`; даёт вероятностные вердикты.
- **Вердикт:** для presence-claims достаточно лёгкой проверки (файлы/импорты/
  конфиг-ключи); полный индекс — будущая стадия, если INCONCLUSIVE-доля окажется
  высокой (метрика в guard).

### No-op: полагаться только на ручную ретракцию
- **Минусы:** Exp 1-R — adoption честного застревает на 0.12; SILENT-факты
  читаются вечно.
- **Вердикт:** отклонён — цель владельца «заражение к нулю» недостижима.

## Consequences

- **Приёмка (Definition of Done):** Exp-аналог 1-R с включённым Verify-On-Read →
  adoption честного агента на SILENT-фактах **0.0** (3/3 → REFUTED
  SILENT_ABSENCE_ON_READ); 0 ложных REFUTED среди TRUE-фактов; латентность чтения
  в бюджете.
- **Backward-compat:** ACTIVE-узлы без якорей (INCONCLUSIVE) ведут себя как раньше;
  существующие VERIFIED/REFUTED не трогаются; кэш — новый файл, не мешает.
- **Невозможно тихо скрыть:** авто-отзывы видны в аудите (SILENT_ABSENCE_ON_READ +
  retract_source), как и ручные.
- **Риск ложных отзывов** истинных фактов о внешнем окружении — закрыт
  INCONCLUSIVE-веткой (см. Open Question 1).
- **VERIFIED не деградирует при смене HEAD** (v1): stale-VERIFIED после изменения
  кода — отдельная задача (TTL/перепроверка VERIFIED), не входит в объём B.

## Impact

| Файл | Изменение |
|---|---|
| `src/core/intelligence/verify_on_read.py` | **новый** — Lazy Validation Layer: извлечение якорей из node (file:/import/env-key), проверка по кодовой базе, вердикты FOUND/NOT_FOUND/INCONCLUSIVE, запись переходов, кэш по HEAD; guard против абсолютных/вложенных путей в `_PATH_RE` |
| `src/core/intelligence/layer.py` | хук слоя в `intel_get_project_memory` (L914-916); переходы пишутся через общий write-путь (тот же `_write_lock`); **write-time anchor capture** в `intel_add_memory_node` и `intel_auto_collect_adrs` (типизированные якоря `data.anchors` из синтаксиса claim/data) |
| `src/core/intelligence/tools_reg.py` | (опц.) флаг `verify_on_read` в `intel_get_project_memory` для отладки |
| `tests/test_verify_on_read.py` | **новый** — юнит: FOUND→VERIFIED, NOT_FOUND→REFUTED(SILENT_ABSENCE_ON_READ), INCONCLUSIVE→ACTIVE, кэш по HEAD, бюджет-таймаут |
| `experiments/context_engine/memory_contamination_verify.py` | **новый** — Exp 1-V: аналог 1-R с verify-on-read (приёмка: adoption → 0.0) |

Evidence-источники (лёгкая проверка): `file:`→`Path.exists()`; импорты →
`CodeParser._extract_imports_recursive` (parser.py:1362) / PropertyGraph IMPORTS;
конфиг-ключи → `.env`/`.env.example`.

## Status

✅ **Accepted (2026-08-11)** — одобрено владельцем с трёхуровневой классификацией
(VERIFIED / REFUTED / INCONCLUSIVE), ключом кэша `hash(node_id + commit_sha)`
(per-node инвалидация без TTL) и `verify_on_read=True` по умолчанию (бюджет
≤50мс + graceful degradation). Реализация (Lazy Validation Layer + кэш + хук +
Exp 1-V) — в том же коммите, что и этот ADR.

## Open Questions (закрыты решениями владельца 2026-08-11)

1. **INCONCLUSIVE-ветка — ОДОБРЕНО.** Авто-отзыв только при прямом отрицательном
   тесте проверяемого якоря (файл/модуль указан, но не существует).
2. **Кэш `hash(node_id + commit_sha)` — УТОЧНЕНО.** HEAD не изменился → cache hit
   ~0мс; HEAD сдвинулся → кэш инвалидируется только для этой ноды (естественная
   per-node инвалидация, без TTL-логики и без липкого VERIFIED).
3. **Дефолт ON — ОДОБРЕНО** с двумя предохранителями: бюджет ≤50мс на проход;
   при превышении необработанные узлы → INCONCLUSIVE и передаются в контекст
   без отзыва.

## Temporal

- **T+0:** Verify-On-Read на чтении, кэш по HEAD, INCONCLUSIVE-защита — обратно совместимо.
- **T+0 (репликация, 2026-08-11, facts v4, seed=7):** ✅ ВОСПРОИЗВЕДЕНО на независимых данных (EXP#2026-08-11-1-V-REP): adoption честного 0.0 (как 1-V), **0 ложных REFUTED TRUE** при корректно типизированных якорях (16 VERIFIED + 9 INCONCLUSIVE из 25 TRUE; в 1-V было 7 — артефакты наивной типизации, закрыты write-time capture), present-trap слепота воспроизведена (memory_first 0.24 vs 0.16, ловят только честный агент contra-анализом), steady-state 0.6ms. Главный вывод 1-V — свойство VerifyOnRead, не данных.
- **T+30d (измерено 2026-08-11, Exp 1-V):** adoption честного агента → **0.0** (v3/1-R: 0.12) —
  цель «заражение к нулю» достигнута; steady-state латентность **0.6мс** (cache hit, бюджет ≤50мс соблюдён;
  первый проход после смены HEAD платит fingerprint ~80мс один раз). Ограничения, зафиксированные
  экспериментом: (1) presence-проверка не ловит present-trap (токен реально импортируется, но не у этого
  субъекта) — memory_first adoption 0.16 vs 1-R 0.12; ловит их только честный агент (code_first,
  contra-анализ) — комбинация verify + честный агент даёт 0.0; (2) наивная типизация голых токенов
  паттернов в import-якоря даёт 7/25 ложных REFUTED TRUE (конфиг-строки, методы слоя, подмодуль
  mcp.server.fastmcp, бинарник basedpyright). **Закрыто write-time anchor capture (2026-08-11):**
  `intel_add_memory_node`/`intel_auto_collect_adrs` извлекают ТИПИЗИРОВАННЫЕ якоря (file:/import/env
  из синтаксиса claim/data) и хранят в `data.anchors` при записи; verify-on-read проверяет их;
  голые токены без синтаксиса якорями не становятся (INCONCLUSIVE, без ложных отзывов).
- **T+180d:** если auto_collect_adrs продолжит генерировать stale — Вариант C (TTL) поверх статус-модели;
  семантический слой (полный поиск) — если INCONCLUSIVE-доля высокая.
