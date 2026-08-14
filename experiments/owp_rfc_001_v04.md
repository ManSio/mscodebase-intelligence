# OWP RFC-001 — v0.4 Hardening: «Verification must itself be verified»

- **Status:** Draft for discussion (GitHub Discussion / PR — как предложил Brian Jin)
- **Target:** OpenWorkProof spec v0.3 → v0.4
- **Inputs:** обзоры Brian Jin (Judgment Pack; Study 017) и Mikhail; два раунда красной команды (TC-1..TC-10), все атаки воспроизведены рабочим кодом (симуляции, параметры в Appendices B/D)
- **Related sections:** §4.1 (incident `ln.strip()`), §5.2 (control rot), §5.3 (population manifest), §5.5 (receipt lifecycle), §7 (detection claims)

---

## 0. TL;DR

Оба рецензента независимо указали на одну и ту же структурную дыру: **v0.3 специфицирует формат доказательства, но не обязательное поведение потребителя доказательства.** Эксперименты и два раунда атак дали количественное подтверждение. Нормативные дополнения:

1. **Новая секция «Consumer Obligations»** — молчаливый soft-fail при недоступности retraction-проверки запрещён по умолчанию.
2. **`retraction_staple`** — аналог OCSP Must-Staple (RFC 7633): проверка становится дешёвой и локальной, поэтому hard-fail работает.
3. **`receipt_id` + `policy_binding`** — квитанция привязана к конкретному policy-checkpoint, на котором выпущена.
4. **Усиления по итогам red team:** `provocation_type` (семантическая пиновка), `collector_witness` → MUST-when-material, `min_accepted_revision` (анти-replay), транзитивные fixtures в negative control-ах.

## 1. Мотивация

- Инцидент `ln.strip()` (§4.1): продакшн-гейт месяцами возвращал `verified: true`; из 40 guard-проверок лишь 7 реально умели ловить сбой. Девиз: «Проверка, которая никогда не проваливается, никогда не была проверкой».
- Brian Jin: квитанция не привязана к policy-checkpoint; `effective_from` неоднозначен; §7 обещает «обнаружение задним числом подделки истории» — перебор (split-view problem); лицензии расходятся.
- Mikhail: OCSP soft-fail trap (агенты молча доверяют старой квитанции), CT illusion (лог доказывает публикацию, не правдивость), SBOM blind spot (`eligible_seen` самоотчётный).

## 2. Экспериментальная база

| # | Что проверялось | Результат (seed-фиксированный) |
|---|---|---|
| 1 | `assert` после `return` | buggy-гейт: 2/2 на хороших, **0/3 на плохих** — невидим без негативного контроля |
| 2 | Классификация «proven» | от **1 до 7/40** при порогах 100%→50%; digest-pinning делает расхождение детектируемым на уровне схемы |
| 3 | Population manifest | `(400, 0)` = SUSPICIOUS vs `(0, 0)` = OK; без `eligible_seen` неотличимы |
| 4 | OCSP soft-fail | **36%** отозванных квитанций использованы необнаруженно (мягкий отказ) vs **0%** (hard-fail); staple: 0 тихих обходов |
| F3 | Policy binding | подделанный digest → INVALID; legacy без binding → INVALID; retraction → receipt остаётся *bounded*, не *invalid* |

*Оговорка: точные проценты зависят от параметров симуляции (36% vs 57% в исходном нарративе; 22% vs 15% в TC-3). Подтверждаемый тезис — механизм, а не число.*

## 3. Нормативные изменения

### 3.1 НОВАЯ СЕКЦИЯ: Consumer Obligations (потребитель доказательства)

- **Consumer MUST** проверять revocation-статус квитанции перед использованием в решении, от которого зависит материальный результат.
- **Consumer MUST NOT** молча использовать квитанцию с недоступной проверкой отзыва (soft-fail). Если деплоймент осознанно разрешает soft-fail — обязан: (a) явно включить в конфигурации, (b) логировать каждый пропуск, (c) включать `soft_fail_rate` в population-метрики (3.7).
- Проверка выполняется live-запросом к issuer/co-signer **или** локальной верификацией свежего `retraction_staple` (3.2).
- **Consumer MUST** отклонять квитанцию, если `policy_binding` (3.3) не соответствует активной ревизии политики; **и** проверять актуальность ревизии (`min_accepted_revision`, TC-9).
- «Потребитель» — явно включая **агентов**, а не только людей/валидаторов (именно агенты под давлением бюджета латентности склонны к тихому soft-fail).

