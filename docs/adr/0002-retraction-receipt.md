# ADR-0002: RetractionReceipt — системный отзыв SILENT-фактов из Project Memory

**Status:** ✅ Accepted (2026-08-11, одобрено владельцем с дополнением VERIFIED; реализация — см. `tests/test_memory_retraction.py` + `intel_retract_memory_node`)
**Дата:** 2026-08-11
**Автор:** агент (по итогам эксперимента Memory Contamination, `EXPERIMENTS_LOG#2026-08-11`)

## Context

Project Memory — **add-only** хранилище. Данные живут в
`<data_root>/projects/<hash>/intelligence/project_memory.json` (`store.py:68-71`,
`get_intelligence_dir` из `artifact_paths.py`). Схема узла (`layer.py:951-956`):

```python
{
    "node_id":   "NODE-XXXXXXXXXX",
    "section":   "adrs | known_issues | tech_debt | failed_attempts",
    "timestamp": "YYYY-MM-DD HH:MM:SS",
    "data":      {...},            # произвольный JSON
}
```

Три пути записи, все — только аппенд:

1. `intel_add_memory_node` (`layer.py:918-964`) — `nodes.append(new_node)` (L957), миграция
   старого dict-формата в плоский список (L936-949), защита `_AsyncLockAdapter(self._write_lock)` (L934).
2. `intel_auto_collect_adrs` (`layer.py:1069-1128`) — дописывает ADR из git-лога (L1121-1128).
3. `intel_log_incident` (`layer.py:818-845`) — отдельный файл `incidents.json`, имеет `success: bool`,
   но проектная память (в отличие от инцидентов) статуса узла **не имеет**.

Чтение — без фильтрации: `intel_get_project_memory` (`layer.py:914-916`) →
`store.load_memory()` (`store.py:94-124`) возвращает **все** узлы. Инструментов
отзыва/пометки не существует: `grep-0 delete/refute` по memory-инструментам.

## Problem

Кумулятивное заражение памяти SILENT-фактами. Эксперимент Memory Contamination
(2026-08-11, 3 прогона, детерминированный прокси-агент, изолированный
`IntelligenceStore(tempdir)`):

| Метрика | v1 (N=24) | v2 (N=24, репликация) | v3 (N=50, мутационный) | Смысл |
|---|---|---|---|---|
| correction_capability (code_first) | 1.0 | 1.0 | — | честный агент при явном CONTRADICT всегда выбирает CODE |
| adoption (memory_first) | 1.0 | 1.0 | — | **100%** — «ленивый» агент принимает любую память, противоречие не защищает |
| adoption (A_cf) | — | — | **0.12** | **12%** — даже честный агент заражён: код молчит (SILENT), память побеждает |
| memory_confidence_effect | 4 | 4 | — | SILENT-факт превращает честный UNKNOWN в уверенный ложный ответ |

Ключевые выводы:
- **Отзыв невозможен системно:** add-only + отсутствие инструмента ретракции —
  даже `would_refute=1` (агент честный) не реализуемо в текущей архитектуре.
- **Заражение кумулятивно:** найденная ложь не отзывается, stale-ADR от
  `intel_auto_collect_adrs` остаются навсегда; память ×22 токенов контекста
  без выигрыша в точности.
- **Слепой агент:** при 100% adoption (memory_first) любая запись, однажды
  попавшая в память, становится фактом для всех последующих сессий.

Решение, рекомендованное экспериментом (урок Exp 1, п.2): retraction-статус
записи (VERIFIED/REFUTED, владелец: RetractionReceipt) + фильтрация REFUTED
при чтении + verify-on-read.

## Decision

**Вариант A — RetractionReceipt** (рекомендация агента; финальное решение — за владельцем).

1. **Поле `status` в узле памяти.** Три значения с явной семантикой:
   - `ACTIVE` — запись сделана, **не проверена** против кода (по умолчанию);
   - `VERIFIED` — **проверено против кода**: агент явно подтвердил факт
     (см. OWP: lifecycle `VERIFIED → REFUTED`, а не `ACTIVE → REFUTED`);
   - `REFUTED` — отозвано (терминальный статус).

   Узел отзыва не удаляется из файла (аппенд-модель сохраняется), а помечается —
   это сохраняет аудит-след «было сказано → было проверено → было опровергнуто».
2. **Запись статуса.** `intel_add_memory_node(section, data_json, status="ACTIVE")`
   принимает `ACTIVE` (по умолчанию) или `VERIFIED` — явное подтверждение агента,
   что факт проверен против кода. `REFUTED` при записи **запрещён** — только
   через инструмент отзыва (аудит-след не обходится).
3. **Инструмент `intel_retract_memory_node(node_id, reason)`.** Единственный
   легитимный путь перевода узла (ACTIVE или VERIFIED) в `REFUTED`.
   Обязательный параметр `reason` — причина отзыва; без неё инструмент
   отказывает. Каждая ретракция фиксирует `retract_reason` + `retracted_at`.
   Повторный отзыв уже REFUTED-узла запрещён (первичная причина остаётся).
4. **Фильтрация при чтении.** `store.load_memory()` и
   `intel_get_project_memory()` исключают узлы со `status == REFUTED` из
   результата по умолчанию. Полный список (включая REFUTED) доступен отдельно
   (флаг `include_retracted=True`) — для аудита и отладки.
