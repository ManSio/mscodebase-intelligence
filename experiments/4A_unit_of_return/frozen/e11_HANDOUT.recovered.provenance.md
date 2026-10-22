# Provenance — `e11_HANDOUT.recovered.md`

Recovered byte-exact from the opencode session database after the original temp directory was cleaned.
This file is the recovery's provenance header; the handout itself is unmodified.

| Field | Value |
|---|---|
| Recovered on | 2026-10-06 |
| Source DB | `%USERPROFILE%\.local\share\opencode\opencode.db` (opened read-only, `mode=ro`) |
| Session | `ses_f352beffaffe5EFOuUr9vpADUn` |
| Part id | `prt_0cb1b0cc7001CdV8kjbTE2r8Ii` (tool = `write`) |
| JSON path | `$.state.input.content` |
| Original path | `%TEMP%/opencode/e11/handout.md` — **directory no longer exists** |
| sha256 | `cd917be4257b65b5ebf511369d5e852d68ff165e7869e7da437f35400170e535` |
| Expected sha256 | identical (value recorded before the run; the materialised file matched it) |
| Size | 6,255 chars / 6,261 bytes UTF-8 |

## Why this recovery counts as pre-look (§17 / §19 recovery rule)

| Event | UTC timestamp |
|---|---|
| Handout written (the input) | 2026-09-22T21:52:22.727Z |
| First model invocation | 2026-09-22T21:52:57Z |

The input was written **35 seconds before** any model ran, as a single atomic `write` whose payload is
stored verbatim in the DB. Nothing was reconstructed from memory after a result had been seen, so this
is a legitimate recovery and the replay it enables is a real replay.

The three run outputs recovered from the same session are **results, not inputs**. They are cited in
`experiments/publication_audit_2026-10-06/RESULTS.md` as evidence of what happened and are not used as
an input to anything.

## Known contamination in the run outputs

All three stdout captures contain U+FFFD replacement characters on the PowerShell
`NativeCommandError` preamble lines (the `opencode.cmd :` stderr prefix). Every `# -> entry` answer
line is clean ASCII. The mojibake was **not** repaired — the bytes are kept verbatim so the artifact
stays faithful to what was captured.

## Related artifact

The 2026-09-26 file `crystal_catalogue_2026-09-26.md` in this directory is **not** this handout's
provenance. It was materialised four days after the E11 runs, from a live fetch of the upstream
catalogue, and it is the input to the F4b arm. E11's pre-look input is the file described above.
