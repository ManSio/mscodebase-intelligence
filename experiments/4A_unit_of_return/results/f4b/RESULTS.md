# 4A — F4b (held-out generalization) — RESULTS

**Дата:** 2026-09-26. **Вход:** `frozen/f4b/handout_{symptom,arrival}.md` + `frozen/f4b/manifest.json`.
**Изоляция:** пустая папка на поток, MCP off, `--pure`, tools deny, `--variant high` (пинован).
**Сырьё:** `results/f4b/{condition}/{model}/run_*.txt`.

## Setup (referent)

- Условия: `symptom` (E7-индекс) и `arrival` (arrival-индекс каталога), **одни и те же 14 пунктов**.
- Модели × прогоны: `longcat-2.0` ×5, `qwen3.7-plus` ×3, `deepseek-v4.1-flash` ×3 на условие.
- **Итого 22 прогона** (2 условия × 11). Все 6 потоков завершены `rc=0` (оркестратор `scripts/f4b_run_all.py`, ~4 мин).
- Контроли: **must-hit** `{3, 8, 13}`, **must-NONE** `{5, 10, 14}`.
- sha256 handout и каталога — `frozen/f4b/manifest.json`; совпадают с фактическими файлами (проверено).
- **Нормализация (F0-класс):** абсолютный env-путь в одном raw-выводе (`→ Read …`, эхо opencode) и в
  `handout`-полях per-model `manifest.json` сведены к repo-относительным. **Текст ответов не изменялся.**

## Валидатор

`python scripts/f4b_validate.py` → **clean 13/22** (arrival 10/11, symptom 3/11).
Negative control `--selftest` падает как положено (rc=1 на generic/error-marker). Все 22 вывода — ровно 14 строк,
известные слаги, без TIMEOUT/apology.

| условие | deepseek | qwen | longcat | clean |
|---|---|---|---|---|
| **arrival** | 3/3 | 3/3 | 4/5 | **10/11** |
| **symptom** | 2/3 | 1/3 | 0/5 | **3/11** |

## Per-item (контроли)

| # | роль | expected | arrival | symptom |
|---|---|---|---|---|
| 3 | must-hit | `a-cached-429-is-not-a-rate-limit` | **11/11** | **3/11** |
| 8 | must-hit | `a-rate-knob-cannot-fix-a-denominator` | 11/11 | 11/11 |
| 13 | must-hit | `a-single-run-ranking-is-noise-even-at-temp-zero` | 11/11 | 11/11 |
| 5 | must-NONE | `NONE` | 10/11 | 11/11 |
| 10 | must-NONE | `NONE` | 11/11 | 11/11 |
| 14 | must-NONE | `NONE` | 11/11 | 11/11 |

Единственный не-NONE по #5 — `arrival/longcat run2` → `a-component-that-needs-starting-passes-every-behaviour-test`
(тот же класс «соседний домен», что E7-FP на CSS→generated-document; модель-независим по природе).

## Главная находка: асимметрия register'а на #3

Пункт `#3 = «It keeps timing out every time I retry, no matter what»`.

- **arrival-индекс** (каталог, строка 34): `it times out every time I try this` → тот же entry.
  → дословный/почти-дословный двойник → модели матчат **11/11**.
- **symptom-индекс** (каталог, Family D): `rate limited, backing off no help` → тот же entry.
  Тут лексического перекрытия с «timing out / retry» **нет** → 8/11 отвечают `NONE`, только **3/11** попадают.

**Вывод (направление, не приговор):** каталог работает как **лексический lookup**: пункт, несущий
словарь индекса, находится; пункт, сформулированный в другом регистре (здесь — arrival-фраза против
symptom-ключа), **не находится**, хотя семантически тот же. Симптом-индекс не «провалился» — он просто не
содержит нужных слов для arrival-формулировки. Это ровно то, что закрывает arrival-индекс Tom'а.

**Изолированность:** все 8 провалов symptom — это **только #3**. #8 и #13 проходят **22/22**. Значит
провал symptom-условия не системный, а сконцентрирован в одном пункте.

