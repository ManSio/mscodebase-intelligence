// gate_advisory_override.test.mjs — M4 MSCODEBASE_ADVISORY_TEXT override, advisory mode.
//
// Runs in the DEFAULT process env (isolation=advisory). Drives the REAL exported plugin
// hooks (default export) with a stubbed `python -m src.cli` (MSCODEBASE_PY), so the
// stash/callID flow, the emitted telemetry rows and the appended text are all exercised
// end to end — no test seams in the hook.
//
// Spec mapping:
//   (a) override set + findings>0 → appended text === override; row has override:true + real_len/real_hash
//   (b) override set + findings==0 → NO note appended (quiet stays quiet)
//   (d) override unset → byte-identical to the pre-change code (literal template + exact row keys)
// (c) block mode lives in gate_advisory_override_block.test.mjs (needs ISO_MODE=block at import).
import { describe, it, before } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const md5 = (s) => createHash("md5").update(s ?? "").digest("hex");

// ── must be set BEFORE the plugin module is first imported (module-level consts) ──
process.env.MSCODEBASE_STALE_GATE = "off"; // stale path untouched by this change; keep e2e focused
if (!process.env.MSCODEBASE_PY) process.env.MSCODEBASE_PY = "python";
const ADVISORY_TEXT_SENTINEL = "MSCODEBASE_ADVISORY_TEXT";

const gate = await import("../tools/gate_helpers.ts");
const { default: plugin } = await import("../.opencode/plugin/mscodebase_gate.ts");
const {
  advisoryOverrideText,
  realOutputHash,
  buildAdvisoryNote,
  isolationRowExtra,
  parseIsolation,
} = gate;

// Firing CLI output shape (mirrors the real formatter: counts + deliver marker).
const FIRING =
  "Completed (7ms)\n  \u2022 base:  HEAD\n  \u2022 counts: \n" +
  "  \u2022 removed_last_caller:  1\n  \u2022 new_orphan:  0\n" +
  "  \u2022 findings: \n  - \n    \u2022 kind:  removed_last_caller\n    \u2022 symbol:  orphan_helper\n" +
  "  \u2022 changed files: \n  -  pkg/caller.py\n  \u2022 deliver:  \u2713\n";

const QUIET =
  "Completed (9ms)\n  \u2022 base:  HEAD\n  \u2022 counts: \n" +
  "  \u2022 removed_last_caller:  0\n  \u2022 new_orphan:  0\n" +
  "  \u2022 findings:  []\n  \u2022 changed files: \n  -  KNOWN_ISSUES.md\n";

// Pre-change appended template, copied verbatim from mscodebase_gate.ts BEFORE the
// override change (tool.execute.after). Test (d) pins byte-identical behavior to it.
const preChangeNote = (cached) =>
  `\n\n\u2726 GRAPH-GATE (advisory): this commit isolates graph node(s).\n${cached.slice(0, 500)}`;

const OVERRIDE = "GRAPH-GATE (advisory): this commit isolates `orphan_helper` — fixed voice V1.";

let stubDir;
let seq = 0;

before(() => {
  // Stub `python -m src.cli <tool> <json>`: prints a canned file per tool (path via env).
  stubDir = mkdtempSync(join(tmpdir(), "m4stub-"));
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
  assert.equal(parseIsolation(FIRING).count, 1, "stub CLI precondition: FIRING must parse to count>0");
  assert.equal(parseIsolation(QUIET).count, 0, "stub CLI precondition: QUIET must parse to count 0");
});

function canned(name, text) {
  const p = join(stubDir, `${name}.txt`);
  writeFileSync(p, text, "utf-8");
  return p;
}

function lastIsolationRow(logPath) {
  const lines = readFileSync(logPath, "utf-8").split("\n").filter(Boolean);
  const rows = lines.map((l) => JSON.parse(l)).filter((r) => r.gate === "isolation");
  assert.ok(rows.length > 0, `expected an isolation telemetry row in ${logPath}`);
  return rows[rows.length - 1];
}

async function runFlow({ cliText, override }) {
  const prevOverride = process.env[ADVISORY_TEXT_SENTINEL];
  const prevStub = process.env.MSCODEBASE_STUB_ISOLATION_OUT;
  const prevLog = process.env.MSCODEBASE_GATE_LOG;
  const tag = `t${seq++}`;
  if (override === undefined) delete process.env[ADVISORY_TEXT_SENTINEL];
  else process.env[ADVISORY_TEXT_SENTINEL] = override;
  process.env.MSCODEBASE_STUB_ISOLATION_OUT = canned(`iso-${tag}`, cliText);
  const logPath = join(stubDir, `gate-${tag}.jsonl`);
  process.env.MSCODEBASE_GATE_LOG = logPath;
  try {
    const hooks = await plugin({ directory: stubDir });
    const callID = `call-${tag}`;
    await hooks["tool.execute.before"](
      { tool: "bash", callID },
      { args: { command: "git commit -m test" } },
    );
    const outObj = { output: "BASE-OUTPUT" };
    await hooks["tool.execute.after"]({ callID }, outObj);
    return { outText: outObj.output, row: lastIsolationRow(logPath) };
  } finally {
    if (prevOverride === undefined) delete process.env[ADVISORY_TEXT_SENTINEL];
    else process.env[ADVISORY_TEXT_SENTINEL] = prevOverride;
    if (prevStub === undefined) delete process.env.MSCODEBASE_STUB_ISOLATION_OUT;
    else process.env.MSCODEBASE_STUB_ISOLATION_OUT = prevStub;
    if (prevLog === undefined) delete process.env.MSCODEBASE_GATE_LOG;
    else process.env.MSCODEBASE_GATE_LOG = prevLog;
  }
}

