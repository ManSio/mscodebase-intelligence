// Тесты edit-gate: логика и проводка хуков, без opencode и без node_modules.
//
// Запуск: node --test .opencode/plugin/edit_gate.test.mjs
//
// Хуки вызываются ровно в той форме, которую плагин получает от хоста
// (`input.sessionID`/`input.tool` + `output.args`), поэтому проверяется реальный
// путь, а не пересказ решения.

import assert from "node:assert/strict"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import { createEditGate, decide, fingerprint, resolveTarget, sameContent } from "./edit_gate.mjs"

let counter = 0

function tmpProject() {
  const dir = mkdtempSync(join(tmpdir(), `edit-gate-${counter++}-`))
  return { dir, cleanup: () => rmSync(dir, { recursive: true, force: true }) }
}

function gate(dir, env = {}) {
  const records = []
  const hooks = createEditGate({
    directory: dir,
    env: { MSCODEBASE_EDIT_GATE: "block", ...env },
    log: (rec) => records.push(rec),
  })
  return { hooks, records }
}

function before(hooks, tool, path, sessionID = "s1") {
  return hooks["tool.execute.before"](
    { tool, sessionID, callID: "c1" },
    { args: path === undefined ? {} : { path } },
  )
}

function after(hooks, tool, path, sessionID = "s1") {
  return hooks["tool.execute.after"](
    { tool, sessionID, callID: "c1", args: { path } },
    { title: "", output: "", metadata: {} },
  )
}

test("new file is allowed without a read", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    const { hooks } = gate(dir)
    await before(hooks, "write", "fresh.txt")
  } finally {
    cleanup()
  }
})

test("editing an existing file that was never read is blocked", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    writeFileSync(join(dir, "a.py"), "x = 1\n")
    const { hooks, records } = gate(dir)
    await assert.rejects(() => before(hooks, "edit", "a.py"), /was not read in this session/)
    assert.equal(records.at(-1).reason, "not-read")
  } finally {
    cleanup()
  }
})

test("read then edit passes", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    writeFileSync(join(dir, "a.py"), "x = 1\n")
    const { hooks } = gate(dir)
    await before(hooks, "read", "a.py")
    await before(hooks, "edit", "a.py")
  } finally {
    cleanup()
  }
})

test("edit after an external change is blocked (stale read)", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    writeFileSync(join(dir, "a.py"), "x = 1\n")
    const { hooks } = gate(dir)
    await before(hooks, "read", "a.py")
    writeFileSync(join(dir, "a.py"), "x = 2\n")
    await assert.rejects(() => before(hooks, "edit", "a.py"), /changed on disk/)
  } finally {
    cleanup()
  }
})

test("two consecutive edits pass: the gate refreshes its own fact", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    writeFileSync(join(dir, "a.py"), "x = 1\n")
    const { hooks } = gate(dir)
    await before(hooks, "read", "a.py")
    await before(hooks, "edit", "a.py")
    writeFileSync(join(dir, "a.py"), "x = 2\n") // what the edit wrote
    await after(hooks, "edit", "a.py")
    await before(hooks, "edit", "a.py")
  } finally {
    cleanup()
  }
})

test("after its own edit an external change is still blocked", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    writeFileSync(join(dir, "a.py"), "x = 1\n")
    const { hooks } = gate(dir)
    await before(hooks, "read", "a.py")
    writeFileSync(join(dir, "a.py"), "x = 2\n")
    await after(hooks, "edit", "a.py")
    writeFileSync(join(dir, "a.py"), "y = 3\n")
    await assert.rejects(() => before(hooks, "edit", "a.py"), /changed on disk/)
  } finally {
    cleanup()
  }
})

test("facts do not leak between sessions", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    writeFileSync(join(dir, "a.py"), "x = 1\n")
    const { hooks } = gate(dir)
    await before(hooks, "read", "a.py", "s1")
    await assert.rejects(() => before(hooks, "edit", "a.py", "s2"), /was not read/)
  } finally {
    cleanup()
  }
})

test("a read of one file does not authorize another", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    writeFileSync(join(dir, "a.py"), "x = 1\n")
    writeFileSync(join(dir, "b.py"), "y = 1\n")
    const { hooks } = gate(dir)
    await before(hooks, "read", "a.py")
    await assert.rejects(() => before(hooks, "edit", "b.py"), /was not read/)
  } finally {
    cleanup()
  }
})

