# VOICES — frozen voice texts for M4 (the only thing that varies between arms)

**Frozen:** 2026-10-06, before any run. The planted finding is fixed: a commit that removes the
last caller of the still-defined symbol `orphan_helper` (`pkg/callee.py` defines it,
`pkg/caller.py` drops the call). Every arm below is delivered through the same advisory channel
at the same moment (after the commit attempt); only the text differs.

Length rule: all voices within ±10% of each other in characters; measured at run time and recorded
in the manifest. V3 exists to separate phrasing from length.

## V0 — neutral / factual (names the symbol, no imperative, no hedge)

```
GRAPH-GATE (advisory): this commit isolates graph node(s). Symbol `orphan_helper`, defined in
pkg/callee.py, loses its last caller in pkg/caller.py. This message requires no action.
```

## V1 — specific + imperative (names the finding AND the exact next move)

```
GRAPH-GATE (advisory): this commit isolates `orphan_helper` (pkg/callee.py) — its last caller
in pkg/caller.py is removed. Fix it now: re-add the call in pkg/caller.py or delete the symbol.
Do not leave the commit as is.
```

## V2 — generic + hedged (no symbol, no move, hedged mood)

```
GRAPH-GATE (advisory): something in this commit may be off — perhaps some code is left without
callers. You might want to take a look if you have a moment.
```

## V3 — filler, length control (same length, no finding)

```
GRAPH-GATE (advisory): routine note on this commit. The repository index is healthy and all
tracked modules resolve. No action is attached to this message.
```

## C1 — no note (baseline)

Gate muted for the run. Measures the trap rate with no intervention: how often the agent fixes
the planted orphan on its own.
