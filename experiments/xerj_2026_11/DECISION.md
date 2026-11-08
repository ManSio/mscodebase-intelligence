# DECISION — ответ на consent-письмо XERJ (P0-4)

> Статус: **решение принято, письмо не отправлено.** Отправка — действие владельца
> (внешний канал, §19.20: после отправки нужна машинная сверка состояния хаба).
> До отправки действует правило «нет ответа = не включать»: мы **не** заявляем
> нигде, что наш репозиторий в хабе, и не считаем молчание согласием.
>
> Факты — только из `EVIDENCE.md` со статусом `Verified`. Дата решения: 2026-11-08.

## Что известно на момент решения (Verified)

| # | Факт | Чем проверено |
|---|---|---|
| 1 | Письмо — настоящий consent-запрос конвейера (PR #2895: «10 044 repos … generated daily by the outreach pipeline») | `EVIDENCE.md` B6 |
| 2 | Нас в хабе **нет**: 0 совпадений в `hub.xerj.org/llms.txt` (559 корпусов) | B4 |
| 3 | Пака с нашим кодом нет, строки в `CONTRIBUTORS.jsonl` нет | B5 |
| 4 | Пак несёт `licence.spdx` + класс, но **не** текст copyright/LICENSE | B10; `docs/CORPUS_PACKS.md` |
| 5 | Их аудит 2026-10-28: 4 из 5 строк `consent-pending`, 1 `consent-lapsed`, «Triage counted it as a yes by mistake» | B8 |
| 6 | #3002: страница утверждала «with the author's permission», автор сказал обратное | B9 |
| 7 | Наша публикуемая сборка из public `main` не воспроизводится (проприетарные крейты, формат 3 vs 4) | A18 (это про них, не про нас) |

Вывод из 4–6: у их конвейера consent **не** является ограничением записи, а «нет
ответа» уже один раз было посчитано как «да». Поэтому вариант «промолчать» — не
нейтральный: он оставляет нас в серой зоне, где решение примет их триаж.

## Решение: **да, с условиями** (вариант 1 из `PLAN.md`)

Причины выбора:
- включение даёт распространение и внешнюю ссылку — при нулевых затратах с нашей
  стороны (код MIT, PR не нужен);
- три условия ниже закрывают именно те дефекты, которые уже были у них (B8, B9, B10);
- отзыв возможен в один прогон — то есть цена ошибки ограничена.

Отвергнуто: «нет» (нет причины отказывать при MIT и явных условиях) и «позже»
(молчание они уже трактовали как «да», B8).

## Текст письма (отправлять как есть; язык адресата)

> Subject: Re: inclusion of ManSio/mscodebase-intelligence in the XERJ corpus hub
>
> Hello,
>
> Yes — you may include `ManSio/mscodebase-intelligence` in the corpus hub, on
> these three conditions, all of which we ask you to confirm in the reply:
>
> 1. **Pin.** Use commit `64215b1` (2026-10-03) — the revision you reviewed. Record
>    it as `pin_sha` in the catalogue entry, and if you later refresh it, say which
>    commit the pack was built from.
> 2. **Wording and licence text.** Describe the use as "used under the MIT licence,
>    with attribution to ManSio", not "with the author's permission". Our
>    `LICENSE` (MIT) must travel inside the pack; `licence.spdx = MIT` alone does
>    not carry the copyright notice.
> 3. **Revocation.** If we ask to be removed, removal happens in a single pipeline
>    run, and `do-not-contact.json` gets an entry for us so a later refresh does
>    not re-add the repository.
>
> We do not ask for a review, a rank or any editorial claim about the project.
> Please do not describe inclusion as an endorsement by us or by you.
>
> — ManSio

## Что меняется у нас (и что нет)

- **Ничего в коде.** Наш MIT `LICENSE` уже есть; отдельного «consent-файла» не
  требуется — согласие живёт в переписке, а не в репозитории.
- **Не заявлять.** В README/доках не появляется строка «we are in the XERJ hub»,
  пока включение не подтверждено фактически (0 совпадений в `llms.txt` сегодня).
- **Проверка после отправки** (когда письмо уйдёт):

  ```
  Invoke-WebRequest https://hub.xerj.org/llms.txt | Select-String -SimpleMatch "mscodebase"
  gh release list -R xerj-org/xerj --limit 30 | Select-String -SimpleMatch "mscodebase"
  ```

  0 совпадений = ещё не включено (не «отказали»). Машинная сверка — по этим двум
  командам, а не по ответу письма (§19.20).

## Если владелец выберет другой вариант

- **Нет:** заменить текст на «please add `ManSio/mscodebase-intelligence` to
  `do-not-contact.json` with `no-include`» — и всё равно отправить, чтобы молчание
  не стало «да».
- **Позже:** ответить «not now, revisit after <дата>» и **явно** написать, что до
  этого момента включать нельзя.

Любой вариант отменяет текущий текст; решение владельца фиксируется здесь же
отдельной строкой с датой.
