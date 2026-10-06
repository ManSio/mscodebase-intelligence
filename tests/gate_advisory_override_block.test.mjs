// gate_advisory_override_block.test.mjs — (c) override set + block mode → override ignored.
//
// MUST run with MSCODEBASE_ISOLATION_GATE=block (ISO_MODE is a module-level const):
//   MSCODEBASE_ISOLATION_GATE=block node --test tests/gate_advisory_override_block.test.mjs
// Drives the REAL exported plugin hooks with a stubbed `python -m src.cli`.
import { describe, it, before } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

process.env.MSCODEBASE_STALE_GATE = "off"; // stale path untouched; keep e2e focused
if (!process.env.MSCODEBASE_PY) process.env.MSCODEBASE_PY = "python";

const gate = await import("../tools/gate_helpers.ts");
const { default: plugin } = await import("../.opencode/plugin/mscodebase_gate.ts");
const { buildAdvisoryNote, isolationRowExtra, parseIsolation } = gate;

const FIRING =
  "Completed (7ms)\n  \u2022 base:  HEAD\n  \u2022 counts: \n" +
  "  \u2022 removed_last_caller:  1\n  \u2022 new_orphan:  0\n" +
  "  \u2022 findings: \n  - \n    \u2022 kind:  removed_last_caller\n    \u2022 symbol:  orphan_helper\n" +
  "  \u2022 changed files: \n  -  pkg/caller.py\n  \u2022 deliver:  \u2713\n";

const OVERRIDE = "GRAPH-GATE (advisory): this commit isolates `orphan_helper` — fixed voice V1.";

let stubDir;

before(() => {
  stubDir = mkdtempSync(join(tmpdir(), "m4stub-block-"));
  mkdirSync(join(stubDir, "src"), { recursive: true });
  writeFileSync(
    join(stubDir, "src", "cli.py"),
    "import os, sys\n" +
      "def main():\n" +
      "    tool = sys.argv[1] if len(sys.argv) > 1 else ''\n" +
      "    key = 'MSCODEBASE_STUB_ISOLATION_OUT' if tool == 'graph_query' else 'MSCODEBASE_STUB_STALE_OUT'\n" +
      "    p = os.environ.get(key, '')\n" +
      "    if p:\n" +
      "        with open(p, 'r', encoding='utf-8') as f:\n" +
      "            data = f.read()\n" +
      "        sys.stdout.buffer.write(data.encode('utf-8'))\n" +
      "        sys.stdout.buffer.flush()\n" +
      "main()\n",
    "utf-8",
  );
});

describe("(c) override set + block mode → block text unchanged, override ignored", () => {
  it("refuses to run unless ISO_MODE is block", () => {
    assert.equal(
      process.env.MSCODEBASE_ISOLATION_GATE,
      "block",
      "this file must run with MSCODEBASE_ISOLATION_GATE=block",
    );
  });

  it("end to end: block throw carries the REAL gate output, never the override", async () => {
    const prevOverride = process.env.MSCODEBASE_ADVISORY_TEXT;
    const prevStub = process.env.MSCODEBASE_STUB_ISOLATION_OUT;
    const prevLog = process.env.MSCODEBASE_GATE_LOG;
    const stubOut = join(stubDir, "iso.txt");
    writeFileSync(stubOut, FIRING, "utf-8");
    const logPath = join(stubDir, "gate.jsonl");
    process.env.MSCODEBASE_ADVISORY_TEXT = OVERRIDE;
    process.env.MSCODEBASE_STUB_ISOLATION_OUT = stubOut;
    process.env.MSCODEBASE_GATE_LOG = logPath;
    try {
      const hooks = await plugin({ directory: stubDir });
      const callID = "call-block-1";
      await assert.rejects(
        hooks["tool.execute.before"](
          { tool: "bash", callID },
          { args: { command: "git commit -m test" } },
        ),
        (e) => {
          assert.match(String(e), /GRAPH-GATE/);
          assert.ok(String(e).includes(FIRING.slice(0, 500)), "block text must carry the real gate output");
          assert.ok(!String(e).includes(OVERRIDE), "block text must NOT contain the override");
          return true;
        },
      );
      // after-hook is a no-op in block mode (and nothing was stashed): output untouched.
      const outObj = { output: "BASE-OUTPUT" };
      await hooks["tool.execute.after"]({ callID }, outObj);
      assert.equal(outObj.output, "BASE-OUTPUT");
      // telemetry block row: fired_block, no override keys.
      const rows = readFileSync(logPath, "utf-8")
        .split("\n")
        .filter(Boolean)
        .map((l) => JSON.parse(l))
        .filter((r) => r.gate === "isolation");
      assert.ok(rows.length > 0);
      const row = rows[rows.length - 1];
      assert.equal(row.reason, "fired_block");
      assert.equal(row.delivered, true);
      assert.ok(!("override" in row), "block row must not carry override flag");
      assert.ok(!("real_len" in row), "block row must not carry real_len");
      assert.ok(!("real_hash" in row), "block row must not carry real_hash");
    } finally {
      if (prevOverride === undefined) delete process.env.MSCODEBASE_ADVISORY_TEXT;
      else process.env.MSCODEBASE_ADVISORY_TEXT = prevOverride;
      if (prevStub === undefined) delete process.env.MSCODEBASE_STUB_ISOLATION_OUT;
      else process.env.MSCODEBASE_STUB_ISOLATION_OUT = prevStub;
      if (prevLog === undefined) delete process.env.MSCODEBASE_GATE_LOG;
      else process.env.MSCODEBASE_GATE_LOG = prevLog;
    }
  });

  it("pure: block mode never builds a note and never adds row keys", () => {
    const prev = process.env.MSCODEBASE_ADVISORY_TEXT;
    try {
      process.env.MSCODEBASE_ADVISORY_TEXT = OVERRIDE;
      assert.equal(buildAdvisoryNote(FIRING, "block"), null);
      assert.deepEqual(isolationRowExtra(FIRING, parseIsolation(FIRING), "block"), {});
    } finally {
      if (prev === undefined) delete process.env.MSCODEBASE_ADVISORY_TEXT;
      else process.env.MSCODEBASE_ADVISORY_TEXT = prev;
    }
  });
});