5. **verify-on-read остаётся будущей работой** (см. Alternatives B) — не входит
   в объём Варианта A.

## Alternatives considered

### Вариант B: verify-on-read (авто-ретракция по evidence)
- **Как работает:** при чтении каждый узел сверяется с кодом/индексом; CONTRADICT →
  автоматический REFUTED.
- **Плюсы:** закрывает и «тихий» путь (агент не обязан сам отзывать).
- **Минусы:** высокая стоимость на чтение (поиск + верификация на каждый узел),
  зависимость от качества индекса, риск ложных ретракций; требует LLM/поиска
  в hot path `intel_get_project_memory`.
- **Вердикт:** отложить — дорого и хрупко; Вариант A создаёт статус-модель,
  на которую B ляжет поверх позже.

### Вариант C: гибрид A + TTL для `intel_auto_collect_adrs`
- **Как работает:** A + автоматический срок жизни для авто-собранных ADR.
- **Плюсы:** закрывает конкретный источник stale (auto_collect_adrs).
- **Минусы:** TTL «молча убивает» и полезные записи без явного отзыва —
  противоречит требованию «невозможно тихо скрыть».
- **Вердикт:** TTL рассматривать отдельной задачей, если auto_collect_adrs
  покажет высокий stale-rate после внедрения A.

## Consequences

- **Backward-compat:** узлы без поля `status` (всё наследие) интерпретируются
  как `ACTIVE` — существующие данные не ломаются, миграция не нужна. Поле
  доустанавливается лениво при чтении (дефолт) и явно при следующей записи
  (`intel_add_memory_node`, `intel_auto_collect_adrs` пишут `status` явно).
- **Второй писатель → TOCTOU закрывается:** `intel_retract_memory_node` — новый
  писатель в `project_memory.json`. Весь read-modify-write (load → mutate → save)
  в `intel_add_memory_node` и `intel_retract_memory_node` выполняется под одним
  `self._write_lock` целиком (в существующем коде лок закрывал только load —
  два конкурентных append теряли записи).
- **Dedup видит отозванное:** `intel_auto_collect_adrs` сверяет существующие
  ADR через `load_memory(include_retracted=True)` — отозванный ADR не собирается
  повторно следующим прогоном.
- **Невозможно тихо скрыть ошибку:** отзыв требует `reason`; каждая ретракция
  оставляет REFUTED-запись с причиной и временем — память не «забывает», она
  документирует опровержение (это же кормит аудит-журнал и будущий verify-on-read).
- **Защита от злоупотребления:** `REFUTED` фильтруется на чтении, но узел
  физически сохранён — «переписать историю» нельзя, только пометить.
- **Поведение:** `intel_get_project_memory` не меняет сигнатуру; меняется
  содержимое (REFUTED скрыты). `intel_add_memory_node`/`intel_auto_collect_adrs`
  пишут `status: ACTIVE` явно.

## Impact

| Файл | Изменение |
|---|---|
| `src/core/intelligence/store.py` | дефолт `status=ACTIVE` при чтении (L94-124); фильтр REFUTED; опция `include_retracted` |
| `src/core/intelligence/layer.py` | `intel_retract_memory_node(node_id, reason)`; параметр `status` в `intel_add_memory_node` (L918); фильтрация в `intel_get_project_memory` (L914-916); dedup с `include_retracted=True` в `intel_auto_collect_adrs` (L1071); `status: ACTIVE` в схеме авто-ADR (L1103) |
| `src/core/intelligence/tools_reg.py` | регистрация `intel_retract_memory_node` (рядом с L373-376); `status` в `add_memory_node`; `include_retracted` в `get_project_memory` |
| `tests/test_memory_retraction.py` | новый: store-фильтрация + layer-ретракция (отказ без reason, повторный отзыв, VERIFIED→REFUTED) + конкурентность (add/retract без потери записей) |

## Status

✅ **Accepted (2026-08-11)** — одобрено владельцем с дополнением: `VERIFIED`
добавлен как третий статус (явное подтверждение проверки против кода; OWP
lifecycle `VERIFIED → REFUTED`, а не `ACTIVE → REFUTED`). Открытый вопрос
закрыт решением владельца — трёхзначная модель принята. Реализация Варианта A
(store + инструмент + фильтрация + тесты) — в том же коммите, что и этот ADR.

## Temporal

- **T+0:** three-статусная модель, zero миграций, фильтрация при чтении — обратно совместимо.
- **T+30d (измерено 2026-08-11, Exp 1-R):** ретракция удаляет ОПРОВЕРЖИМУЮ часть заражения: persistent false-контаминация 25→3 (-88%), adoption memory_first 1.0→0.12 (защита «ленивого» агента), токены контекста -45%; 22/22 would_refute реализованы системно (corr_cap=1.0). **Прогноз «adoption честного → 0» уточнён:** SILENT-факты неотзывны без проверки против кода — adoption честного остаётся 0.12; до 0 доведёт verify-on-read (Вариант B), нацеленный на остаточные SILENT-факты.
- **T+180d:** если auto_collect_adrs продолжит генерировать stale — переоткрыть ADR для Варианта C (TTL) или B (verify-on-read) поверх статус-модели; B — единственный путь к нулю SILENT-заражения.
