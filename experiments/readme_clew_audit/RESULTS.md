# readme-clew-2 — независимый аудит

Target: `earlgreyhot1701D/readme-clew-2` @ `2e57d3f` (read-only clone, `_reference_repos/`)
Environment: Windows, Node v24.14.1, `core.autocrlf=true` (this mattered — see H1).
All experiments offline, $0.

Every number below has a command and raw output. Nothing is asserted from reading alone
unless marked **Verified by reading**.

---

## Verification Ledger

| # | Issue | Evidence | Status | Verdict |
|---|---|---|---|---|
| H1 | sync test red on Windows | `git ls-files --eol` `i/lf w/crlf`; 474/474 green after autocrlf=false | ✅ | **not their bug** — harness artifact |
| H2 | "474 tests, all offline" | `node --test` → tests 474, pass 474, fail 0 | ✅ | **CONFIRMED** as published |
| H3 | SPEC regex misses dynamic imports / `export…from` | 9/10 found by their own function | ❌ | **REFUTED** — only backticks missed |
| H4 | `coverage.js` substring ⇒ silent false negatives | 3 synthetic + 1 real corpus instance | ✅ | **CONFIRMED** |
| H5 | "precision <0.3, FP 70–90%" for `missing` | 1/22 suppressions on 6 repos | ❌ | **NOT SUPPORTED** by this corpus |
| H6 | "every guard shown failing once" | 6/7 mutants killed, no-op control green | ✅ | **substantially CONFIRMED** |
| H7 | body-size limit bypass (chunked) | `validate.js:34` checks real body bytes | ❌ | **REFUTED** by reading |
| H8 | rate limit spoofable via XFF | limiter self-declared non-authoritative | ⚠️ | real but **not a finding** (documented) |

---

## H1 — The one failing test is MY environment, not their code

First full run: `✖ sync: every copy in extension/ is byte for byte the file in web/`
→ `actual: ['extension/shared/README.txt']`.

That file has no `web/` counterpart — it is compared against the `NOTE` constant
(`scripts/sync-extension.mjs:35-36`). Root cause:

    git ls-files --eol extension/shared/README.txt   ->  i/lf  w/crlf   (core.autocrlf=true)

Working copy is CRLF, constant is LF. Same commit, LF checkout:

    git config core.autocrlf false; git reset --hard
    node --test   ->  tests 474 / pass 474 / fail 0

**Their guard is fail-closed and worked correctly — it caught a real byte difference.
My checkout produced it.** Reported to the author only as: *no `.gitattributes`, so this
test is red on any Windows checkout*. Not as "your sync is broken".

## H2 — their headline suite claim holds

`npm test` → **474 passed, 0 failed**, offline, no keys. Exactly the README's claim.

## H3 — REFUTED: the regex is better than the third-party review says

A third-party agent asserted the `SPEC` regex in `lib/verifiers/dependencies.js:6`
"does not catch dynamic imports and `export ... from`". Calling their own function:

    POS 9/10   NEG 3/3
    ok  export ... from        -> found
    ok  export * from          -> found
    ok  dynamic import()       -> found
    ok  require()              -> found
    FAIL dynamic import(`pkg`) -> MISSED   (backtick literal only)

`\bfrom\s*['"]` covers `export…from`; `import\s*\(?\s*['"]` covers `import()`.
The only real gap is a **template literal** specifier. Publishing the original claim
would have put a false technical assertion in front of the author.

## H4 — CONFIRMED: `coverage.js:24` silently drops real Missing findings

    if (readme.includes(name.toLowerCase())) continue;

Substring test over the whole lowercased README. Ground truth by construction,
both controls green (`absent pkg MUST be flagged` ok, `named pkg MUST NOT be flagged` ok):

| case | flagged | should be |
|---|---|---|
| `"once you got it working"` + package `got` | **false** | true — "got" is the English verb |
| `"use the canvas element"` + package `can` | **false** | true — "can" inside "canvas" |
| `"we use lodash-es not lodash"` + package `lodash` | **false** | true — a *different* package |
| `"Uses the MCP SDK"` + `@modelcontextprotocol/sdk` | **true** | false — documented under alias |

**Real instance, not synthetic** — `sindresorhus/yocto-queue @72a8fa9`:
declared devDependency `ava` is suppressed because the README contains

    mozilla.org/en-us/docs/web/javascript/reference/iteratio…

whose "**ava**script" contains `ava`. Standalone-token test: `False`.
A genuine Missing finding disappears without a trace.

**Why this is the right thing to raise:** it is the inverse of the failure mode they
spend the README defending. They guard hard against *false accusations*; this is a
*missed real finding*, which is the other half of trust. Cheap fix: require a token
boundary instead of `includes`.

## H5 — NOT SUPPORTED: "precision <0.3, FP 70–90%"

Frozen corpus of 6 real repos (`frozen/CORPUS.md`, SHAs pinned before running):

    suppressed total           : 22
      genuine token mention    : 21
      SUBSTRING-ONLY (bug hits): 1     (4.5%)

So the substring defect is **real but rare** in the wild. I did **not** hand-label the
`missing` findings, so I make **no claim** about their precision. The third-party figure
is not reproduced here and will not be repeated to the author as fact.

## H6 — CONFIRMED: their guards really do fail loudly

Mutation test of the load-bearing fail-closed guards, one at a time, scratch copy,
full suite each time. No-op control stayed green (harness is not manufacturing redness).

| mutant | broken guard | result |
|---|---|---|
| M1 | prose guard → always code-context | **KILLED** (4 fails) |
| M2 | 0.8 gate removed | **KILLED** (5) |
| M3 | platform-set env vars not exempt | **KILLED** (1) |
| M4 | unread-config guard removed | **KILLED** (1) |
| M5 | Missing suppression removed | **KILLED** (13) |
| M6 | import scan extension filter removed | **survived** |
| M7 | build-output exclusion renamed | **KILLED** (17) |

**6/7 killed.** M6 survives but is **redundant, not a bug**: `github.js:14,45`
`isSourcePath` already restricts `sources` to JS/TS before `importedPackages` sees it.
Reported as redundant defence-in-depth, not as a defect.

## H7 — REFUTED: no body-size bypass

`api/scan.js:44` checks `content-length` (absent on chunked requests), but
`lib/validate.js:34` re-checks `Buffer.byteLength(rawBody)` on the real body.
Closed.

## H8 — rate limiting: honest by construction

`lib/ratelimit.js:1-2` states the limiter is best-effort and "NOT a real ceiling";
the real ceiling is the prepaid balance, the Anthropic spend cap and a firewall rule.
Taking the leftmost `x-forwarded-for` is client-influenceable, but they never claim
that limiter is authoritative. Not a finding.

---

## What I did NOT verify (and will not claim)

- **Self-scan "0 Contradicted" on their own README** — reproducing it needs live Jev
  API calls. Paid, and not authorised. **Not reproduced.**
- **Precision of `missing` on real repos** — needs hand-labelling of every finding.
- **The 0.8 threshold empirically** — their own eval data exists under `evaluation/`;
  not yet analysed. The code itself calls 0.8 a prior, not a measurement, and I agree
  with that characterisation.

## Reproduce

    cd experiments/readme_clew_audit/harness
    node EXP_import_recall_probe.mjs        # H3
    node EXP_coverage_substring.mjs         # H4 synthetic
    node EXP_missing_real_corpus.mjs        # H4 real corpus
    node EXP_mutation_guards.mjs            # H6