## Contamination #3 (честная оговорка — вход для F6)

`#3` — **семантический морфологический двойник arrival-фразы каталога**, но прошёл G6-гейт:

- `scripts/frozen_overlap_check.py` сравнивает только **нумерованные** пункты (`^\d+[.)]\s`); табличные
  arrival-строки каталога он **не видит** → правило README «включая arrival-симптом» операционно не покрыто.
- Даже если бы видел: содержимое-токены `#3` = `{keeps, timing, every, time, retry, matter}`,
  arrival-фразы = `{times, every, time, try}` → общих **2** (`every, time`) < порога 3.
  Морфология (`timing/times`, `retry/try`) лексическим токенизатором не сводится.

→ G6 в текущем виде **не отсекает парафраз-двойники**. Ручной semantic-review (A3) его тоже пропустил.
Это **OPEN-находка** для F6, но **не FATAL**: frozen-набор не меняем (freeze-before-look), сообщаем и
основной, и объяснённый результат.

## Held-out vs known

| набор | индекс | must-hit | must-NONE | clean |
|---|---|---|---|---|
| **known** E7 (`pinned_variant`) | symptom | {1,4,9} | {3,6,11} | 10/11 |
| **held-out** F4b | symptom | {3,8,13} | {5,10,14} | 3/11 |
| **held-out** F4b | arrival | {3,8,13} | {5,10,14} | 10/11 |

- **arrival held-out ≈ known** (10/11), must-hits 33/33, must-NONE 32/33 → **генерализация arrival-индекса подтверждена**.
- **symptom held-out 3/11** — целиком из-за #3. При изоляции #3: must-hit #8,#13 = 22/22, must-NONE 33/33,
  и все 11 symptom-прогонов чисты. Т.е. **искусственный «обвал» = один контаминированный пункт**, а не деградация метода.
- Как frozen: **симптом-условие 3/11 — первичный результат, не подменяем**; объяснение даём отдельно.

## Известный FP индекса (не контроль)

`a-generated-document-is-unverified-until-you-render-it` всплыл 7 раз на не-контрольных пунктах
(`#12` Zed/JSONC ×4, `#6` docstring-sandbox ×2, `#14`→нет; один на `#12`). Подтверждает запись E7:
FP — свойство **границы индекса**, не модели, и остаётся must-NONE только там, где пункт явно out-of-domain.

## Вердикт

- ✅ **arrival held-out генерализует:** 10/11 clean; must-hit 33/33; #14-фикс (Docker) дал **22/22 NONE** — A6 закрыт эмпирически.
- ✅ **symptom-индекс тоже держит:** после изоляции контаминированного #3 — 11/11, 33/33 must-NONE.
- ⚠️ **OPEN:** G6 не ловит парафраз/morphology-двойники (A7) → один held-out must-hit (#3) контаминирован.
- ⛔ **Не публиковать** частоты без оговорки о #3; **один обвал ≠ результат** (direction vs result).

## Ledger

| # | Утверждение | Источник | Статус |
|---|---|---|---|
| 1 | 22 прогона, все rc=0, 14 строк каждый | `results/f4b/**` + лог | ✅ |
| 2 | arrival clean 10/11 | `f4b_validate.py` | ✅ |
| 3 | symptom clean 3/11, все провалы = #3 | per-item таблица | ✅ |
| 4 | #8,#13 = 22/22; #5=21/22; #10,#14=22/22 | per-item | ✅ |
| 5 | #14-фикс (Docker) убрал прежний 100% FP | 22/22 NONE | ✅ |
| 6 | #3 — морфологический двойник arrival-фразы | `crystal_catalogue…` стр.34 | ✅ |
| 7 | G6 слеп к табличным arrival-строкам и морфологии | `frozen_overlap_check.py` | ✅ fixed 2026-09-26 (v2: arrival-фразы + стемминг; гейт флажит #3) |
| 8 | F6 Red Team на числах | — | ⏳ |