describe("MSCODEBASE_ADVISORY_TEXT pure helpers", () => {
  it("advisoryOverrideText: unset/empty → '' (default-off)", () => {
    const prev = process.env[ADVISORY_TEXT_SENTINEL];
    try {
      delete process.env[ADVISORY_TEXT_SENTINEL];
      assert.equal(advisoryOverrideText(), "");
      process.env[ADVISORY_TEXT_SENTINEL] = "";
      assert.equal(advisoryOverrideText(), "");
      process.env[ADVISORY_TEXT_SENTINEL] = OVERRIDE;
      assert.equal(advisoryOverrideText(), OVERRIDE);
    } finally {
      if (prev === undefined) delete process.env[ADVISORY_TEXT_SENTINEL];
      else process.env[ADVISORY_TEXT_SENTINEL] = prev;
    }
  });

  it("realOutputHash is md5 of the raw output", () => {
    assert.equal(realOutputHash(FIRING), md5(FIRING));
  });

  it("isolationRowExtra: {} when override off or inapplicable; override:true + length/hash when armed", () => {
    const prev = process.env[ADVISORY_TEXT_SENTINEL];
    try {
      delete process.env[ADVISORY_TEXT_SENTINEL];
      assert.deepEqual(isolationRowExtra(FIRING, parseIsolation(FIRING), "advisory"), {});
      process.env[ADVISORY_TEXT_SENTINEL] = OVERRIDE;
      assert.deepEqual(isolationRowExtra(FIRING, parseIsolation(FIRING), "advisory"), {
        override: true,
        real_len: FIRING.length,
        real_hash: md5(FIRING),
      });
      assert.deepEqual(isolationRowExtra(FIRING, parseIsolation(FIRING), "block"), {});
      assert.deepEqual(isolationRowExtra(QUIET, parseIsolation(QUIET), "advisory"), {});
    } finally {
      if (prev === undefined) delete process.env[ADVISORY_TEXT_SENTINEL];
      else process.env[ADVISORY_TEXT_SENTINEL] = prev;
    }
  });
});

describe("(a) override set + findings>0 → appended text === override, row carries override:true + real length", () => {
  it("end to end through the real hooks", async () => {
    const { outText, row } = await runFlow({ cliText: FIRING, override: OVERRIDE });
    assert.equal(outText, "BASE-OUTPUT" + OVERRIDE);
    assert.equal(row.reason, "fired_advisory");
    assert.equal(row.delivered, true);
    assert.equal(row.override, true);
    assert.equal(row.real_len, FIRING.length);
    assert.equal(row.real_hash, md5(FIRING));
  });

  it("pure: buildAdvisoryNote substitutes verbatim", () => {
    const prev = process.env[ADVISORY_TEXT_SENTINEL];
    try {
      process.env[ADVISORY_TEXT_SENTINEL] = OVERRIDE;
      const note = buildAdvisoryNote(FIRING, "advisory");
      assert.equal(note.text, OVERRIDE);
      assert.equal(note.override, true);
      assert.equal(note.realLen, FIRING.length);
      assert.equal(note.realHash, md5(FIRING));
    } finally {
      if (prev === undefined) delete process.env[ADVISORY_TEXT_SENTINEL];
      else process.env[ADVISORY_TEXT_SENTINEL] = prev;
    }
  });
});

describe("(b) override set + findings==0 → NO note appended", () => {
  it("end to end: quiet gate stays quiet, row has no override keys", async () => {
    const { outText, row } = await runFlow({ cliText: QUIET, override: OVERRIDE });
    assert.equal(outText, "BASE-OUTPUT");
    assert.equal(row.reason, "suppressed_zero_findings");
    assert.ok(!("override" in row), "quiet row must not carry override flag");
    assert.ok(!("real_len" in row), "quiet row must not carry real_len");
    assert.ok(!("real_hash" in row), "quiet row must not carry real_hash");
  });

  it("pure: buildAdvisoryNote returns null on zero findings even with override set", () => {
    const prev = process.env[ADVISORY_TEXT_SENTINEL];
    try {
      process.env[ADVISORY_TEXT_SENTINEL] = OVERRIDE;
      assert.equal(buildAdvisoryNote(QUIET, "advisory"), null);
    } finally {
      if (prev === undefined) delete process.env[ADVISORY_TEXT_SENTINEL];
      else process.env[ADVISORY_TEXT_SENTINEL] = prev;
    }
  });
});

describe("(d) override unset → byte-identical to pre-change behavior", () => {
  it("end to end: appended text equals the pre-change template", async () => {
    const { outText, row } = await runFlow({ cliText: FIRING, override: undefined });
    assert.equal(outText, "BASE-OUTPUT" + preChangeNote(FIRING));
  });

  it("end to end: telemetry row key shape is exactly the pre-change shape", async () => {
    const { row } = await runFlow({ cliText: FIRING, override: undefined });
    assert.deepEqual(Object.keys(row), ["t", "gate", "mode", "act", "count", "delivered", "reason", "latency_ms"]);
  });

  it("pure: default note equals the pre-change template, override=false", () => {
    const prev = process.env[ADVISORY_TEXT_SENTINEL];
    try {
      delete process.env[ADVISORY_TEXT_SENTINEL];
      const note = buildAdvisoryNote(FIRING, "advisory");
      assert.equal(note.text, preChangeNote(FIRING));
      assert.equal(note.override, false);
    } finally {
      if (prev === undefined) delete process.env[ADVISORY_TEXT_SENTINEL];
      else process.env[ADVISORY_TEXT_SENTINEL] = prev;
    }
  });
});
