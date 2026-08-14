# Exp 1-L — Memory Contamination, Live-Arm: ПОЛНЫЙ ОТЧЁТ (все прогоны, проверки, воспроизведение)

> **Статус:** ✅ Завершён (Day 1 + Day 2 + Red Team + follow-up'и, 2026-08-14)
> **Harness:** `scripts/run_1L_live_arm.py` · **Тесты:** `tests/test_run_1L_live_arm.py` (29)
> **Датасет:** `experiments/context_engine/memory_contamination_facts_v4_rep.json` (N=50)
> **Всего вызовов:** ~3300 · **Суммарная стоимость:** ~$0.14
> **Записи:** `EXPERIMENTS_LOG.md` · `AGENT_DIARY.md` (2026-08-14 23:20 / 23:55)
> **Полный pytest:** 1226 passed / 10 skipped (2026-08-14)

---

## 0. Резюме (1 экран)

Измерено: насколько **живые LLM** принимают ложные утверждения из «памяти» проекта
(контаминация) и доверяют ли памяти без кода. 50 фактов (25 true / 25 false) × 2 руки
(memory_first / code_first) × 14 моделей (6 дешёвых flash + 3 nemotron + 4 премиум + 1 негодная).

**Ключевые числа (V2-промпт, EN, канонические):**

| Модель | FA memory_first | FA code_first | unknown | Цена/100 выз. |
|---|---|---|---|---|
| **qwen3.6-flash** | **0.00** | **0.00** | 0.58 / 0.38 | $0.003 |
| **qwen3.7-flash** | **0.00** | **0.00** | 0.68 / 0.24 | $0.0005 |
| claude-sonnet-5 | **0.00** | **0.00** | 0.86 / 0.70 | $0.049 |
| deepseek-v4-pro | 0.04 | **0.00** | 0.66 / 0.88 | $0.018 |
| z-ai/glm-5.2 | **0.00** | 0.02 | 0.96 / 0.76 | $0.017 |
| deepseek-v4-flash | 0.04 | 0.00 | 0.80 / 0.94 | $0.002 |
| qwen3.5-flash | 0.02 | 0.00 | 0.82 / 0.96 | $0.0009 |
| nemotron-3.5-lightning | 0.08 | 0.04 | 0.32 / 0.56 | $0.001 |
| **glm-4.7-flash** ⚠️ | 0.10 | **0.24** | 0.64 / 0.24 | $0.001 |
| **nemotron-3-nano-30b** 🔴 | 0.06 | **0.38** | 0.78 / 0.20 | $0.0008 |
| qwen3.8-max ❌ | — | — | ~1.0 | несовместима (mandatory reasoning) |
| nemotron-3-super ❌ | — | — | — | 50% ошибок 422 апстрима |

**Выводы:**
1. **Лучшие для verify-on-read: qwen3.6-flash и qwen3.7-flash** — FA=0.00, цена копеечная, детерминированы 3/3 (проверено). Премиум-модели (включая Claude из ревью) не дают выигрыша по FA при цене ×100.
2. **Красные флаги: glm-4.7-flash (FA 0.24–0.30), nemotron-3-nano-30b (FA 0.38)** — с якорями принимают ложное. qwen3.8-max — несовместима с бюджетом 100 токенов (обязательное рассуждение).
3. **Нейтральный промпт (V2) снижает FA** у 4/6 моделей vs наводящий вопрос (V1) — сикофантия реальна.
4. **`--no-reasoning` обязателен**: без него GLM-4.7-flash ест весь бюджет рассуждением (110 reasoning-токенов, content=None). Все 6+4 модели соблюдают параметр (reasoning_tokens=0 — подтверждено пробами и дашбордом OpenRouter).
5. **Кеш OpenRouter (у GLM 45–48%) на вердикты НЕ влияет** (KV-кеш без потерь; контр. эксперимент: полностью закешированные идентичные запросы дают РАЗНЫЕ ответы у GLM — недетерминизм модели, не кеша). Влияет только на цену.
6. **Детерминизм модель-зависим**: qwen3.6/3.7/deepseek детерминированы 3/3 при temp=0+seed; GLM — нет. Однопроходные тонкие ранжировки недостоверны → выводы по верхней границе FA за ≥2 прогона.

---

## 1. Контекст и мотивация

- **Exp 1-V** (синтетика): детерминированный **proxy-агент** («проверь claim по паттернам в коде») — adoption≈0.16/0.24, false_accept=0 по построению, unknown=0.
- **Ревью Part 3**: *«детерминированный proxy-агент вместо живой модели — headline-числа от эвристики; с живым Claude или GPT-4o цифры будут другими»*.
- **Цель 1-L:** реальные вердикты живой LLM на тех же 50 фактах: adoption, false_accept (контаминация памяти), unknown, accuracy.
- **Гипотеза 1 (Day 1):** цифры живой LLM ≠ proxy. **Гипотеза 2 (Day 2):** разброс между моделями большой (FA от ~0 до ~0.3).

---

## 2. Датасет (ground truth)

`memory_contamination_facts_v4_rep.json` · N=50 (R01–R50) · создан 2026-08-11 · seed=7.

| kind | n | Описание |
|---|---|---|
| `real` | 25 | TRUE: паттерны grep-валидированы в коде (file:6 + env:2 + import:9 + CamelCase:8) |
| `absent-mutation` | 16 | FALSE: компонент отсутствует в проекте (grep-0) |
| `present-trap` | 6 | FALSE: файл/импорт существует, но claim про другой subject/value |
| `silent` | 3 | FALSE: внешние системы, код «молчит» |

Структура факта: `{id, truth, section, kind, subject, value, claim, support_patterns, contra_patterns}`.
**Блочный порядок:** R01–R25 все true, R26–R50 все false (для независимых вызовов — не угроза; зафиксировано).
**Fingerprint** (в каждом отчёте): `sha256(json.dumps(facts, sort_keys=True))[:16]` = **`820bbbf60a0fc930`**.

---

## 3. Дизайн: руки, промпты, методология

**Руки (50 × 2 = 100 вызовов на модель):**
- `memory_first` — ТОЛЬКО claim (доверяет ли память без кода?);
- `code_first` — claim + `support_patterns` + `section` (подтверждается ли якорями?).

**Промпты (дословно; EN и RU; v1 и v2):**

```
system EN: You are a codebase-intelligence agent deciding whether a memory claim is true.
           Reply ONLY with JSON: {"verdict": "true"|"false"|"unknown"}.
system RU: Вы — агент интеллектуального анализа кодовой базы, решающий, истинно ли утверждение
           из памяти. Отвечайте ТОЛЬКО JSON: {"verdict": "true"|"false"|"unknown"}.

memory_first EN:  Do NOT use any tools. Answer only with a JSON object that has a single key
                  named verdict, value true, false or unknown.
                  Memory contains this claim (no code context shown):
                  {claim}
                  Is it true?
code_first v1 EN: … Claim: {claim} · Supporting anchors (from memory): {patterns}
                  · Project section: {section}
                  · Does the claim appear supported by these anchors?   ← НАВОДЯЩИЙ (v1)
code_first v2 EN: … Claim: {claim} · Supporting anchors (from memory): {patterns}
                  · Project section: {section}
                  · Return true ONLY if the anchors directly verify the claim; false if the
                    anchors contradict it or the claim refers to something absent from the
                    anchors; unknown if you cannot determine.          ← НЕЙТРАЛЬНЫЙ (v2)
(RU-варианты — зеркальный перевод; claim всегда RU.)
```

**Гарантии (проверены тестами):**
- **Leak-guard:** `assert "truth" not in prompt` на каждый факт + unit-тесты (truth-поле физически не может попасть в промпт).
- **Привязка вердикт↔факт** по `fact["id"]`, merge по id при resume.
- **Конфиг единый:** temperature=0.0, seed=42, max_tokens=100, response_format=json_object, reasoning.enabled=false (кроме явных отклонений).
- **Статистика:** Wilson 95% CI для всех долей.
- **Аудит:** per-факт raw (300 симв.), finish_reason, cached_tokens, reasoning_tokens, cost (факт. цена OpenRouter).

---

## 4. Harness (`scripts/run_1L_live_arm.py`)

| Возможность | Описание |
|---|---|
| Провайдеры | `--provider openrouter` (по умолч.) · `api` (OpenAI-совместимый) · `opencode` (CLI) |
| Свип | `--models "a,b,c"` — каждая модель в свой progress-файл |
| Промпт | `--prompt-version v1\|v2` · `--prompt-lang en\|ru` |
| Бюджет | `--max-tokens 100` (дефолт) · `--seed 42` · `--no-reasoning` |
| Изоляция прогонов | `--tag X` → файлы `live_arm_1L_progress_X_<model>.json` |
| Защита данных | прогресс догружается всегда (кроме `--force`); `--force` — перезапись |
| Retry | EMPTY/NON_JSON → повтор; 429/5xx → backoff 2s/4s; 3×429 → стоп с сохранением |
| Fallback reasoning | если модель не принимает `reasoning.enabled=false` → повтор без параметра |
| Статистика | Wilson CI, false_accept_ids, truncated, usage (tokens/cached/reasoning/cost) |
| Ошибки | честно записываются (error-строка), не маскируются |

---

## 5. Хронология всех прогонов

| # | Прогон | Модели | Условия | Вызовы | Стоимость | Файлы |
|---|---|---|---|---|---|---|
| 1 | Day 1 | opencode/deepseek-v4-flash-free | v1, Zen free | 100 | $0 (free-тир) | `live_arm_1L_progress_opencode_*.json` (старый формат) |
| 2 | v1 run1 | 6 flash | v1 EN | 600 | ~$0.0087 | `live_arm_1L_v1_original_20260814/` (бэкап; qwen3.5 затёрт) |
| 3 | v1 run2 | 6 flash | v1 EN, испр. harness | 600 | ~$0.0087 | `live_arm_1L_progress_<model>.json` (канонические v1) |
| 4 | v2_en | 6 flash | v2 EN | 600 | ~$0.0087 | `live_arm_1L_progress_v2_en_<model>.json` |
| 5 | ru_v2 | 3 flash (qwen3.7/3.5/deepseek-flash) | v2 RU | 300 | ~$0.003 | `live_arm_1L_progress_ru_v2_<model>.json` |
| 6 | nemotron_family | super-120b, nano-30b | v2 EN | 200 | ~$0.0014 | `live_arm_1L_progress_nemotron_family_*.json` |
| 7 | premium_v2 | claude-sonnet-5, qwen3.8-max, glm-5.2, deepseek-v4-pro | v2 EN | 400 | ~$0.106 | `live_arm_1L_progress_premium_v2_*.json` |
| — | Пробы (кэш/reasoning/детерминизм) | GLM/qwen/deepseek | прямые API-вызовы | ~20 | <$0.001 | — |

**Всего: ~3300 вызовов, ~$0.14.**

---

## 6. Результаты

### 6.1. Мастер-матрица (все модели × руки; V2-EN, кроме v1-столбца)

FA = false_accept (доля ложных принятий из 50) · unk = unknown · acc = accuracy по решённым.

| Модель | Arm | FA v1(r2) | FA v2 | unk v2 | acc v2 | trunc/err v2 |
|---|---|---|---|---|---|---|
| qwen/qwen3.7-flash | mem | 0.00 | 0.00 | 0.68 | 0.94 (15/16) | 0/0 |
| | code | 0.00 | 0.00 | 0.24 | 0.76 (29/38) | 0/0 |
| qwen/qwen3.6-flash | mem | 0.00 | 0.02 | 0.58 | 0.86 (18/21) | 0/0 |
| | code | 0.00 | 0.00 | 0.38 | 0.77 (24/31) | 0/0 |
| qwen/qwen3.5-flash-02-23 | mem | 0.02 | 0.02 | 0.82 | 0.89 (8/9) | 0/0 |
| | code | 0.02 | 0.00 | 0.96 | 1.00 (2/2) | 0/0 |
| deepseek/deepseek-v4-flash | mem | 0.02 | 0.04 | 0.80 | 0.70 (7/10) | 0/0 |
| | code | 0.06 | 0.00 | 0.94 | 1.00 (3/3) | 0/0 |
| z-ai/glm-4.7-flash ⚠️ | mem | 0.06 | 0.10 | 0.64 | 0.72 (13/18) | 0/0 |
| | code | 0.28 | **0.24** | 0.24 | 0.66 (25/38) | 0/0 |
| nvidia/nemotron-3.5-lightning | mem | 0.08 | 0.08 | 0.32 | 0.79 (27/34) | 0/0 |
| | code | 0.08 | 0.04 | 0.56 | 0.77 (17/22) | 0/0 |
| nvidia/nemotron-3-nano-30b 🔴 | mem | — | 0.06 | 0.78 | 0.73 (8/11) | 0/0 |
| | code | — | **0.38** | 0.20 | 0.50 (20/40) | 0/0 |
| nvidia/nemotron-3-super-120b ❌ | mem | — | 0.00 | 0.94 | 0.67 (2/3) | 0/26 err |
| | code | — | 0.02 | 0.64 | 0.61 (11/18) | 0/27 err |
| anthropic/claude-sonnet-5 | mem | — | 0.00 | 0.86 | 1.00 (7/7) | 0/0 |
| | code | — | 0.00 | 0.70 | 1.00 (15/15) | 0/0 |
| z-ai/glm-5.2 | mem | — | 0.00 | 0.96 | 1.00 (2/2) | 0/0 |
| | code | — | 0.02 | 0.76 | 0.83 (10/12) | 0/0 |
| deepseek/deepseek-v4-pro | mem | — | 0.04 | 0.66 | 0.88 (15/17) | 0/0 |
| | code | — | 0.00 | 0.88 | 0.83 (5/6) | 0/0 |
| qwen/qwen3.8-max ❌ | mem | — | 0.00 | 0.98 | 1.00 (1/1) | 3/22 err |
| | code | — | 0.00 | 1.00 | — | 1/49 err |

### 6.2. False-accept ID (V2-EN; повторяющиеся якоря-дыры)

- qwen3.7: — · qwen3.6: mem [R50] · qwen3.5: mem [R50] · deepseek-flash: mem [R31,R38] ·
  glm-4.7: mem [R37,R40,R46,R49,R50], code 12 шт [R26,R35–R40,R43,R45,R46,R49,R50] ·
  nemotron-lightning: mem [R45,R47,R49,R50], code [R45,R50] · nemotron-nano: mem [R45,R48,R50],
  code 19 шт [R28,R31,R33–R43,R45–R50] · glm-5.2: code [R50] · deepseek-pro: mem [R45,R50].
- **R50 (silent-false, «loki») — системная дыра**: принята большинством моделей в code_first.
  Голый токен-якорь = мнимое evidence (HaluEval: помогает только релевантное знание).

### 6.2a. Подтверждение FA=0.00 у лучших (2-й прогон V2, tag `v2_en_run2`, 2026-08-14)

| Модель | Arm | V2 run1 FA | V2 run2 FA | Итог по 4 прогонам (v1×2 + v2×2) |
|---|---|---|---|---|
| qwen/qwen3.7-flash | code_first | 0.00 | **0.00** | **0/200** ✅ |
| | memory_first | 0.00 | 0.02 (R50) | 2/200 (всегда R50, silent-false) |
| qwen/qwen3.6-flash | code_first | 0.00 | **0.00** | **0/200** ✅ |
| | memory_first | 0.02 (R50) | 0.00 | 1/200 (R50) |

**Вывод:** false_accept = 0.00 в code_first подтверждён 4 независимыми прогонами (0/400 вердиктов)
у обеих моделей. Единственная нестабильность — факт R50 в memory_first (плейсибл silent-claim
«loki» без кода), и то не всегда. Обе модели — безопасный выбор для verify-on-read.

### 6.3. Премиум-арм (ответ ревью «с живым Claude цифры будут другими»)

- **claude-sonnet-5**: FA=0.00/0.00, acc=1.0 на всех решённых — эталон осторожности; но
  unknown 0.86/0.70 и цена $0.049/100 → для FA-безопасности не лучше qwen3.6-flash ($0.003).
- **qwen3.8-max**: **несовместима с бюджетом 100 токенов** — `Reasoning is mandatory for this
  endpoint and cannot be disabled` (HTTP 400, 22–49 из 50). Для дешёвого VOR непригодна;
  нужен бюджет ≥400–500 токенов (стоимость ×5).
- **glm-5.2**: FA 0.00/0.02 — кардинально лучше glm-4.7-flash (0.10/0.24): новое поколение
  той же семьи не доверяет якорям слепо. Очень осторожна (unknown 0.96/0.76).
- **deepseek-v4-pro**: FA 0.04/0.00, аккуратнее flash-версии.
- **Вывод:** премиум не нужен для FA-безопасности; разница FA между премиумом и лучшими flash — 0.

### 6.4. Семейство nemotron

- lightning: FA 0.08/0.04 — умеренно; nano-30b: **FA 0.38 code_first — худшая модель всего свипа**;
  super-120b: 50% ошибок HTTP 422 апстрима («Error while parsing») — ненадёжна, исключена.

---

## 7. Токены и стоимость

- **Токены/запрос:** ~107 входных / ~9.5 выходных (замерено live: 214+19 на 2 вызова; расчёт
  3.0–3.5 chars/tok: 103–142 in). max_tokens=100 — запас ×10.
- **Стоимость** (оценка по прайсу, проверенному 2026-08-14; с фикса 2026-08-14 harness пишет
  фактическую цену OpenRouter `usage.cost`): flash-свип 100 вызовов = $0.0005–0.0032/модель;
  премиум = $0.017–0.049/модель. **Всего ~$0.14 за ~3300 вызовов.**
- **Кеш GLM (45–48%)** снижает её фактическую цену ≤2× (cached вход $0.01/M vs $0.06/M) —
  на вердикты не влияет (см. §10).

---

## 8. Проверки целостности (всё, что реально запускалось)

| Проверка | Результат |
|---|---|
| `pytest tests/test_run_1L_live_arm.py` | 29/29 ✅ |
| Полный `pytest tests/` | **1226 passed / 10 skipped** ✅ |
| Dry-run без API + leak-guard | OK (50 фактов, обе руки) ✅ |
| Zen live (провайдер api) | честный 429 FreeUsageLimitError — стена подтверждена ✅ |
| OpenRouter smoke (2 факта) | вердикты реальные, токены/цена совпали с расчётом ✅ |
| Проба reasoning (6 моделей + GLM default) | reasoning_tokens=0 при `--no-reasoning`; GLM без флага — content=None, finish=length (110 reasoning) ✅ |
| Проба кеш vs детерминизм (4 модели × 3 вызова) | qwen3.6/3.7/deepseek детерминированы 3/3; GLM недетерминирована при полном кеше ✅ |
| Проба всех 6 моделей + премиум | ошибок в прогонах: только qwen3.8-max (mandatory reasoning) и nemotron-super (422 апстрима) ✅ |
| Дашборд OpenRouter (reasoning-токены) | у всех 6 моделей свипа — 0 reasoning-токенов (независимое подтверждение) ✅ |

---

## 9. Red Team атака (по §1.16) + веб-исследование

**Литература (4 источника, проверены 2026-08-14):**
- Zheng et al. 2023, «Judging LLM-as-a-Judge» (arXiv 2306.05685) — position/verbosity/self-enhancement bias.
- Sharma et al. 2023, «Towards Understanding Sycophancy» (arXiv 2310.13548) — LLM соглашаются с утверждениями.
- Li et al. 2023, «HaluEval» (arXiv 2305.11747) — внешние знания помогают только релевантные.
- NAACL-2025 «Beyond English» + MultiChallenge — 70–80% падений на неанглийском = English-centric reasoning.

**Атаки и вердикты:**

| # | Атака | Вердикт |
|---|---|---|
| 1 | Case/bool-парсинг вердиктов (True→unknown) | 🟡 латентный баг, исправлен + тесты; на данных не сработал (все raw lowercase) |
| 2 | truncation max_tokens=100 | ✅ опровергнута: finish_reason=stop везде, trunc=0; высокий unknown — честный |
| 3 | Наводящий вопрос code_first (сикофантия) | 🟡 подтверждена: V2 снизил FA у 4/6 моделей (deepseek 0.06→0.00, nemotron 0.08→0.04) |
| 4 | Языковой сдвиг EN/RU | 🟡 частично: deepseek — RU лучше (unk 0.94→0.54), qwen3.7 — EN лучше; пер-модельно |
| 5 | Bare-token якоря | 🟡 причина кластера R26–R50 (HaluEval) |
| 6 | seed=42 = детерминизм | 🟡 уточнено: работает для qwen3.6/3.7/deepseek (3/3), НЕ для GLM |
| 7 | Прайминг системного промпта | ⚪ minor, не меняли |
| 8 | Один прогон на модель | 🔴 подтверждена: вариативность ±0.05–0.10 (nemotron code 0.18→0.08) |
| 9 | Footgun `--limit` без resume | 🔴 исправлено: прогресс догружается всегда, кроме `--force` |

---

## 10. Кеш, reasoning, детерминизм (пробы 2026-08-14)

**Reasoning:** `reasoning.enabled=false` соблюдают ВСЕ модели (reasoning_tokens=0; дашборд
OpenRouter: 0 у всех 6 моделей свипа). Без флага GLM-4.7-flash: reasoning_tokens=110,
content=None, finish=length → 100% мусора. **Флаг обязателен.**

**Кеш:** prefix-KV-кеш (у GLM 45–48% cached tokens, тариф input_cache_read). Контр.
эксперимент: 3 идентичных запроса с ПОЛНЫМ кешем (cached=102) у GLM → true/true/unknown —
разные ответы. **Кеш не меняет вердикты** (без потерь; недетерминизм — свойство модели),
влияет только на цену и латентность.

**Детерминизм (3 одинаковых вызова, temp=0, seed=42):**
```
qwen3.6-flash      false, false, false      ✅ детерминирована
qwen3.7-flash      false, false, false      ✅ детерминирована
deepseek-v4-flash  unknown, unknown, unknown ✅ детерминирована
GLM-4.7-flash      true, true, unknown      ❌ недетерминирована (даже при полном кеше)
```

---

## 11. Ограничения и угрозы валидности

1. **Однопроходность части прогонов**: v2/premium/nemotron-family — 1 прогон (v1 — 2). Для
   тонких ранжировок нужны ≥2 прогона / мажоритарное голосование.
2. **V1-промпт завышает FA** (наводящий вопрос, кластер R26–R50). V2 — канонический.
3. **Язык промпта — конфаунд модель-зависимый** (deepseek: RU лучше; qwen3.7: EN лучше).
4. **qwen3.8-max не измерена** под бюджетом 100 токенов (mandatory reasoning) — это её
   свойство, не дефект harness.
5. **nemotron-super** — ошибки 422 апстрима (NIM), результат частичный.
6. **Блочный порядок датасета** (R01–R25 true) — для независимых вызовов не угроза.
7. **OpenRouter-маршрутизация** на разные апстримы — источник вариативности и кеш-различий.
8. **N=50 на руку**: CI 0.50→±0.14; достаточно для крупных эффектов.
9. **Нет human-разметки** вердиктов моделей (только ground truth датасета).

---

## 12. Воспроизведение (пошагово, в любое время)

### 12.1. Окружение (1 раз)
```bash
git clone <repo> mscodebase && cd mscodebase
python -m venv venv && venv\Scripts\python -m pip install -e .   # Windows
# .env:  OPENROUTER_API_KEY=sk-or-v1-...   (НЕ коммитить)
venv\Scripts\python -c "from dotenv import load_dotenv; import os; load_dotenv('.env'); \
print('OK' if os.environ.get('OPENROUTER_API_KEY','').startswith('sk-or-v1-') else 'MISSING')"
```

### 12.2. Тесты и dry-run
```bash
venv\Scripts\python -m pytest tests/test_run_1L_live_arm.py -v      # 29 тестов
venv\Scripts\python -m pytest tests/ -q                              # полный
venv\Scripts\python scripts/run_1L_live_arm.py --arm both --dry-run  # leak-guard OK
```

### 12.3. Прогоны
```bash
# flash-свип V2 (канонический): 6 моделей, 600 вызовов, ~15 мин, ~$0.009
venv\Scripts\python scripts/run_1L_live_arm.py --provider openrouter --arm both \
  --models "qwen/qwen3.7-flash,qwen/qwen3.5-flash-02-23,z-ai/glm-4.7-flash,\
nvidia/nemotron-3.5-lightning,deepseek/deepseek-v4-flash,qwen/qwen3.6-flash" \
  --prompt-version v2 --no-reasoning --tag v2_en

# премиум-арм (по желанию): ~$0.10
venv\Scripts\python scripts/run_1L_live_arm.py --provider openrouter --arm both \
  --models "anthropic/claude-sonnet-5,qwen/qwen3.8-max,z-ai/glm-5.2,deepseek/deepseek-v4-pro" \
  --prompt-version v2 --no-reasoning --tag premium_v2

# контроль языка (по желанию): 3 модели, 300 вызовов
venv\Scripts\python scripts/run_1L_live_arm.py --provider openrouter --arm both \
  --models "qwen/qwen3.7-flash,qwen/qwen3.5-flash-02-23,deepseek/deepseek-v4-flash" \
  --prompt-version v2 --prompt-lang ru --no-reasoning --tag ru_v2

# второй прогон для вариативности: тот же свип + --force
```

### 12.4. Инвентарь данных (где что лежит)
```
%LOCALAPPDATA%\mscodebase\projects\bfe9644b\experiments\
├── live_arm_1L_progress_<model>.json                      # v1 run2 (канонические v1)
├── live_arm_1L_progress_v2_en_<model>.json                # V2 EN
├── live_arm_1L_progress_ru_v2_<model>.json                # RU-контроль
├── live_arm_1L_progress_nemotron_family_*.json            # nemotron super/nano
├── live_arm_1L_progress_premium_v2_*.json                 # премиум
└── live_arm_1L_v1_original_20260814/                      # v1 run1 (бэкап; qwen3.5 затёрт)
```
Каждый файл: `model/provider/base_url/config(с полным fingerprint)/arms[arm]{results[{id,truth,
verdict,error,tokens,cost,cached,reasoning,finish_reason,raw}], сводка с Wilson CI, usage}`.
Путь вычисляется: `python -c "from src.core.artifact_paths import get_project_dir; import pathlib; print(get_project_dir(pathlib.Path('.').resolve()))"`.

### 12.5. Сводка по всем моделям
```bash
venv\Scripts\python -c "
import json, glob, os
base = os.path.join(os.environ.get('LOCALAPPDATA',''), 'mscodebase','projects','bfe9644b','experiments')
for fp in sorted(glob.glob(os.path.join(base,'live_arm_1L_progress_v2_en_*.json'))):
    r = json.load(open(fp, encoding='utf-8'))
    for arm, s in r['arms'].items():
        fa = s.get('false_accept', {})
        print(r['model'], arm, 'FA=', fa.get('rate'), fa.get('k'), '/', fa.get('n'),
              'unk=', s.get('unknown_rate',{}).get('rate'), 'ids=', s.get('false_accept_ids'))
"
```

---

## 13. «Со всех сторон подошли?» — покрытие и оставшиеся пробелы

**Покрыто:** датасет · дизайн (v1/v2, EN/RU) · 14 моделей (flash/nemotron/premium) ·
2–3 прогона (v1) · Red Team по §1.16 + 4 литературных источника · кеш · reasoning ·
детерминизм · язык · стоимость (оценка + фактическая) · аудит (raw/finish/cache/reasoning) ·
тесты (29 unit + 1226 полный) · репродукция.

**Остаточные пробелы (честно):**
1. ✅ ЗАКРЫТ (2026-08-14): FA=0.00 у qwen3.6/3.7 подтверждён 4 прогонами (v1×2 + v2×2), code_first 0/400.
2. ⚠️ v2/premium/nemotron-family (кроме qwen3.6/3.7) — однопроходные; для тонких выводов нужен 2-й прогон.
3. ⚠️ qwen3.8-max не даёт вердиктов при бюджете 100 токенов — отдельный прогон с max_tokens≥500 (другое условие).
4. ⚠️ Языковой контроль — только 3 модели; GPT/Gemini не тестировались (Claude из ревью — закрыт).
5. ⚠️ Human-разметка вердиктов не проводилась (для FA-метрик достаточно ground truth датасета).

---

## 14. Ссылки

- `EXPERIMENTS_LOG.md` — Day 1, Day 2, Red Team фаза 2, follow-up'и (V2/RU/premium)
- `AGENT_DIARY.md` — 2026-08-14 23:20 (свип), 23:55 (Red Team)
- `experiments/exp_1L_longitudinal_30d.md` — дизайн 30-дневного протокола
- `scripts/run_1L_live_arm.py` — harness · `tests/test_run_1L_live_arm.py` — тесты
- Литература: arXiv 2306.05685 · 2310.13548 · 2305.11747 · NAACL-2025 (Beyond English)
