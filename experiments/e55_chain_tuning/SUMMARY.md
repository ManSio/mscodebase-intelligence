# E55 — real chain modes + cheap flags

Clean production index (7,314 chunks) + rebuilt graph (12,753 nodes).

| Arm | hit@1 | hit@5 | code h1/h5 | docs h1/h5 | p50 |
|---|---:|---:|---:|---:|---:|
| hybrid | 0.688 | 0.771 | 0.825 / 0.900 | 0.000 / 0.125 | 45 ms |
| fast | 0.542 | 0.729 | 0.625 / 0.850 | 0.125 / 0.125 | 19 ms |
| quality | 0.688 | 0.771 | 0.825 / 0.900 | 0.000 / 0.125 | 48 ms |
| deep | 0.688 | 0.771 | 0.825 / 0.900 | 0.000 / 0.125 | 48 ms |
| quality_nodemote | 0.688 | 0.771 | 0.825 / 0.900 | 0.000 / 0.125 | 47 ms |
| quality_intent | 0.688 | 0.771 | 0.825 / 0.900 | 0.000 / 0.125 | 47 ms |
| quality_ru | 0.688 | 0.771 | 0.825 / 0.900 | 0.000 / 0.125 | 63 ms |
| quality_p3 | 0.688 | 0.771 | 0.825 / 0.900 | 0.000 / 0.125 | 89 ms |

## Verdict

- `quality` = `hybrid` = `deep`; **no parameter changes move hit@1**.
- `fast` is 2.4× faster but loses 14.6 p.p. hit@1.
- `demote`, `intent`, `ru_synonyms`, `p3` have **zero effect** on this panel.
- Docs hit@1 is 0 because docs are not in the candidate pool, not because of
  demotion. H1/H2/H3/H7/H8/H10 FAIL; H4/H5/H6/H9 PASS.
