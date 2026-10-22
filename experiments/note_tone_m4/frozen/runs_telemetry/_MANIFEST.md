# M4 gate telemetry — verbatim copy manifest

**Contents:** `run<N>.jsonl` in this directory is a BYTE-VERBATIM copy of
`%LOCALAPPDATA%\mscodebase\projects\<hash>\gate_telemetry.jsonl`, where `<hash>` and the source
path are the `data_dir` / run mapping recorded by the runner in `results/full<N>.json`. The bytes
were NOT modified, re-serialised or re-ordered, so no header can live inside the `.jsonl` itself;
the `telemetry_sha256` is therefore recorded in this sidecar instead.

**Extraction rule (reproducible):** for each run N in 1..30, read `data_dir` from
`experiments/note_tone_m4/results/full<N>.json`, open `<data_dir>/gate_telemetry.jsonl` in binary
mode, copy the bytes verbatim to `run<N>.jsonl`. If the destination already exists it is left
untouched (idempotent, do-not-clobber).

**Verification:** recompute `sha256` of each `run<N>.jsonl` and compare to the table below.

| run | data_dir (source) | bytes | telemetry_sha256 |
|---|---|---|---|
| 1 | `C:\Users\misha\AppData\Local\mscodebase\projects\8381c9f5` | 2396 | `1fb80596d9dafa0bbde4c117780aa7e39545e67ad68d343a8c960446733a0dfa` |
| 2 | `C:\Users\misha\AppData\Local\mscodebase\projects\01d89dc7` | 2280 | `4d75e6e3f93428c8571ebff5cc5ce3a4326e2fc32580f1f59297ea5693d3300c` |
| 3 | `C:\Users\misha\AppData\Local\mscodebase\projects\9fa0ca47` | 1645 | `811f924441da902877349249af702c1f03e45c324da4c5b5003b255b5f865eb2` |
| 4 | `C:\Users\misha\AppData\Local\mscodebase\projects\087672cc` | 1869 | `5ee5e5f1b34c22a1730ef4e5bc485d6db9453c7152595242e07e5b356517a7f6` |
| 5 | `C:\Users\misha\AppData\Local\mscodebase\projects\92d60982` | 1495 | `b337c3f8d8755ba85246c3960ff42c7fc266881fa985fe51c7f5a2f0608fe595` |
| 6 | `C:\Users\misha\AppData\Local\mscodebase\projects\39a8b9e6` | 2649 | `9a7bd8c7080e25f6c8d1b5ee4cf5b653e540b092df93e59756fdc7021cb7add9` |
| 7 | `C:\Users\misha\AppData\Local\mscodebase\projects\f70065b6` | 1383 | `f78d397e47d8ef7d70a78bbd8c1b74dd03890ea6ae8ddefce8d4f91c7ad86a03` |
| 8 | `C:\Users\misha\AppData\Local\mscodebase\projects\1288b6c8` | 2060 | `91feb3d4e3c00cbd972a6c7fdba306ff162d45104402e15c18075cd5bd17562a` |
| 9 | `C:\Users\misha\AppData\Local\mscodebase\projects\ae018f09` | 2727 | `b470939830be42947478ba785cbf809d57e89f02cf156f49f4e5b51171a216bf` |
| 10 | `C:\Users\misha\AppData\Local\mscodebase\projects\f7b1089a` | 1714 | `c4ee3df96245d631d83257f14873cd3742eea19072e0acd8ac44554feabdf3b0` |
| 11 | `C:\Users\misha\AppData\Local\mscodebase\projects\75be95db` | 422 | `9f69d8e095a5772fd3830ae4f50d063cedfe3297a522d634331e2bc0ff96d025` |
| 12 | `C:\Users\misha\AppData\Local\mscodebase\projects\bade7199` | 1502 | `5151cf61cd5e8fdd33f039df929e7566472a19314e357ea44d8e90c570fa0b93` |
| 13 | `C:\Users\misha\AppData\Local\mscodebase\projects\a405d320` | 1859 | `6507d322de38473ac89b70b0ec7778c3b44e7dae8be436c8f9763c9a31ad4fd2` |
| 14 | `C:\Users\misha\AppData\Local\mscodebase\projects\709706da` | 1883 | `8ae67e223b480fa733dbb3b7c28748c7a624ec74021c985744aabf1fbb0904f3` |
| 15 | `C:\Users\misha\AppData\Local\mscodebase\projects\c87342fb` | 1702 | `a3def03e011dc3f7ab9c7e2b42e237344c830c0983baf5ecf7a09ac6891f77e5` |
| 16 | `C:\Users\misha\AppData\Local\mscodebase\projects\f6b27155` | 1044 | `2e8dd3f82a4db7f2a566de9263a4fc252626604aeb48d3df5ffbeb58e933559b` |
| 17 | `C:\Users\misha\AppData\Local\mscodebase\projects\c312534d` | 980 | `f1b4fd57855394d4171d0ea0f78a0487d5a21edba3f4643b5826fe2dc0875441` |
| 18 | `C:\Users\misha\AppData\Local\mscodebase\projects\70d6a47f` | 2102 | `1a0dd2daf2df33c79bfd108d0100142297fd354cef1cb0bbea97041de9c51352` |
| 19 | `C:\Users\misha\AppData\Local\mscodebase\projects\f42a25ec` | 988 | `dcc45a00e4466ed6dba7a6079a3a9817698345e8105457a888ddff40ca73d81d` |
| 20 | `C:\Users\misha\AppData\Local\mscodebase\projects\815ddb85` | 812 | `c072729513640cd4d56d1ec11932e08b6ccb90e0a26e12671455b10f55f84f76` |
| 21 | `C:\Users\misha\AppData\Local\mscodebase\projects\24b17c5b` | 3565 | `9b19161c19a4f41d140a7c41c88333b5c171e38685546e00384aef0cf45d9bc4` |
| 22 | `C:\Users\misha\AppData\Local\mscodebase\projects\8467e0ca` | 1647 | `323b254780d50c1c05d98805bf01cb38898030cfc1d1ddf69e237c5756e269e5` |
| 23 | `C:\Users\misha\AppData\Local\mscodebase\projects\2eac4b6a` | 1055 | `459428c7d34b872ac78c1a5df37f189754f729a38f2ab47eb5d75eb9de6dbef2` |
| 24 | `C:\Users\misha\AppData\Local\mscodebase\projects\dbbfa20b` | 1018 | `17cc61962fec52e78428f2bd3a9f85ed7afee4dd41bf05b83e7a351c62b604f2` |
| 25 | `C:\Users\misha\AppData\Local\mscodebase\projects\db2bb999` | 1302 | `b3bac1b4a6068513ee0461874c176322b9cc511433f9cc84631d038ab7836b76` |
| 26 | `C:\Users\misha\AppData\Local\mscodebase\projects\4a2b410f` | 1124 | `44dbc4319f24841add639106d1e50d3d252beabcc383456f927f5fb189ab535d` |
| 27 | `C:\Users\misha\AppData\Local\mscodebase\projects\43656b1a` | 2111 | `0888991851b7ae33c5583c4221f79f2db0525fab8f33dbd1f6d76c2d99e08b26` |
| 28 | `C:\Users\misha\AppData\Local\mscodebase\projects\f209de99` | 1000 | `eff9dd45f5ef11c51bf53c17faee3fd775d311c2513f76a4b724ece9cea2a95f` |
| 29 | `C:\Users\misha\AppData\Local\mscodebase\projects\c9a45015` | 974 | `b35ef2df466b1bbba6bde82b62b5a6664e94a4ddaa9044c337d0344cba893ff6` |
| 30 | `C:\Users\misha\AppData\Local\mscodebase\projects\30e461f6` | 830 | `4b41a20ff48a1657c816645fe3c87baae0f7848f1d56e15a94c63f66ce5089c3` |

**Totals:** 30 runs, 48138 bytes, 0 missing.
