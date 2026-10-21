# Integration: making the pipeline a built-in mechanism, not a script

Own synthesis. Sources: OpenCode docs (plugins, custom tools — both last
updated 2026-10-20) and aider's architect/editor work (2024-09-26, docs).

## 0. The complaint this answers

Right now the pipeline is **a tool the agent must be told to call** — an MCP
server plus a rule in `AGENTS.md`. That is a script with manners. A built-in
mechanism has two properties:

1. the parent agent's behaviour does not change — it calls the tools it always
   calls;
2. the *system* performs the decomposition, the bounded execution and the
   verification, and returns an ordinary tool result.

OpenCode gives both, natively:

| native point | what it buys | source |
|---|---|---|
| **custom tools** in `.opencode/tools/` or `~/.config/opencode/tools/`, written in TS/JS but **may invoke scripts in any language** | the pipeline engine stays Python (one implementation) while OpenCode sees a normal tool | OpenCode docs, "Custom Tools" |
| **"If a custom tool uses the same name as a built-in tool, the custom tool takes precedence"** (their own example: a `shell.ts` file *replaces* the built-in `shell` tool) | we can shadow `edit`/`write`/`bash`: the parent calls the same names, the pipeline serves them | OpenCode docs, "Custom Tools" |
| **`tool.execute.before` / `tool.execute.after`** hooks, plus `permission.asked`, `file.edited`, `session.*`, `experimental.session.compacting` | interception instead of replacement; the docs' own compaction example is written for a "multi-agent swarm session" | OpenCode docs, "Plugins" |
| **load order**: global config → project config → **global plugin dir** → project plugin dir | one global plugin makes the mechanism work in **every** project | OpenCode docs, "Plugins" |

## 1. The pattern is established, not invented

Aider's **architect/editor** split is the same contract with a different vendor:
"an **architect model** will propose changes and an **editor model** will
translate that proposal into specific file edits"; the editor emits `diff`/`whole`
edits — the same unified-diff contract our engine applies. Their measured
result: **o1-preview architect + o1-mini editor = 85 %** on their benchmark
against **79.7 %** for the same model solo. Their stated reason is *exactly* our
measured failure mode: "certain LLMs aren't able to propose coding solutions and
specify detailed file edits all in one go" — Gemma 4 on our server "reasons
instead of acting", and the split fixes it by giving the model one job.

Our roles map one to one:

| role | aider | here | who |
|---|---|---|---|
| plan | architect (strong, reasons) | planner | cloud OpenCode (free account model) |
| execute | editor (formats the edit) | micro-agent | Gemma 4 26B A4B on our server |
| verify | aider's `--auto-test` | code acceptance + receipt | pytest + harness |

## 2. Two integration shapes

### A. Shadow the built-in tools (the "system" shape)

```
.opencode/tools/edit.ts        →  our implementation of "edit"
.opencode/tools/write.ts       →  our implementation of "write"
.opencode/tools/bash.ts        →  our implementation of "bash" (restricted)
```

Each one: takes the tool's normal arguments, turns them into a **Brief**
(file + goal + acceptance), runs the microstep on the local model, applies the
diff, runs the acceptance command, and returns an ordinary tool result:

```
edited src/core/run_bounded.py (+2/-1) · acceptance: pytest tests/test_run_bounded.py -q → exit 0 · receipt r-a0c6cba9
```

The parent agent does not know the difference. Its next turn sees a normal tool
result and continues. **No prompt rule, no new tool to learn.**

### B. Intercept with a plugin (the reversible shape)

```
.opencode/plugins/microtask_kernel.ts
    "tool.execute.before": if (input.tool is edit/write/bash) → route into the pipeline
```

Same effect, but the built-in tools stay intact and the kernel can be switched
off with one env var. It also has a hook the tool layer lacks:
`experimental.session.compacting` — we can inject "what each agent changed and
what is still open" into the compaction prompt, which is precisely what a swarm
needs when the parent session is compacted.

## 3. What is still open (and why we do not flip it on yet)

Shadowing the built-in tools makes **every** edit go through the pipeline,
including the small ones. Our own measured numbers say that is not yet a good
trade:

* the pipeline's success rate is **not** established: 1 of 2 live audits passed,
  and the first failure was our own bug (the slice cut the function body);
* the executor is slow on our server (~115 s per call) — a parent agent's
  20-call session would spend 40 minutes inside the kernel;
* if the pipeline fails, the parent has **no** fallback (it is not allowed to
  edit) — so the failure mode is "the agent is stuck", not "the agent is slow".

So the order is: (1) the explicit tool (now), (2) the plugin interception in
*observe-only* mode — every intercepted call is served by the pipeline **and**
recorded, but the parent's own execution still happens, so we can compare the two
on real work, (3) shadowing, once the comparison says the pipeline is at least
as good.

That third step is the "built-in system" the owner asked for, and it is one
flag away, not a rewrite.

## 4. Install (already done for the explicit path)

```jsonc
// ~/.config/opencode/opencode.jsonc
"mcp": {
  "pipeline": { "type": "local", "command": ["python", "<repo>/tools/microtask_pipeline/mcp_server.py"], "enabled": true }
},
"agent": {
  "pipeline-orchestrator": { "mode": "primary", "steps": 24, "permission": { "edit": "deny", "shell": "deny", "task": "deny" } }
}
```

For the built-in shape (step 2–3): drop the files into
`~/.config/opencode/tools/` (global ⇒ every project) and enable with
`MSC_MICROKERNEL=1`.

## 5. Measured facts this design rests on

| fact | measurement |
|---|---|
| a strong model cannot be asked to plan *and* edit in one turn | aider: 85 % split vs 79.7 % solo; our audit: Gemma 4 "reasons instead of acting" |
| the answer must not carry the artifact | Tīrtha Base cuts answers at 1024 tokens (10 of 998); our diff-in-the-answer prompt cost 5.33 M tokens on one task (13× the receipt contract) |
| the parent must not re-verify | the receipt (cmd + exit + sha256) is the observation; our audit ended with a machine verdict, not a claim |
| the brief must contain the right slice | the audit's first failure: the model said "I don't have the actual content" — the slice cut the function at a multi-line signature; the slice now comes from the AST |
