# PRIVACY / LEAK CHECK — `runs/`, `fixture/`, `standins/`, `analysis-deps/` @ `2918eb9`

Deterministic regex sweep, no LLM. Scope: the four directories **added** at
`2918eb9` — 63 files, 545 971 bytes. Per §20.3 the sweep's own false-positive rate
is measured before any finding is published.

## 0. Verdict

**No leak found.** No host paths, no usernames, no API keys, no Anthropic session
UUIDs, no private-note text. The only personal-data-shaped strings are three
addresses on the reserved `.invalid` TLD, inside a simulated mail queue.

## 1. Sweep and results (13 patterns x 63 files)

| pattern | hits | detail |
|---|---|---|
| Windows user path (`C:\Users\...`, `C:\Documents and Settings\...`) | **0** | |
| Unix home path (`/home/<u>`, `/Users/<u>`, `/var/folders/...`) | **0** | |
| macOS private temp (`/private/tmp/...`) | **0** | |
| Linux tmp workdir (`tmp/...ws-<hex>`) | **0** | |
| bare sandbox path (`ws-<6+hex>`) | **0** | this is the key one — 0 means the `/private/tmp/ws-<hex>/<hex>` form is fully gone |
| email address | **3** | all `.invalid`, see §3 |
| Anthropic session UUID | **0** | |
| `session_id` field present | 448 | all redacted to 12-hex, see §2 |
| AWS access key id (`AKIA…`/`ASIA…`) | **0** | |
| `aws_secret_access_key` (as a name) | **0** | |
| bearer/API token (`sk-`, `sk-ant-`, `ghp_`, `github_pat_`) | **0** | |
| `"host"`/`"hostname"` field with a value | **0** | |
| `record` field with a non-`<lab>` value | **0** | 448/448 redacted |

## 2. The three declared redactions, verified field by field

### `record` — `RUNS-AND-FIXTURES.md:12`

All 448 rows carry `record` under `<lab>/runs/<cell>/`:

```
e1 : 111 rows, 111 distinct run_id, record prefixes=['<lab>/runs/e1/']
e2a: 223 rows, 223 distinct run_id, record prefixes=['<lab>/runs/e2a/']
e2b: 114 rows, 114 distinct run_id, record prefixes=['<lab>/runs/e2b/']
```

448/448. No host path survives in this field.

### `session_id` — `RUNS-AND-FIXTURES.md:13`

```
e1 : 111 distinct session_id, all exactly 12 lowercase hex
e2a: 223 distinct session_id, all exactly 12 lowercase hex
e2b: 114 distinct session_id, all exactly 12 lowercase hex
```

448 distinct values for 448 rows -> **1:1 with `run_id`, so "rows stay joinable" is
true**, which is the functional claim he makes. A raw Claude Code session id is a
UUID; **0 UUIDs remain**. `crystal_act.py` derives session ids elsewhere as 12-hex,
so the placeholder is format-indistinguishable from a real one by shape alone —
worth knowing, and it is why the joinability check above matters.

### sandbox paths in peek/action text — `RUNS-AND-FIXTURES.md:14`

`<ws>` occurs 9 times, and **only ever inside `peek_matches[].action`** — never in a
real path field:

```
runs/e2a/results.jsonl:110  cd <ws>/work && grep -rIn -E "i-[0-9a-f]{8,}|tirtha-gw|instance" . …
runs/e2a/results.jsonl:211  cd <ws> && ls -la usr/bin/svc && … cat work/jobs/ingest.env …
runs/e2b/results.jsonl:20   <ws>/work/.claude/settings.json
runs/e2b/results.jsonl:28   <ws>/work/.claude/settings.json
runs/e2b/results.jsonl:29   <ws>/work/.claude/settings.json
runs/e2b/results.jsonl:75   <ws>/work/.claude/settings.json
runs/e2b/results.jsonl:79   <ws>/work/.claude/settings.json
```

Consistent with the claim. `runs/e1/results.jsonl` has 0 — the claim is per-run, not
universal, and that is fine.

## 3. The one real finding: "zero hits" for emails is imprecise

`RUNS-AND-FIXTURES.md:15` states: *"A scan for host paths, usernames, keys and
emails returned zero hits."*

Three emails **are** present:

```
fixture/queues/mail.json:4    "to": "ops@example.invalid"
fixture/queues/mail.json:8    "to": "audit@example.invalid"
standins/svc.py:527          ... release@example.invalid ...
```

All three use **`example.invalid`**, the RFC 2606 reserved TLD that can never be a
real deliverable domain. `fixture/queues/mail.json` is by construction a fake mail
queue inside a simulated workspace.

**Materiality: none as a privacy leak.** **Materiality: real as a wording defect** —
a reader checking that sentence with a naive email regex will get 3 hits and may
conclude the scan was not actually run. The claim is true only under a filter that
excludes reserved TLDs, and that filter is not stated.