### 3.2 `retraction_staple` (аналог OCSP Must-Staple, RFC 7633)

- Issuer или независимый co-signer заранее, в фоне, прикрепляет короткоживущий подписанный proof «не отозвано»: `{ receipt_id, status: "active", issued_at, max_age }`, подпись issuer'а.
- **Verification rule:** `age(staple) <= max_age` → свежий; `age > max_age` или отсутствие → **hard-fail** (невалидно для материального решения).
- **Урок Must-Staple (RFC 7633, §3–§5):** hard-fail работает, когда проверка дешёвая и локальная; staple делает её локальной. Цена — фоновая генерация и короткий TTL.
- **Окно доверия** `(issued_at, issued_at+max_age)` фиксируется в квитанции и политике потребителя; параметризация: `max_age << expected_detection_latency` (TC-3).

### 3.3 `receipt_id` + `policy_binding` (замечание Brian Jin, п.1)

- `receipt_id` — **обязательное** поле (v0.3 ссылается на него в §5.5, но не определяет).
- Новый блок: `policy_binding { policy_checkpoint_digest, policy_revision, checkpoint_chain[] }` (X.509-подобная цепочка, опционально).
- **Validation:** сверка digest с активной ревизией + **`min_accepted_revision`** (TC-9): квитанция, выпущенная под ревизией ниже актуальной, для *новых* claim'ов — INVALID (для *исторических* — bounded, §5.5).
- **Retraction-семантика:** смена политики не делает квитанцию ретроактивно невалидной — она остаётся **bounded** к своей ревизии.

### 3.4 Ужесточение `negative_control` (control rot, §5.2; «Fix 1» + TC-1/TC-8)

- Аналогия из mutation testing (Stryker/PIT): «нет универсального порога» решается **публикацией и фиксацией** порога для конкретного класса проверок.
- `negative_control` обязан нести подписанные: `proof_threshold`, `control_set_digest` (дайджест всего набора), **`provocation_type`** (декларируемый класс провокации — TC-1: digest пинит байты, не семантику; provocation_type фиксирует намерение, маркер вывода обязан содержать имя класса).
- **Fixtures = транзитивное замыкание зависимостей контроля** (TC-8): все файлы, от которых зависит исполнение negative control (сам чекер, конфиги), обязаны входить в digest — иначе правка чекера невидима для пина.
- **Consumer MUST** отклонять квитанцию, если: (a) `control_set_digest` не в known-good реестре, или (b) собственная оценка классифицирует guard'ы иначе.
- **`--pin` (re-prove) = единственная точка изменения digest — обязательный момент ревью**, фиксируемый записью (кто/когда/что изменилось); без записи pin недействителен (TC-10: запись без внешнего якоря — самоаттестация; целостность — через git-историю/co-signer, v0.5).

### 3.5 Разграничение `effective_from` (Brian Jin, п.2)

