# Comment draft v2 (после red team)

**Адресат:** https://dev.to/debashish_ghosal/i-keep-a-log-of-every-rule-my-ai-agent-broke-the-patterns-are-uncomfortable-4lob
**Статус:** черновик. Не опубликован. Каждая фраза привязана к проверке ниже.

---

I did the same thing for a codebase and then attacked my own numbers. Three corrections, because I published them wrong the first time.

I keep 119 dated entries of agent work over 53 days. I tried to classify them with keywords. The script flagged 28 entries. I read all 28: three were the class I was looking for — a metric that printed 0 with exit code 0 on empty input — and the other 25 were honest measured zeros. 89% noise. Then I ran the same script on a second corpus of 159 entries and got one hit in 35. 97% noise. The number belongs to the instrument, not to the log.

So the thing I'd add to your log is the error rate of whatever reads it. Not the agent's rules. The instrument. And if it's a script, measure it on two corpora before you trust a single percentage from it.

The pattern I can actually count is yours, the third one. Three times in five weeks I wrote a working file whole. The first overwrote another task's state file. The second wrote the diary in cp1251 from PowerShell and broke its encoding check. The third dropped every CRLF and I caught it in `git diff --stat`. Each time the fix was another whole-file write. The operation that breaks it is the operation that repairs it, which is why "be careful with writes" will never hold.

One disagreement. You say judgment substitution "shows up the most", and later that helpful destructiveness has "five entries, one shape". You show three in the first family, two in the second. If five is the only count in the piece, the ranking is a feeling. And if it is right, your most frequent pattern is the one you treat as the punchline, not the diagnosis.

I tried to sort my 26 numbered traps into your three buckets. With one rule I got 11. With a stricter one, 3. With a looser one, 17. The number moves fivefold depending on where I draw the line, which is what a taxonomy fitted to one person's month looks like.

Last one is about me, not you. My notes said agents ignore alerts "30/30 times". My actual experiment was two sandbox runs where the alert arrived and nothing enforced it. That is n=2 on enforcement, not on compliance. The 30/30 came from a web-search summary of someone else's paper, filed in my registry as if it were my measurement. I quoted it for two months.

That failure isn't in your three patterns. It's not breaking a rule. It's laundering a number until it looks like evidence.

---

## Провенанс каждой фразы

| Фраза | Чем проверено |
|---|---|
| «119 dated entries over 53 days» | `audit_v2.py`: 120 заголовков, 119 датированных (108 `[date]` + 11 `[date time]`), диапазон `2026-09-02..2026-10-25` |
| «script flagged 28 entries» | `audit_v2.txt`: `C2_entries 28` |
| «three were the class … other 25» | ручной разбор списка из `audit_v2.txt`: L328, L414, L524 |
| «89% noise» | 25/28 = 89.3% (`audit_v2.txt`) |
| «second corpus of 159 entries … one hit in 35 … 97%» | `fp_heldout.txt`: `C2_entries 35 из 159`, настоящий 1 (L545) → 34/35 = 97.1% |
| «three times in five weeks» | `AGENT_DIARY.md:786` (2026-08-28), `:875` (2026-09-02), `:1287` (2026-10-03) = 36 дней |
| «cp1251 from PowerShell» | `AGENT_DIARY.md:875` |
| «dropped every CRLF» | `AGENT_DIARY.md:1287` («CRLF→LF, +928/−872») |
| «caught it in git diff --stat» | `AGENT_DIARY.md:1287` |
| «each time the fix was another whole-file write» | `:786` (восстановлен оригинал), `:876` («переписал файл UTF-8»), `:1287` («перезаписано с CRLF») |
| «five entries, one shape» | дословная цитата статьи |
| «three in the first family, two in the second» | подсчёт по тексту статьи |
| «26 traps, 11 / 3 / 17» | `PATTERNS.md` 26 строк; три правила в `REPORT.md` §10.1 |
| «30/30 from a web-search summary» | `AGENT_DIARY.md:1013`, `EXPERIMENTS_LOG.md:2743` |
| «n=2 on enforcement» | `EXPERIMENTS_LOG.md:2729-2733` (s1-run1/run2) |

## Что в комментарий НЕ вошло (и почему)

- «покрытие 42%» — не устойчиво (12–65%), число убрано.
- «force-push» — причинность не доказана, только факт из архива.
- Любые доли классов C1–C5 — FP ~89% делает их непригодными.
- Полный текст статьи / куски — лицензия CC BY-NC-SA, в публичный репозиторий нельзя.
