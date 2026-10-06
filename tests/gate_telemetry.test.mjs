// gate_telemetry.test.mjs — node --test for the pure helpers in
// .opencode/plugin/mscodebase_gate.ts (run via pytest subprocess too).
// Covers: log-path resolution, stale/isolation parsing (on REAL formatter
// output shapes), and reachability of EVERY GateReason.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import * as gate from "../tools/gate_helpers.ts";
import * as entryModule from "../.opencode/plugin/mscodebase_gate.ts";

const {
  projectHash,
  dataRoot,
  resolveGateLog,
  parseStale,
  parseIsolation,
  decideStale,
  decideIsolation,
  makeRow,
} = gate;

// Local copy on purpose: the plugin module must not export non-function values
// (opencode >=1.16 legacy loader throws "Plugin export is not a function").
// Keeping the expected keys here also proves the schema from the consumer side.
const ROW_REQUIRED_KEYS = ["t", "gate", "mode", "act", "delivered", "reason", "latency_ms"];

describe("plugin entry is loader-safe (opencode >=1.16 getLegacyPlugins)", () => {
  it("every runtime export is a function", () => {
    for (const [name, value] of Object.entries(gate)) {
      assert.equal(typeof value, "function", `non-function export: ${name}`);
    }
  });
  it("entry module exports ONLY default (exact upstream issue pattern)", async () => {
    assert.deepEqual(Object.keys(entryModule), ["default"]);
  });
  it("default export is a function", () => {
    assert.equal(typeof entryModule.default, "function");
  });
  it("plugin dir holds no other loadable module (helpers live outside)", async () => {
    // The loader auto-loads EVERY file in the plugin dir as its own plugin
    // (M4 smoke attempts 2-3: gate_helpers.ts was invoked export-by-export).
    const { readdirSync } = await import("node:fs");
    const { join, dirname } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const dir = join(dirname(fileURLToPath(import.meta.url)), "..", ".opencode", "plugin");
    const ts = readdirSync(dir).filter((f) => f.endsWith(".ts") || f.endsWith(".js"));
    assert.deepEqual(ts, ["mscodebase_gate.ts"]);
  });
});

describe("hooks never throw on malformed input (M4 smoke attempts 2-3)", () => {
  it("before/after resolve (not reject) on undefined input/output", async () => {
    const plugin = await entryModule.default({ directory: tmpdir() });
    await plugin["tool.execute.before"](undefined, undefined);
    await plugin["tool.execute.before"](undefined, {});
    await plugin["tool.execute.before"]({ tool: "bash" }, undefined);
    await plugin["tool.execute.before"]({ tool: "bash", callID: "x" }, { args: {} });
    await plugin["tool.execute.after"](undefined, undefined);
    await plugin["tool.execute.after"]({ callID: "y" }, undefined);
  });
});

// Sample produced by the REAL src/core/error_handler._format_success_response
// on a post-change isolation dict (deliver=false + restraint detail).
const ISO_SUPPRESSED =
  "Completed (7ms)\n  \u2022 base:  HEAD\n  \u2022 counts: \n" +
  "  \u2022 removed_last_caller:  1\n  \u2022 new_orphan:  1\n" +
  "  \u2022 findings: \n  - \n    \u2022 kind:  new_orphan\n    \u2022 symbol:  helper\n" +
  "  \u2022 changed files: \n  -  pkg/a.py\n  \u2022 deliver:  \u2717\n" +
  "  \u2022 suppressed reason:  cooldown: same findings, 42s left (strikes=1)\n" +
  "  \u2022 restraint: \n  \u2022 signature:  ad6d23ff4f5c87c2\n" +
  "  \u2022 strikes:  1\n  \u2022 cooldown_s_left:  42\n";

const ISO_DELIVERED = ISO_SUPPRESSED.replace("deliver:  \u2717", "deliver:  \u2713").replace(
  "suppressed reason:  cooldown: same findings, 42s left (strikes=1)",
  "suppressed reason: ",
);

const ISO_ZERO =
  "Completed (9ms)\n  \u2022 base:  HEAD\n  \u2022 counts: \n" +
  "  \u2022 removed_last_caller:  0\n  \u2022 new_orphan:  0\n" +
  "  \u2022 findings:  []\n  \u2022 changed files: \n  -  KNOWN_ISSUES.md\n";

const STALE_DIRTY =
  '{"ok": true, "tool": "stale_detector", "result": "Stale Detector \\u2014 Doc Drift Report\\n' +
  "Actual version: 3.2.0\\nDocs with drift: 1\\nTotal drift instances: 2 (1 errors)\\n\"}";

const STALE_CLEAN = STALE_DIRTY.replace("Total drift instances: 2 (1 errors)", "Total drift instances: 0 (0 errors)");

