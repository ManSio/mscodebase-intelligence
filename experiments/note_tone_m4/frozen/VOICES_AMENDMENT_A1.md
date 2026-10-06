# VOICES Amendment A1 — length re-match (pre-run, no voice verdict exists anywhere)

**Reason:** frozen VOICES.md lengths are V0=181, V1=220, V2=155, V3=155 (max/min 1.42) —
outside the ±10% rule, measured in smoke run 1 (V1=220 vs V2=155, 29.5% apart). The smoke produced
no voice contrast verdicts, so this amendment is still pre-look. Originals preserved untouched in
VOICES.md; the texts below supersede them for all runs. Meaning and mood of each voice unchanged;
only length adjusted.

## V0 — neutral / factual (names the symbol, no imperative, no hedge)

```
GRAPH-GATE (advisory): this commit isolates graph node(s). Symbol `orphan_helper`, defined in
pkg/callee.py, loses its last caller in pkg/caller.py. This message requires no action from you.
```

## V1 — specific + imperative (names the finding AND the exact next move)

```
GRAPH-GATE (advisory): this commit isolates `orphan_helper` (pkg/callee.py) — its last caller
in pkg/caller.py is removed. Fix it now: re-add the call or delete the symbol. Do not leave
it as is.
```

## V2 — generic + hedged (no symbol, no move, hedged mood)

```
GRAPH-GATE (advisory): something in this commit may be off — perhaps some code is left without
any remaining callers. You might want to take a careful look at the changed files if you have
a moment.
```

## V3 — filler, length control (same length, no finding)

```
GRAPH-GATE (advisory): routine note on this commit. The repository index is healthy, all tracked
modules resolve, and no finding is attached. No action is attached to this message.
```

## C1 — no note (baseline, unchanged)

Gate muted for the run.