test("relative and absolute paths describe the same file", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    writeFileSync(join(dir, "a.py"), "x = 1\n")
    const { hooks } = gate(dir)
    await before(hooks, "read", "a.py")
    await before(hooks, "edit", join(dir, "a.py"))
  } finally {
    cleanup()
  }
})

test("warn mode records but does not throw", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    writeFileSync(join(dir, "a.py"), "x = 1\n")
    const { hooks, records } = gate(dir, { MSCODEBASE_EDIT_GATE: "warn" })
    await before(hooks, "edit", "a.py")
    assert.equal(records.at(-1).action, "allow")
    assert.equal(records.at(-1).reason, "not-read")
  } finally {
    cleanup()
  }
})

test("off mode never blocks and never records", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    writeFileSync(join(dir, "a.py"), "x = 1\n")
    const { hooks, records } = gate(dir, { MSCODEBASE_EDIT_GATE: "off" })
    await before(hooks, "edit", "a.py")
    assert.deepEqual(records, [])
  } finally {
    cleanup()
  }
})

test("an unknown mode falls back to block", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    writeFileSync(join(dir, "a.py"), "x = 1\n")
    const { hooks } = gate(dir, { MSCODEBASE_EDIT_GATE: "yes-please" })
    await assert.rejects(() => before(hooks, "edit", "a.py"), /was not read/)
  } finally {
    cleanup()
  }
})

test("unknown tools are ignored", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    writeFileSync(join(dir, "a.py"), "x = 1\n")
    const { hooks } = gate(dir)
    await before(hooks, "grep", "a.py")
  } finally {
    cleanup()
  }
})

test("missing path or a directory is not blocked", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    const { hooks } = gate(dir)
    await before(hooks, "edit", "folder/that/does/not/exist.py")
    await before(hooks, "edit", dir)
    await before(hooks, "edit", undefined)
  } finally {
    cleanup()
  }
})

test("large files fall back to size+mtime and still detect a change", async () => {
  const { dir, cleanup } = tmpProject()
  try {
    const big = join(dir, "big.bin")
    writeFileSync(big, "a".repeat(9 * 1024 * 1024))
    const { hooks } = gate(dir)
    await before(hooks, "read", "big.bin")
    await before(hooks, "edit", "big.bin")
    writeFileSync(big, "b".repeat(9 * 1024 * 1024 + 1))
    await assert.rejects(() => before(hooks, "edit", "big.bin"), /changed on disk/)
  } finally {
    cleanup()
  }
})

test("decide() is total: off and new-file allow, stale blocks", () => {
  const fp = { hash: "a", size: 1, mtimeMs: 1 }
  assert.equal(decide({ relPath: "x", exists: true, seen: fp, current: fp, mode: "off" }).action, "allow")
  assert.equal(decide({ relPath: "x", exists: false, seen: null, current: null, mode: "block" }).action, "allow")
  assert.equal(
    decide({ relPath: "x", exists: true, seen: fp, current: { ...fp, hash: "b" }, mode: "block" }).reason,
    "stale-read",
  )
  assert.equal(decide({ relPath: "x", exists: true, seen: null, current: fp, mode: "warn" }).action, "allow")
})

test("resolveTarget() reads the path shapes the host actually sends", () => {
  assert.equal(resolveTarget({ path: "a.py" }, "D:\\p"), join("D:\\p", "a.py"))
  assert.equal(resolveTarget({ filePath: "a.py" }, "/p"), join("/p", "a.py"))
  assert.equal(resolveTarget({}, "/p"), null)
  assert.equal(resolveTarget({ path: "  " }, "/p"), null)
})

test("sameContent() and fingerprint() agree on a real file", () => {
  const { dir, cleanup } = tmpProject()
  try {
    const p = join(dir, "f.txt")
    writeFileSync(p, "hello")
    const a = fingerprint(p)
    const b = fingerprint(p)
    assert.ok(a && b)
    assert.equal(sameContent(a, b), true)
    writeFileSync(p, "hello!")
    assert.equal(sameContent(a, fingerprint(p)), false)
    assert.equal(fingerprint(join(dir, "missing.txt")), null)
  } finally {
    cleanup()
  }
})