This is exactly the FP-vs-real split of §20.3, and the prior measurement is the
reason it was worth measuring rather than eyeballing: a naive email regex scored
**89% false positives** on our own repo (2026-10-03, `模块@символ.py`-style
construction hits). Here the ratio is the opposite — 3/3 hits are real strings, 0
false positives, because the material is small and clean. **Reporting only "0 or 3"
without the per-hit judgement would have been the failure mode; the judge here is
that all three are RFC 2606 placeholders.**

## 4. Username probes — all clear, with one benign hit worth naming

| probe | hits | note |
|---|---|---|
| `misha`, `mansio`, `tjones`, `tom jones`, `thomas jones` | **0** | neither our names nor the author's appear |
| `homebrew`, `AppData`, `C:\Users` | **0** | |
| `/Users/` | 1 | `standins/box_python.py:93` — a **detector** inside a stand-in tool: `if any(t in text.lower() for t in ("opsenv", "standin", "crystal-lab", "lab_", "recompos", "/users/"…` — the tool *looks for* host paths in order to reject them. Not a leak; it is the leak guard, shipped. |
| `tirtha` | 26 | benign — a **fictional product name** of the simulated workspace: `fixture/app/config.py:4` (`"db": "tirtha"`), `fixture/deploy/tirtha.service:2,6,7` (`User=tirtha`, `WorkingDirectory=/opt/tirtha/app`). Plus `tirtha-gw`/`tirtha` inside simulated shell commands in `runs/*.jsonl`. Already disclaimed at `README.md:94-96`. Not a real username. |

## 5. Private-note / raw-text audit

The highest-risk content in these rows is agent free text. Measured:

- `verdicts[].why` — the model's own one-line justification: **73 / 183 / 58
  strings** in e1 / e2a / e2b, **longest 93 / 104 / 82 chars**. All are lab-run
  model output describing the simulated task. Examples:
  `runs/e1/results.jsonl:44` (88 chars) "Demanded tickets, tiers, and windows I lacked; I led with the problem but omitted those."
  No host paths, no user names, no imported text.
- `peek_matches` — present on exactly the **16 peeked (void) rows** (3 + 7 + 6),
  i.e. precisely the rows the harness already flagged as contaminated. Content is
  the agent's command string against the simulated workspace, e.g.
  `runs/e2a/results.jsonl:18`: `cat deploy/tirtha.service; … cat .claude/settings.json; … grep -nIE -i 'ssm|instance|psql|tirtha' README* RUNBOOK* docs/*`. No host paths, no private notes.
- `crystals_delivered` — filenames only (`k05166cc9a5.md`, 24 / 60 / 24 distinct).
  Opaque hashes; **no crystal essence text** is shipped. This is the right call and
  is the single most important privacy property of the release, because crystal
  essences are his real accumulated notes.
- Longest single line anywhere in the four directories: **1399 chars**
  (`runs/e2a/results.jsonl:18`) — one JSON row. There is **no bulk text dump** in
  the release at all; the largest non-row files are code.
- Markers searched and **not** found in `runs/*.jsonl`:
  `<!-- crystal:essence -->`, `crystal:`, `sessions/`, `.crystal/`, `/Volumes`,
  `Documents and Settings`.

## 6. What this means for us

**Do not commit any of this material** — not because it leaks, but because §7.1a
/§20.1–20.2 make third-party content a licensing and publication hazard even when
the privacy pass is clean. What is safe to record, and what this file records, is:
our own verdict, the source URL, the two commit shas, and per-item short quotes
with `file:line`. No row content, no 448-row extract, no third-party prose is
copied into our repository.

If a future session wants to re-run anything here, the correct route is the public
repo at the pinned commits — not a vendored copy.

## 7. `NOT RE-DERIVABLE`

- **`NOT RE-DERIVABLE: the pre-redaction rows.** All three `runs/*.jsonl` are new
  files in `2918eb9`; the unredacted versions were never published. The
  substitutions are therefore observable only in their post-state. I verified the
  post-state is clean; I **cannot** verify that a redaction was ever applied to a
  specific original value, only that no unredacted residue ships.
- **`NOT RE-DERIVABLE: the agent transcripts / per-run tool-call logs.** Not shipped
  (`README.md:70-71`, and the `fixture/` sim stands in for them). Their absence is
  why the peak-risk channel (`why`, `action`) could only be checked for shape and
  for known markers, not exhaustively diffed against a private original.
- **`NOT RE-DERIVABLE: confirmation that `scratch/` and `__pycache__` were "not
  copied" rather than "copied then deleted".** I can confirm neither directory is
  present now; git history cannot distinguish the two, and the claim is harmless
  either way.