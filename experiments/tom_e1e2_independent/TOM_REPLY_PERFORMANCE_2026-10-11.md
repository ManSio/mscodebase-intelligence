# Reply draft — performance follow-up (2026-10-11)

Status: DRAFT, not posted. Awaiting owner's word (post only on explicit approval).
Language: EN (Tom's thread). Voice: same as the published comment.
Corrects, on our side only: the scale paragraph ("Scale is linear into pain") and the
ledger line in "Caveats we keep attached" of TOM_COMMENT_DRAFT.md (the published comment).
All numbers re-measured 2026-10-11, Defender OFF unless labelled, same session, same
harness, fresh store with a unique nonce per run. Raw: scale_forensics/REMEASURE.json,
AB_DEFENDER.jsonl, INVESTIGATE_SCALE.json.

---

Performance follow-up — the 100–200× gap was ours, not the code

You asked for the measurement boundary; re-running the timing suite with Windows Defender real-time **OFF** turned two of our published numbers into measurement artifacts and one into a real finding. Everything below is ours to correct.

## 1. Defender real-time inflated our load ~25–30× (via content-verdict caching)

A/B at n=1000, identical code, only the Defender toggle differs:

| run  | RT  | load cold | load warm | µs/file (cold) |
|------|-----|-----------|-----------|----------------|
| on1  | ON  | 10.3045 s | 0.5604 s  | 10304 |
| on2  | ON  |  8.9341 s | 0.3752 s |  8934 |
| off1 | OFF |  0.3176 s | 0.3236 s |   318 |
| off2 | OFF |  0.3310 s | 0.3298 s |   331 |

"Cold" = fresh unique files (Defender scans them). "Warm" = the same files again — and with Defender ON it drops to 0.38–0.56 s, because Defender caches its verdict **by content**. So the ~28–32× gap is the first-touch scan, and it vanishes once Defender has seen the bytes. Our published "load 0.87 / 8.02 / 39.07 s (100/1000/5000)" is the ON class (8.7/8.0/7.8 ms/file, ~25× the OFF value) — it moved with a background scanner, not with your code.

This is exactly where our own "Windows untested" caveat bites: it does not footnote those numbers, it invalidates them.

## 2. Our match number was a re-load, not a match

`candidates(repo=...)` re-reads the whole store (`crystal_act.py:416`), so "match 0.35 ms/crystal" was a second `load_crystals`. Separated, Defender OFF:

| n | load_cold | candidates(repo) | match (preloaded) |
|---|-----------|------------------|-------------------|
| 100  | 0.0321 s | 0.0312 s | 2.199 µs/crystal |
| 1000 | 0.3177 s | 0.3134 s | 2.064 µs/crystal |
| 5000 | 1.6160 s | 1.6681 s | 2.211 µs/crystal |

`candidates(repo)` ≈ `load` at every n (it re-loads); pure match on a preloaded list is 2.1–2.2 µs/crystal, flat in n and identical with Defender ON (2.10–3.86 µs; the first ON run is warm-up noise). That is your ~3 µs. Matching does not disagree by 100× — it agrees.

Boundary we used: `time.perf_counter()` around `load_crystals(str(store))` and around `candidates(...)`; pass a preloaded crystal list for pure matching.

## 3. The ledger does degrade — linearly (the real finding)

We published "ledger size does not degrade delivery (0.014 s at 3 vs 0.059 s at 20,002 — the prune holds)". The first loop in that script never ran, the numbers were never persisted, and I misread a stale file. Re-measured, Defender OFF:

| entries | due_for() |
|---------|-----------|
| 3       | 0.0027 s |
| 2 002   | 0.0065 s |
| 20 002  | 0.0547 s |
| 40 002  | 0.1099 s |

Fits `due_for ≈ 0.0027 s + 2.7 µs × entries` — linear, no cliff (3→40 002). The cost is the JSON parse of the whole ledger on every `due_for` call. Not a bug, but it grows with history; parse-once/cache removes it. This is the one thing worth your time in this message.

## 4. The pain thresholds were downstream of the bad match number

We said "500 ms at ~1,400 crystals". Corrected: load crosses 500 ms at ~1,570 files (318–323 µs/file); pure match crosses 500 ms at ~238,000 crystals (2.1 µs/crystal). The old figure blended the re-load with the Defender-inflated load.

## What else we re-checked with Defender OFF (all hold)

- **Delivery + order**, your dispatcher on the isolated store: 30/30 checks, order repeat=True, blinded=True — the defect verdicts are unchanged; Defender only moved the clock.
- **Context:** 10 MB ctx in 0.486 s (was 0.41) — no ReDoS still.
- **Controls re-run:** `sleep(50 ms)` → 50.3 ms; empty store load 0.00041 s (n=0); empty candidates 0.

<details>
<summary>Load-cost attribution (n=1000, Defender OFF) — why the residual is Windows, not your code</summary>

| stage | time (n=1000) |
|-------|---------------|
| walk | 0.0016 s |
| stat | 0.0127 s |
| **open (head)** | **0.1357 s** |
| open (full) | 0.1293 s |
| parse binding | 0.0088 s |
| essence | 0.0038 s |
| total load_cold | 0.3012 s |

The per-file `open` (~136 µs of the ~300 µs/file) dominates. Fixture essence 1335 chars vs your ~1000. Defender OFF our load is still ~9× your 37 µs/file, on a platform your `INSTALL.md` declares untested — read the absolute load as out of scope, not a regression.
</details>

## What survives, what changes

- **Survives:** scale is linear; the mechanics stand; your ~3 µs match is confirmed on a different OS and language.
- **Changes:** every absolute in our scale paragraph and the ledger line in "Caveats we keep attached" should be read through this correction.

Separately: we re-derived our own overlap suite from scratch (independent implementation of the spec, 416/416 rows, 171 nonzero / 245 zero controls) to close the one artifact on our side that had no saved producer. It reproduces exactly.
