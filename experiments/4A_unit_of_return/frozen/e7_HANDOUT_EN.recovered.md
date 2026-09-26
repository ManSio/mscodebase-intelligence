# RECOVERED ARTIFACT — E7 HANDOUT v2 (frozen input)

> **Это восстановленный артефакт, а не реконструкция по памяти.**
> Источник: `opencode.db` (сессия `ses_f3619ed80ffexz7XO14iPQ5a5w`), `write`-part `rid=75331`
> (2026-09-22), сверено с более поздним `read` того же файла (`rid=75864`) — содержимое идентично.
> Оригинальный путь был `C:\...\Temp\opencode\e7\HANDOUT_EN.md` (утерян при чистке temp 2026-09-26).
> Timestamp исходника **до** E11 и до F3-research → pre-look целостность сохранена.
> **Оговорка:** помечено «HANDOUT v2»; проверить перед использованием как frozen, что это финальная
> версия, которой гоняли E7 (при необходимости вытащить промежуточные `edit`-part'ы).
> SHA256 фиксируется в `AGENT_DIARY.md` и commit-body (не в самом файле — иначе хеш цикличен).

---

# HANDOUT v2 — symptom index mapping (blind)

Instruction: For **each** numbered item, pick **one** entry from the index that best explains it, or `NONE` if none fits. Do not force a match. Answer as a table: `# -> entry`. Answer from the text only; do not use tools, search, or MCP.

## Items

1. All tests pass, but when I open the app and click the button, nothing happens.
2. Background reindex shows ETA "~8s" and progress freezes at "Finalizing".
3. Postgres replication lag grows linearly under write load.
4. I deleted an entire function and the test suite stayed green.
5. CI is red on ruff errors that are only caught after push.
6. My GPU driver crashes when the batch size exceeds 64.
7. Hung `git cat-file` processes; `git.exe`/`conhost` chains multiply; RAM climbs.
8. `lock_guard` raises `ThreadExpired`: timeout 60s < pre-commit duration 5-10 min.
9. I compared my new build against my old one and the numbers were identical, so I said the change did nothing.
10. A test is green but `MagicMock.embedding_dim` is truthy.
11. The CSS grid collapses only in Safari 17.
12. `drift_gate` is a false negative: the control never fired on real drift.
13. `verify-on-read` retracts true facts (false-retraction).
14. The TESTS signal ranks tests but does not improve answer quality.
15. Tests fail locally but pass in CI (after clearing `__pycache__`).
16. My coding agent won't use my high-level code-intelligence tools; it keeps reaching for raw grep instead.

## Index (symptom -> entry)

| Symptom | Entry |
| --- | --- |
| The whole suite is green and the shipped binary draws an empty box | a-component-that-needs-starting-passes-every-behaviour-test |
| A guard has never fired and I assume that means things are fine | a-guard-keyed-on-a-field-nobody-fills-is-a-silent-no-op |
| I deleted the code on purpose and the test still passed | a-surviving-mutant-can-mean-the-code-is-dead |
| My before and after look identical, so the change did nothing | a-control-built-from-the-treated-arm-is-not-a-control |
| My immutability test passes and the operation still edits the caller's copy | testing-rejection-is-not-testing-immutability |
| I turned the sampling rate all the way up and almost nothing was sampled | a-rate-knob-cannot-fix-a-denominator |
| My benchmark ranking flipped between two identical runs | a-single-run-ranking-is-noise-even-at-temp-zero |
| Two tools share the same rule and give me different answers | an-instrument-that-answers-a-different-question-can-be-wrong-two-ways |
| I am being rate limited, and backing off does not help | a-cached-429-is-not-a-rate-limit |
| A figure is correct and its premise is dead | a-number-that-moves-without-new-data-is-an-assumption |
| The file validates and the output still looks wrong | a-generated-document-is-unverified-until-you-render-it |
| My test harness reports bugs that do not reproduce by hand | an-instrument-that-reshapes-input-fabricates-the-test |
