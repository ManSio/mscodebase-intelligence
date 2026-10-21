# microtask_pipeline — the pipeline as a tool of this repository

A parent agent (OpenCode, cloud) delegates coding work here. This folder owns
the **microtask protocol**: every operation is one microstep with one tool, and
every result is a machine-checked receipt. The parent never edits code and
never re-runs the tests.

```
OpenCode (primary agent, free account model)
   │  one tool call: pipeline_run(task, repo, test_files, source_file)
   ▼
mcp_server.py  (MCP over stdio, stdlib only)
   ▼
engine.py      plan → gate → measure → brief → microstep → apply → verify → receipt
   ▼
Gemma 4 26B A4B (QAT) on our own LM Studio server  ──►  http://192.168.2.5:1234/v1
```

## Files

| file | what |
|---|---|
| `engine.py` | the protocol: microstep kinds, the code layer, the guards, the diff applier, receipts |
| `mcp_server.py` | MCP stdio server; one tool, `pipeline_run` |
| `red_team.py` | 13 attacks against the guards; every one must be **refused** |
| `live_smoke.py` | runs one frozen corpus task end to end against a chosen executor |

## Microstep taxonomy (one tool each)

`locate` (search_files) · `read` (read_file) · `write` (write_file/patch_file) ·
`exec` (run_command) · `output` (read_output) · `decide` / `verify` / `handoff`
(no tool, JSON only). The code layer adds `plan`, `gate`, `measure`, `slice`,
`apply`, `verify`, `receipt` — deterministic, never a model.

## Guarantees (enforced in code, not in the prompt)

* one tool per model turn, at most 2 turns per microstep;
* prompt budget ≤ 2048 tokens (the brief is **shrunk** to fit, never refused);
* answer ≤ 512 tokens — the answer carries a receipt, never a diff;
* one writer per file; test files are read-only and **restored** from the
  pristine copy before verification;
* every write is resolved and must stay inside the repository (symlink escapes
  included);
* the verdict comes from the acceptance command, never from the model's claim;
* receipts are minted by the harness and bind the artifact's sha256.

## Running it

```powershell
# offline self-test (no model, no network): the guards must refuse everything
python tools/microtask_pipeline/red_team.py

# the unit tests (also in the repo suite)
python -m pytest tests/test_microtask_pipeline.py tests/test_microtask_pipeline_red_team.py -q

# one frozen corpus task against our own server
python tools/microtask_pipeline/live_smoke.py --task 17e65663b7_health

# the MCP server speaks stdio; OpenCode starts it from the global config
python tools/microtask_pipeline/mcp_server.py
```

Executors (env `MSC_EXECUTOR`): `lmstudio` (default, our server) · `llama` ·
`tirtha` (metered gateway, mode=low) · `fake` (offline stub, no network).

## Measured limits (do not re-derive, read)

* our server answers **150–300 s per call** — the model is very likely in
  CPU-offload; check `lms ps` and the engine log (`n_gpu_layers`);
* LM Studio's OpenAI-compatible layer does **not** accept `tool_choice` ⇒ the
  model proposes a diff as text and this harness applies it;
* the model reasons in `content`, so a write step needs a second phase
  ("now output ONLY the diff");
* the diff applier is tolerant of the "numbered paste" failure (line-number
  prefixes copied back), and the brief shows raw code for that reason;
* the Tīrtha Base tier cuts answers at **1024** tokens — another reason the
  answer carries only a receipt.

Full protocol and evidence: `experiments/microtask_vs_single/PIPELINE_PROTOCOL.md`.