- `effective_from_utc` — **нормативное** время (подписывается; enforcement требует доверенного источника времени: NTP у issuer'ов, допустимый clock skew в политике); `validity_window` — информационное.
- Спецификация явно перечисляет, какие claim'ы зависят от доверенного времени (staple, policy activation), а какие нет (факт подписи).

### 3.6 §7: корректировка «обнаружения подделки истории» (Brian Jin, п.3; Mikhail; TC-5)

- Заменить на ограниченное: **квитанция доказывает (a) публикацию в момент T и (b) внутреннюю согласованность с подписанной цепочкой digest, известной верификатору. Она НЕ доказывает, что оператор не показывал третьим лицам другую (раздвоенную) историю.**
- «Split-view scope»: свежий верификатор не знает, какую историю оператор демонстрировал другим; обнаружение требует независимых внешних свидетелей (append-only witness log) для high-value квитанций. Study 017 — как процитировано рецензентом.

### 3.7 Доверие к сборщику population manifest (SBOM blind spot, Mikhail; TC-2)

- `eligible_seen` самоотчётный: digest защищает список **после** подписи, не сбор **до** неё.
- `collector_witness` (независимый gateway-счётчик или выборочный пересчёт) — **MUST** для material-claim'ов; `collection_method` обязателен; `soft_fail_rate` — в той же таблице.
- Таблица отказов: `(400, 0)` = сломанный день, `(0, 0)` = здоровый тихий день — без `eligible_seen` неотличимы.

### 3.8 Унификация лицензии (Brian Jin, п.4)

- Одно решение по лицензии до внешнего вклада (рекомендация: Apache-2.0 для спекулятивной части; либо явное разделение docs/code); единый LICENSE-хедер; пункт в CONTRIBUTING.

## 4. Совместимость и миграция

- Квитанции v0.3 без `policy_binding`/`control_set_digest`: grace-период (валидация с warning), затем reject. Срок — в политике перехода.
- Квитанции v0.3 без стапла: по умолчанию **unproven** (не невалидные), пока не пройдут live-проверку отзыва.
- Квитанции, выпущенные под ревизией ниже `min_accepted_revision`: для новых claim'ов INVALID; исторические — bounded (§5.5).

## 5. Открытые вопросы

1. Soft-fail: полный запрет или разрешение с обязательной отчётностью? (Фрикция Must-Staple; нужен ли аналог «MAY accept, но MUST NOT называть secure» из RFC 7633 §4.2.3.1.)
2. Staple: кто устанавливает `max_age`, доверие к co-signer'у, цена фоновой генерации.
3. `control_set_digest`: публичный реестр (CT-подобный) или per-issuer? (CT illusion: реестр доказывает публикацию, не правдивость.)
4. External witness log — в scope v0.5 (см. Appendix C, общий вывод).

## 6. Влияние на модель зрелости

Уровень 5 («контролёры сами проверяются») требует: consumer obligations (3.1), digest-pinned контроли с provocation_type (3.4), collector-witness (3.7) и **witness/consensus-слой** (Appendix C) — без последнего уровень 5 недостижим по построению.

---

## Appendix A — схема (компактный JSON)

```json
{
  "receipt_id": "R-001",
  "effective_from_utc": "2026-08-14T09:00:00Z",
  "validity_window": {"note": "descriptive"},
  "policy_binding": {
    "policy_checkpoint_digest": "...",
    "policy_revision": "v2.1",
    "min_accepted_revision": "v2.0",
    "checkpoint_chain": []
  },
  "negative_control": {
    "provocation_type": "lockfile-drift",
    "proof_threshold": 0.85,
    "control_set_digest": "...",
    "fixture_transitive_closure": true
  },
  "retraction_staple": {
    "status": "active", "issued_at": "...", "max_age": 3600,
    "signature": "..."
  },
  "population": {
    "eligible_seen": 400, "population_size": 0,
    "collection_method": "gateway_counter",
    "collector_witness": "...",
    "soft_fail_rate": 0.0
  }
}
```

## Appendix B — сырой вывод симуляций (ключевые строки)

```
[EXP 1] good inputs (must PASS):   ok=2/2  buggy=2/2  <- indistinguishable
        bad inputs  (must REJECT): ok=3/3  buggy=0/3  <- negative control reveals
[EXP 2] threshold >= 100%: proven=1/40 | >=85%: 6/40 | >=70%: 7/40 | >=50%: 7/40
        [FIX1] same digest -> 6 == 6; other set -> 6 vs 5; digest != -> receipt invalid
[EXP 3] broken_day eligible_seen=400 population_size=0 -> SUSPICIOUS
        quiet_day  eligible_seen=0   population_size=0 -> OK
[EXP 4] soft-fail: 73/204 = 36% used undetected | hard-fail: 0/204 (73 blocked)
        [FIX2] fresh staple pass = 1375; stale staple hard-rejected = 625 -> silent bypass = 0
[FIX 3] good: VALID | forged: INVALID | legacy: INVALID | retraction -> bounded, not invalid
```

Параметры: seed=42 (Exp 2), seed=7 (Exp 4), budgets ~ U(0.05–0.15)s, check latency ~ U(0.03–0.14)s, revoked=10%, N=2000.

## Appendix C — Threat Model / Non-Goals (Adversarial Limits)

> Правило чтения: если механизм «выглядит как защита от X» — X перечислен ниже; если его нет — протокол его не даёт. **OWP доказывает консистентность утверждений с артефактами, не правдивость мира. «Подписанная квитанция» ≠ «не подделана».**

### C.1 Доверительные якоря (Trust Anchors)

Все гарантии опираются на один якорь — **честность держателя ключа подписи**. Протокол не защищает от него самого; защита — только аудит якоря (TC-4, TC-6). Миграция к нескольким якорям (co-signer, witness log) — v0.5.

### C.2 Угрозы (TC-1..TC-6, раунд 1 — все воспроизведены кодом)

| # | Сценарий | Proved | Not proved | Mitigation (v0.4) | Status |
|---|---|---|---|---|---|
| TC-1 Control theater | digest пинит байты, не `provocation_type`; всегда-красный контроль → легитимный proven | набор байт зафиксирован | набор тестирует заявленный класс | `provocation_type` нормативен; маркер содержит имя класса; `--pin` = ревью-момент с записью | закрыто 3.4 |
| TC-2 Collector forgery | `eligible_seen` самоотчётный; компрометированный сборщик выдумывает N событий до подписи | отчёт не изменён после подписи | события реально произошли | `collector_witness` MUST-when-material; `collection_method` | закрыто 3.7 |
| TC-3 Staple race window | окно «компрометация→детекция»: отозванная квитанция со свежим staple'ом используется до обработки (22% при U(5,30)/U(0,90)) | не отозвана на issued_at | не отозвана в окне (issued_at, issued_at+max_age) | `max_age << expected_detection_latency`; co-signer cross-check | residual (управляется) |
| TC-4 Checkpoint stuffing | цепочка консистентна, содержание вредоносно; ключ-держатель встраивает checkpoint | привязка к ревизии, ревизия не подменялась | содержание политики легитимно | декларация якоря (C.1); аудит корня — процесс | by design (trust anchor) |
| TC-5 Split-view | два верификатора получают разные внутренне консистентные истории | версия, показанная этому верификатору, консистентна | третьим лицам не показана иная история | §3.6 ограничивает §7; witness log для high-value | закрыто 3.6 / witness = v0.5 |
| TC-6 Issuer collusion | negative arm честно прогнан (capability), positive arm сфабрикован; подпись валидна | подпись якоря; способность контрольной группы ловить класс — хотя бы раз | данный прогон был честным (attestation, не proof-of-truth) | честная маркировка Non-Goals; «signed» без раздела — вредно | by design / witness = v0.5 |

### C.3 Общий вывод (раунд 1)

Патчи v0.4 не защищают от TC-1..TC-6 — **и не обязаны**: их цель — конвертировать тихий отказ в детектируемый на уровне схемы, и она достигнута. TC-1/TC-2 — нормативные усиления v0.4; TC-3 — управляемый риск; TC-4/5/6 — граница attestation-модели, закрывается **witness/consensus-слоем** (v0.5).

## Appendix D — Red Team round 2 (TC-7..TC-10, все воспроизведены кодом)

```
[TC-7] marker substring spoof via negation
  control output: 'DEAD GUARD DETECTED: nothing was actually detected, control is GREEN'
  substring 'DEAD GUARD DETECTED' found: True  -> classified PROVEN
  => substring matching is fooled by negation; exact-line/structured markers needed
[TC-8] transitive dependency gap
  digest of pinned fixtures: e5cee3591b0d
  after editing stale_check.py (not in fixtures): e5cee3591b0d  unchanged: True
  => edits to transitive deps never invalidate the pin (no re-review moment)
[TC-9] policy replay after revision upgrade
  old-revision receipt replayed after upgrade to v2.2: accepted = True
  => consumer MUST check min_accepted_revision, not just binding
[TC-10] pin-log self-attestation
  real log:   {'pinned_at': '2026-08-14T07:30:00Z', 'reason': '...', 'digests': {...}}
  forged log: identical  -> indistinguishable: True
  => review record gains integrity only via external anchor (git/co-signer, v0.5)
```

| # | Сценарий | Вердикт | Mitigation (v0.4) |
|---|---|---|---|
| TC-7 Marker spoof | substring-совпадение маркера обходится отрицанием в выводе контроля | реальная, но вариант TC-1 (автор контроля контролирует вывод) | structured/exact-line маркеры для high-assurance; в нашей реализации — substring достаточен для внутренних гейтов (документировано) |
| TC-8 Transitive gap | правка чекера/конфига вне fixtures-списка не инвалидирует pin | реальная, дешёвая | **fixtures = транзитивное замыкание** (сам чекер, конфиги); реализовано в runner (3.4) |
| TC-9 Policy replay | старая ревизия переигрывается после апгрейда политики | реальная, consumer-side | `min_accepted_revision` (3.1/3.3); bounded ≠ acceptable-for-new-claims |
| TC-10 Pin-log self-attestation | ревью-запись пишется тем же субъектом; неотличима от поддельной без внешнего якоря | by design (самоаттестация) | целостность через git-историю (commit на pin) / co-signer; witness = v0.5 |

---

## References

- RFC 7633 «X.509v3 TLS Feature Extension» — проверено по rfc-editor.org (2026-08-14).
- RFC 2119 (MUST/SHOULD).
- Study 017 — процитировано Brian Jin; не проверено независимо в этой сессии.
- OWP v0.3 — по описанию в обсуждении; репозиторий из этой сессии недоступен.