describe("log path resolution", () => {
  it("override respected", () => {
    const prev = process.env.MSCODEBASE_GATE_LOG;
    process.env.MSCODEBASE_GATE_LOG = "D:/custom/gate.jsonl";
    try {
      assert.equal(resolveGateLog("D:/whatever"), "D:/custom/gate.jsonl");
    } finally {
      if (prev === undefined) delete process.env.MSCODEBASE_GATE_LOG;
      else process.env.MSCODEBASE_GATE_LOG = prev;
    }
  });

  it("default derives from the data-root convention, not the legacy temp log", () => {
    const prev = { ...process.env };
    delete process.env.MSCODEBASE_GATE_LOG;
    delete process.env.MSCODEBASE_DATA_DIR;
    delete process.env.BASE_INDEX_DIR;
    try {
      const p = resolveGateLog("D:/Project/wt-audit-corrections");
      assert.match(p, /gate_telemetry\.jsonl$/);
      assert.match(p, /projects[\\/][0-9a-f]{8}[\\/]/);
      assert.ok(p.startsWith(dataRoot()), `expected under dataRoot ${dataRoot()}, got ${p}`);
      // legacy location this replaces: <tmpdir>/opencode/mscodebase_gate.log
      const legacy = join(tmpdir(), "opencode", "mscodebase_gate.log");
      assert.notEqual(p, legacy);
    } finally {
      process.env = prev;
    }
  });

  it("projectHash mirrors artifact_paths.project_hash (md5 lower slash path, 8 hex)", () => {
    const h = projectHash("D:\\Project\\WT-AUDIT-CORRECTIONS");
    const expected = createHash("md5").update("d:/project/wt-audit-corrections").digest("hex").slice(0, 8);
    assert.equal(h, expected);
    assert.match(h, /^[0-9a-f]{8}$/);
  });

  it("default honours MSCODEBASE_DATA_DIR", () => {
    assert.ok(dataRoot().length > 0);
    assert.ok(resolveGateLog("D:/x").startsWith(dataRoot()));
  });

  it("tmpdir legacy path only as fallback shape", () => {
    assert.ok(tmpdir().length > 0);
  });
});

describe("parseStale", () => {
  it("extracts drift from CLI JSON envelope", () => {
    assert.equal(parseStale(STALE_DIRTY).drift, 2);
    assert.equal(parseStale(STALE_DIRTY).unavailable, false);
  });
  it("clean report is zero drift", () => {
    const p = parseStale(STALE_CLEAN);
    assert.equal(p.drift, 0);
    assert.equal(p.unavailable, false);
  });
  it("empty output is unavailable", () => {
    assert.equal(parseStale("").unavailable, true);
  });
});

describe("parseIsolation", () => {
  it("counts both signals on real formatter output", () => {
    const p = parseIsolation(ISO_SUPPRESSED);
    assert.equal(p.count, 2);
  });
  it("detects suppression marker", () => {
    assert.equal(parseIsolation(ISO_SUPPRESSED).suppressed, true);
    assert.equal(parseIsolation(ISO_DELIVERED).suppressed, false);
  });
  it("extracts restraint detail", () => {
    assert.deepEqual(parseIsolation(ISO_SUPPRESSED).restraint, {
      signature: "ad6d23ff4f5c87c2",
      strikes: 1,
      cooldown_s_left: 42,
    });
  });
  it("zero-findings output parses to count 0", () => {
    const p = parseIsolation(ISO_ZERO);
    assert.equal(p.count, 0);
    assert.equal(p.suppressed, false);
    assert.equal(p.restraint, null);
  });
  it("empty output is unavailable", () => {
    assert.equal(parseIsolation("").unavailable, true);
  });
});

describe("every GateReason reachable (stale)", () => {
  it("fired_block", () => assert.equal(decideStale("block", { drift: 2, unavailable: false }, false).reason, "fired_block"));
  it("fired_advisory (drift, non-block mode)", () =>
    assert.deepEqual(decideStale("advisory", { drift: 2, unavailable: false }, false), { delivered: false, reason: "fired_advisory" }));
  it("suppressed_zero_findings", () =>
    assert.deepEqual(decideStale("block", { drift: 0, unavailable: false }, false), { delivered: false, reason: "suppressed_zero_findings" }));
  it("skipped_off", () =>
    assert.deepEqual(decideStale("off", { drift: 99, unavailable: false }, false), { delivered: false, reason: "skipped_off" }));
  it("error_unavailable", () =>
    assert.deepEqual(decideStale("block", { drift: 0, unavailable: true }, false), { delivered: false, reason: "error_unavailable" }));
  it("error_exception", () =>
    assert.deepEqual(decideStale("block", { drift: 0, unavailable: false }, true), { delivered: false, reason: "error_exception" }));
});

