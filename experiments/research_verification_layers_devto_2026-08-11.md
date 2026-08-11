# Research: Verification Layers for AI Agents — dev.to discussion → MSCodeBase

> Дата: 2026-08-11 · Тип: research (внедрение — по решению владельца, §1 Шаг 4)
> Эксперименты: `experiments/exp_*.py` (воспроизводимы), сырые выводы — EXPERIMENTS_LOG#2026-08-11-EXP-1..5
> Автор: agent (MSCodeBase), триггер: задача владельца «изучи посты+комментарии, проведи эксперименты с атаками»
> **Обновление 2026-08-12:** P1 (drift-гейт + negative control) и P2 (stale_detector placeholder → реальный чекер, отключён из pre-commit) ВНЕДРЕНЫ по команде владельца. Canary P2 и health P3 — ждут команды.

---

## 1. Источники

| Источник | Что внутри |
|---|---|
| [dev.to/dengyier: "When an AI agent says 'I ran the tests and they passed'"](https://dev.to/dengyier/when-an-ai-agent-says-i-ran-the-tests-and-they-passed-do-you-trust-it-4ni1) | Trust problem в multi-agent; автор предлагает крипто-чеки (OpenWorkProof); 40 комментариев |
| [dev.to/dengyier: "When Your AI Agent Passes 2,283 Tests — And Still Fails in Production"](https://dev.to/dengyier/when-your-ai-agent-passes-2283-tests-and-still-fails-in-production-2dga) | Синтез: баг `ln.strip()`, Four Layers, dual-arm verification; 13 комментариев |

Ключевые участники (комментарии изучены все): **Tom Jones** (финтех, измеренный кейс verifier-который-не-может-упасть), **Giulio D'Erme** (negative control + artifact-not-exit-code), **ANP2** (reproducibility ≠ falsifiability, mutant-patch), **Zira** (execution ledger vs evidence bundle, VERIFIED/REFUTED/UNKNOWN), **Max Quimby** (метрика «proven/unproven», scheduled rot), **Cophy Origin** (verification theater, negative control checkpoints), **Skillselion** (rot контрольной группы, digest-pinning), **Mikhail** (= владелец проекта; Layer 0 Semantic Correctness, Population Manifest, immutable evidence ≠ immutable truth).

## 2. Концептуальная модель дискуссии

**Три вопроса проверки (а не два):**

| Layer | Вопрос | Failure mode | Решение |
|---|---|---|---|
| L1 (Tom) | Может ли проверка УПАСТЬ? | `ln.strip()` — структурно не может fail; vacuous suite | Negative control (мутант обязан exit≠0) |
| L2-4 (dengyier) | Была ли это РЕАЛЬНАЯ проверка с РЕАЛЬНЫМИ входами? | Подмена входов/результата после выполнения | Receipt chain + signatures + authorization |
| L3 (Tom, день 2) | Была ли проверка наведена на ПРАВИЛЬНУЮ популяцию? | Пустой входной набор = зелёный как настоящий all-clear | Population manifest: N входов + правило селекции |
| L3.5 (Tom, день 2) | Сколько событий достигло гейта ДО селекции? | 0 строк с 0 eligible (здоровый idle) vs 0 строк с 400 eligible (сломанный коллектор) | `eligible_seen` рядом с `population_size` |
| L0 (Mikhail) | Верна ли СЕМАНТИКА утверждения? | Тест зелёный, но проверяет не то (shared blind spot) | Отдельный ревьюер БЕЗ вердикта первого (не echo chamber) |

**Сопутствующие принципы:**
- **immutable evidence ≠ immutable truth** — чек immutable, вердикт отзываем (VERIFIED → REFUTED, отдельный актор, со-подпись).
- **Dual-arm verification** — каждый claim-носитель обязан нести (a) pinned-сюиту, которая проходит, И (b) pinned-мутанта, который падает. Только (a) = «reproducibility without falsifiability».
- **Rot**: proven-сегодня → unproven-завтра (рефакторинг зависимости, schema-миграция). Guard: digest-pinning контрольной группы → правка сбрасывает proven → unproven.
- **Ask for the artifact, not the exit code** (Giulio) — exit code — claim о процессе; артефакт — claim о мире.
- **UNKNOWN — честное состояние** (Zira) — механически валидно, семантически пусто.

## 3. Маппинг на MSCodeBase

### Уже внедрено (этой дискуссии это соответствует 1:1)

| Концепция | Где в проекте |
|---|---|
| Retraction VERIFIED→REFUTED (RetractionReceipt) | ADR-0002, `intel_retract_memory_node`, tests/test_memory_retraction.py (2026-08-11) |
| Verify-on-read + UNKNOWN-аналог | ADR-0003, `INCONCLUSIVE` вердикт, tests/test_verify_on_read.py |
| «Тест проверяет не то» (synthetic monitoring лгал) | health.py:676-767 + регрессия #15 — FIXED 2026-08-07 |
| Trust-стампинг / untrusted по умолчанию | WISDOM Security (cross-origin poisoning) |
| Shadow canary для смены embedder | remote_embedder.py `_shadow_compare` + test_shadow_canary.py |

### Слепые зоны (подтверждены экспериментами)

| # | Зона | Эксперимент | Вердикт |
|---|---|---|---|
| 1 | **drift-гейт verify_clean_state.sh:58-65 структурно мёртв** (grep `^\"?pkg==` не матчит TOML-массив) | EXP-5A | P1 🔴 — guard не может упасть, неотличим от рабочего |
| 2 | **pre-commit stale_detector = placeholder**, всегда exit 0 | Любопытство (§3.4) | P2 🟡 — второй guard того же класса |
| 3 | **Shadow Canary**: fail-open (пустой canary, сбой базлайна → доверие); collapse-to-constant не ловится (относительная метрика) | EXP-1 | P2 🟡 — 5/5 атак прошли |
| 4 | **_check_search_quality**: «0 eligible» (пустой индекс) неотличим от «0 собрано» (сломанный коллектор) | EXP-4 | P3 🟡 — нет eligible_seen |
| 5 | **verify_clean_state.sh** печатает PASSED для вакуумной сюиты (0 asserts) | EXP-5B | семантическая слепота (reproducibility без falsifiability) |
| 6 | Сюита тестов: 1133/1143 proven — **это хорошо**, не надо чинить | EXP-2 | ❌ гипотеза опровергнута (0.3% вакуумных) |

## 4. Предложение по внедрению (по приоритету, ждёт решения владельца)

### P1 — Фикс drift-гейта (verify_clean_state.sh:58-65)
```bash
# Было (мёртвое): требует pkg== в начале строки
PINNED=$(grep -iE "^\"?${pkg}==" pyproject.toml | head -1 | grep -oE '[0-9][0-9.]*' | head -1)
# Стало: матчит пины внутри TOML-массива    "lancedb==0.34.0",
PINNED=$(grep -oE "\"${pkg}==[0-9.]+" pyproject.toml | head -1 | grep -oE '[0-9][0-9.]*' | head -1)
```
+ **negative control** (правило Тома): CI-шаг, который создаёт фикстуру дрейфа (pin 0.99.0 vs lock) и требует exit 1. Без него гейт снова незаметно умрёт.

### P2 — Shadow Canary: fail-closed + абсолютный порог (remote_embedder.py)
```python
if not self._canary_pairs:
    logger.warning("🐦 Canary empty — switch BLOCKED (fail-closed)")
    return False                      # было: return True (доверие)
...
except Exception:
    logger.warning("🐦 Baseline failed — switch BLOCKED (fail-closed)")
    return False                      # было: return True
...
if old_mean < ABS_MIN_QUALITY:        # абсолютный якорь, напр. 0.5
    logger.warning("🐦 Baseline itself below quality — UNKNOWN, block")
    return False
# collapse-детектор: дисперсия новых векторов ≈ 0 → reject
```
+ решение по `test_shadow_canary.py:54-63` («пустой canary = доверие») — keep+документировать или перевернуть.

### P2 — pre-commit stale_detector: убрать placeholder
Подключить `tools/stale_detector/stale_check.py` (реальная реализация) или удалить вызов из git_hooks_installer.py:88. «Декоративные» гейты хуже отсутствия — создают ложную уверенность.

### P3 — Population manifest в health (health.py:744-756)
В warning/метрику добавить: `eligible_seen` (число чанков в индексе до запроса — из indexer) рядом с `population_size` (сырые результаты). «0 сырых + 0 eligible» → INFO «healthy idle»; «0 сырых + N eligible» → WARNING «broken collector».

### P3 — Дорожная карта negative controls (протокол Тома для проекта)
`scripts/negative_controls/` — фикстуры, каждая ОБЯЗАНА дать exit≠0, runner ассертит это; digest-pinning (Skillselion): правка фикстуры сбрасывает proven→unproven. Кандидаты (по итогам скана EXP-2 их мало — сюита доказуема):
1. дрейф-гейт (мутант pin),
2. canary collapse (constant-векторы),
3. health empty-vs-garbage (различимость),
4. ln.strip()-класс (assert-после-return) — если появится код экстракции.

## 5. Red Team собственного предложения (§1.16)

1. **Атака: отрицательный контроль тоже может врать** (Skillselion-rot) → защита: digest-pinning + «crash ≠ catch» (финтех: SyntaxError-крах градился как proven — у нас runner различает exit≠0 с traceback от аккуратного AssertionError).
2. **Атака: fail-closed canary заблокирует смену модели при лёгкой деградации** (ложный отказ) → защита: UNKNOWN-ветка вместо жёсткого False: блок + явный лог причины; порог 10% остаётся, но baseline-качество фиксируется.
3. **Атака: eligible_seen тоже может быть популяционно-слеп** (считаем не тот индекс) → защита: источник eligible_seen — реальный счётчик чанков indexer, а не производное от searcher; в receipt-стиле — правило селекции в метрике.
4. **Атака: фикс гейта `grep -oE "\"pkg==..."` сломается на диапазонных пинах** (mcp `<2`) → защита: сравнение только exact-pin пакетов (как сейчас) + отдельная проверка диапазонов через tomllib (python) в том же шаге.
5. **Атака: внедрение без negative control → гейт снова молча умрёт** → защита: negative control обязателен в ТОМ ЖЕ коммите, что фикс (Триггер 7 §1.19).

## 6. Следующие шаги (жду решения владельца)

1. «Делаем P1» → фикс drift-гейта + negative control, тесты, verify_clean_state.
2. «Делаем P2 canary» → fail-closed + absolute threshold + тест на constant-vectors (EXP-1 как тест).
3. «Делаем P2 stale_detector» → подключить реальный чек в хук.
4. «Делаем P3 health» → eligible_seen.
5. Создать `scripts/negative_controls/` runner (протокол Тома), как базу для всех будущих guard-ов.

**Open questions владельцу (§1.10):** (1) empty-canary: keep как фичу (документировать) или перевернуть в fail-closed? (2) 3 вакуумных smoke-теста (test_assignments.py:396, test_ast_cache_invalidation.py:60, test_sandbox.py:46) — добавить явные asserts или оставить (дискриминация через exception-пропагацию)? (3) внедрять ли в эту сессию или отдельной по команде?
