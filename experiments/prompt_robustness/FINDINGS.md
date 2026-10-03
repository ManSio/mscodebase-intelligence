# FINDINGS — prompt_robustness, полный живой прогон

Дата: 2026-10-03. Транспорт: `cli` (opencode), `--variant high`, 3 base-повтора.

## Идентичность прогона

| Параметр | Значение |
|---|---|
| dataset sha256 | `72ffdb58e0bc850de82cdf70c13c21a36c0f4b46988cab8982b98d6d0977c4e1` |
| instruction sha256 | `bba27901d4193d56…` (префикс) |
| Модели | longcat-2.0, qwen3.7-plus, deepseek-v4.1-flash |
| Вызовов | 360 (120 на модель: 60 RU + 60 EN) |
| Порог / мин. знаменатель | 0.90 / 10 |
| Wall-clock | 102 мин (~17 с/вызов) |
| Артефакт | `results/live_full.json` |

## Результаты (перевыведены из сырых `rows`, расхождений 0)

| Модель | Язык | base_acc | inv given base_ok | inv overall | seed | abstain | invalid | Вердикт |
|---|---|---|---|---|---|---|---|---|
| longcat-2.0 | ru | 1.0 | 1.0 (30/30) | 1.0 | 1.0 (10) | 1 | 0 | PASS |
| longcat-2.0 | en | 0.9 | 1.0 (27/27) | 0.9 | 0.9 (10) | 0 | 0 | PASS |
| qwen3.7-plus | ru | 1.0 | 1.0 (30/30) | 1.0 | 1.0 (10) | 0 | 0 | PASS |
| qwen3.7-plus | en | 1.0 | 1.0 (30/30) | 1.0 | 1.0 (10) | 0 | 0 | PASS |
| deepseek-v4.1-flash | ru | 0.9 | 1.0 (27/27) | 0.9333 | 0.9 (10) | 0 | 0 | PASS |
| deepseek-v4.1-flash | en | 0.9 | 1.0 (27/27) | 1.0 | 0.9 (10) | 0 | 0 | PASS |

`served_models_observed` совпал с запрошенными для всех трёх моделей.

## НАХОДКА 1 (критично к публикации): все впады ниже 1.0 — дефект матчера, не поведение модели

Единственный кейс, давший хоть какой-то провал, — `q_http_404` (ось `meaning_fact`).
Алиасы: `не найдено`, `not found`, `не обнаружено`, `не найден`, `resource not found`.

Все 8 строк, помеченных `matched=False`, — **семантически верные ответы**:

| Модель/рука | Ответ модели | Почему не совпало |
|---|---|---|
| longcat/en/base2 | `…the server could not find the requested resource.` | есть `could not find`, нет `not found` |
| deepseek/ru/base2 | `…сервер не нашёл запрошенный ресурс.` | есть `не нашёл`, нет `не найден` |
| deepseek/ru/p1 | `…сервер не смог найти запрошенный ресурс.` | нет ни одного алиаса |
| deepseek/en/base0 | `…could not be found on the server.` | нет `not found` |
| deepseek/en/base1, p0, p1, p2 | `…could not find…` | нет `not found` |

Контроль отрицательный (детектор не ловит мусор): «404 = Не авторизован», «404 means Unauthorized»,
«404 — это ошибка 500» → `matched=False` во всех трёх.

Диагностика (НЕ правка замороженного набора): +6 алиасов
(`could not be found`, `could not find`, `не нашёл`, `не нашла`, `не нашли`, `не смог найти`)
переключают все 8 строк в `matched=True` при **0 ложных срабатываниях**.

**Следствие.** `base_acc=0.9`, `seed=0.9`, `inv_overall=0.9333` измеряют не модель,
аsubstring-матчер. Публиковать их как неустойчивость моделей нельзя.
Вери��икты PASS от этого не изменились (все и так ≥ 0.90), но подпороговые числа недействительны.
Требуется **dataset v3** с расширенными алиасами и повторный замер. Версию v2 не правим:
правка после первого взгляда на результат — hindsight (§17).

## НАХОДКА 2: бинарный вердикт грубее метрики

Planted-контроль ломает 1 строку из 30 → `invariance = 0.9667`, что **выше** порога 0.90,
поэтому вердикт остаётся `PASS`. Метрика ломание видит (видна точная строка), бинарный гейт — нет.
При знаменателе 30 порог 0.90 срабатывает только на ≥3 сломанных строках.
Вывод: `PASS` означает «падения ниже 0.90 не обнаружено», а не «неустойчивости нет».

## НАХОДКА 3: один отказ из 360

`longcat-2.0/ru/q_python_release_year/base0` → `I don't know.` (0.28 % вызовов).
Влияния на вердикт не оказало: 2 оставшихся повтора ответили верно, base_accuracy = 1.0.

## Чего НЕ установлено

- Поведения при инвариантности < 0.90 не наблюдалось ни у одной модели — выводов о «robust/fragile» нет.
- `q_gradient_descent_direction` (исключён из агрегата) не оценивался: нет judge.
- `system_fingerprint` от CLI недоступен; версия провайдера не зафиксирована.

## Воспроизведение

```bash
python -m pytest experiments/prompt_robustness/test_harness_sanity.py -q      # 39 passed
python experiments/prompt_robustness/run_experiment.py --transport oracle   --out results/control_oracle.json
python experiments/prompt_robustness/run_experiment.py --transport planted  --out results/control_planted.json
python experiments/prompt_robustness/run_experiment.py --transport cli --repeats 3 --out results/live_full.json
```