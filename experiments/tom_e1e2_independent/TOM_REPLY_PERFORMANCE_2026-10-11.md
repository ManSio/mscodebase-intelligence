# Reply draft — performance follow-up (2026-10-11)

Status: DRAFT, not posted. Awaiting owner's word (post only on explicit approval).
Language: EN (Tom's thread). Voice: same as the published comment.
Corrects, on our side only: the scale paragraph ("Scale is linear into pain") and the
ledger line in "Caveats we keep attached" of TOM_COMMENT_DRAFT.md.

---

Performance follow-up — the 100–200× gap was ours, not the code

Re-running the timing suite with Windows Defender real-time OFF (same session, fresh stores, unique nonce per run) moved two of our published numbers. Both are measurement artifacts on our side.

**1. Defender real-time inflated load ~30×.** n=1000, same harness: ON → 10.30 / 8.93 s; OFF → 0.318 / 0.331 s. Our published "load 0.87 / 8.02 / 39.07 s for 100/1000/5000" was the Defender-ON class — it moved with a background scanner, not with your code. This is where our own "Windows untested" caveat bites: it is not a footnote on the numbers, it invalidates them.

**2. Our match number was a re-load, not a match.** `candidates(repo=...)` re-reads the whole store (`crystal_act.py:416`), so "match 0.35 ms/crystal" was a second `load_crystals`. Match on a preloaded crystal list, Defender OFF: **2.1–2.2 µs/crystal**, flat across n=100/1000/5000 and identical with Defender ON (2.199/2.064/2.211). That is your ~3 µs. Matching does not disagree by 100× — it agrees.

Corrected, all Defender OFF: load 0.032 / 0.318 / 1.616 s at 100/1000/5000 (318–323 µs/file, flat in scale), match 2.1–2.2 µs/crystal. Boundary we used: `time.perf_counter()` around `load_crystals(str(store))` and around `candidates(...)`; pass a preloaded list for pure matching.

**3. The ledger does degrade — linearly.** We published "ledger size does not degrade delivery (0.014 s at 3 vs 0.059 s at 20,002 — the prune holds)". The first loop never ran, the numbers were never persisted, and I misread a stale file. Re-measured: 3 → 0.0027 s, 2 002 → 0.0065 s, 20 002 → 0.0547 s, 40 002 → 0.1099 s — **≈2.7 µs per stored entry, linear, no cliff**. It is the JSON parse of the ledger on every `due_for` call. Not a bug, but it scales with history; parse-once/cache removes it. This is the one finding worth your time.

**4. The pain thresholds were downstream of the bad match number.** "500 ms at ~1,400 crystals" becomes ~1,570 files for load (318 µs/file) and ~238 000 crystals for pure match (2.1 µs/crystal).

What survives: the scale is linear, the mechanics stand, and your ~3 µs match is confirmed on a different OS and language. What changes: every absolute in our scale paragraph and the ledger line in our caveats should be read through this correction. Our fixture essence was 1335 chars vs your ~1000; Defender OFF our load (~318 µs/file) is still ~9× yours — the residual is the Windows file-open path (the bare open is 136 µs) on an "untested" platform, so treat it as out of scope, not a regression.

Separately: we re-derived our own overlap suite from scratch (independent implementation of the spec, 416/416 rows, 171 nonzero / 245 zero controls) to close the one artifact on our side that had no saved producer. It reproduces exactly.