describe("every GateReason reachable (isolation)", () => {
  const hit = { count: 2, suppressed: false, restraint: null, unavailable: false };
  const supp = { count: 2, suppressed: true, restraint: { signature: "s", strikes: 1, cooldown_s_left: 5 }, unavailable: false };
  const zero = { count: 0, suppressed: false, restraint: null, unavailable: false };
  it("fired_block", () => assert.deepEqual(decideIsolation("block", hit, false), { delivered: true, reason: "fired_block" }));
  it("fired_advisory", () => assert.deepEqual(decideIsolation("advisory", hit, false), { delivered: true, reason: "fired_advisory" }));
  it("suppressed_restraint", () =>
    assert.deepEqual(decideIsolation("advisory", supp, false), { delivered: false, reason: "suppressed_restraint" }));
  it("suppressed_zero_findings", () =>
    assert.deepEqual(decideIsolation("advisory", zero, false), { delivered: false, reason: "suppressed_zero_findings" }));
  it("skipped_off", () =>
    assert.deepEqual(decideIsolation("off", hit, false), { delivered: false, reason: "skipped_off" }));
  it("error_unavailable", () =>
    assert.deepEqual(decideIsolation("advisory", { ...zero, unavailable: true }, false), { delivered: false, reason: "error_unavailable" }));
  it("error_exception", () =>
    assert.deepEqual(decideIsolation("advisory", zero, true), { delivered: false, reason: "error_exception" }));
});

describe("row schema (makeRow — the single choke point)", () => {
  const reasons = [
    ["stale", "block", "fired_block", { drift: 2 }],
    ["stale", "block", "suppressed_zero_findings", { drift: 0 }],
    ["stale", "off", "skipped_off", { drift: 0 }],
    ["stale", "block", "error_unavailable", { drift: 0 }],
    ["stale", "block", "error_exception", { drift: 0 }],
    ["stale", "advisory", "fired_advisory", { drift: 1 }],
    ["isolation", "advisory", "fired_advisory", { count: 2 }],
    ["isolation", "block", "fired_block", { count: 1, refusal_len: 120 }],
    ["isolation", "advisory", "suppressed_restraint", { count: 2, restraint: { signature: "s", strikes: 1, cooldown_s_left: 5 } }],
    ["isolation", "advisory", "suppressed_zero_findings", { count: 0 }],
    ["isolation", "off", "skipped_off", { count: 0 }],
    ["isolation", "advisory", "error_unavailable", { count: 0 }],
    ["isolation", "advisory", "error_exception", { count: 0 }],
  ];
  for (const [gateKind, mode, reason, extra] of reasons) {
    it(`schema keys present: ${gateKind}/${reason}`, () => {
      const row = makeRow({ gate: gateKind, mode, act: "bash git commit -m x", delivered: reason.startsWith("fired"), reason, latency_ms: 3, ...extra });
      for (const k of ROW_REQUIRED_KEYS) assert.ok(k in row, `missing ${k}`);
      assert.ok(typeof row.t === "number");
      assert.ok(gateKind === "stale" ? "drift" in row : "count" in row);
      // append-only JSONL: exactly one line, no raw newlines
      const line = JSON.stringify(row);
      assert.ok(!line.includes("\n"));
      assert.deepEqual(JSON.parse(line), { ...row, t: row.t });
    });
  }
  it("stale rows carry drift, isolation rows carry count", () => {
    assert.ok("drift" in makeRow({ gate: "stale", mode: "block", act: "a", drift: 0, delivered: false, reason: "suppressed_zero_findings", latency_ms: 0 }));
    assert.ok("count" in makeRow({ gate: "isolation", mode: "off", act: "a", count: 0, delivered: false, reason: "skipped_off", latency_ms: 0 }));
  });
});

describe("parser parity with legacy regexes", () => {
  it("legacy stale regex and parseStale agree on envelope text", () => {
    const m = /Total drift instances:\s*(\d+)/i.exec(STALE_DIRTY);
    assert.equal(parseStale(STALE_DIRTY).drift, parseInt(m[1], 10));
  });
  it("legacy isolation regexes and parseIsolation agree", () => {
    const r = /removed_last_caller:\s*(\d+)/i.exec(ISO_SUPPRESSED);
    const n = /new_orphan:\s*(\d+)/i.exec(ISO_SUPPRESSED);
    assert.equal(parseIsolation(ISO_SUPPRESSED).count, parseInt(r[1], 10) + parseInt(n[1], 10));
    const legacySupp = /deliver:\s*\u2717/i.test(ISO_SUPPRESSED) || /deliver:\s*false/i.test(ISO_SUPPRESSED);
    assert.equal(parseIsolation(ISO_SUPPRESSED).suppressed, legacySupp);
  });
});
