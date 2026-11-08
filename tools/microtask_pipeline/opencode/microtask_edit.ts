/**
 * microtask_edit — the pipeline as an OpenCode tool.
 *
 * The parent agent calls this exactly as it would call the built-in `edit`
 * tool; the work itself is done by the microtask pipeline (a bounded brief, a
 * one-shot local model, a code verifier and a receipt). The agent gets an
 * ordinary tool result back and continues as if the edit had been made.
 *
 * To shadow the built-in tool, put this file in ~/.config/opencode/tools/ as
 * `edit.ts` — "If a custom tool uses the same name as a built-in tool, the
 * custom tool takes precedence" (OpenCode docs, Custom Tools).
 *
 * The engine is Python and stays the single implementation; this file is a
 * thin adapter (the docs explicitly allow a tool to invoke a script written in
 * any language).
 */
import { tool } from "@opencode-ai/plugin"
import { $ } from "bun"
import path from "path"

const ENGINE = process.env.MSC_ENGINE ?? "D:/Project/MSCodeBase/tools/microtask_pipeline/run_step.py"

export default tool({
  description:
    "Edit one file. The change is executed by the microtask pipeline: a bounded brief is " +
    "given to a local model, the diff is applied and verified by the acceptance command, " +
    "and the result is a receipt (command, exit code, artifact hash).",
  args: {
    filePath: tool.schema.string().describe("absolute path of the file to edit"),
    oldString: tool.schema.string().describe("text to replace"),
    newString: tool.schema.string().describe("replacement text"),
    acceptance: tool.schema
      .string()
      .optional()
      .describe("command that must pass after the edit, e.g. python -m pytest tests/test_x.py -q"),
    goal: tool.schema.string().optional().describe("what the change must achieve"),
  },
  async execute(args, context) {
    const payload = JSON.stringify({
      tool: "edit",
      args,
      directory: context.directory,
      worktree: context.worktree,
      agent: context.agent,
    })
    const script = path.join(path.dirname(ENGINE), "run_step.py")
    const result = await $`python ${script} ${payload}`.text()
    return result.trim()
  },
})
