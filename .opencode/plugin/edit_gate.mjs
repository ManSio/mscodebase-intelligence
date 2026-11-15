// edit_gate.mjs — «красное до правки»: файл обязан быть прочитан в этой сессии
// и не измениться на диске после чтения.
//
// AGENTS §11 требует читать перед правкой и перечитывать файл, если он менялся
// (параллельная сессия, генератор, другой процесс). До сих пор это была
// дисциплина. Этот модуль делает правило машинным: `edit`/`write`/`patch` по
// существующему файлу проходит, только если в этой сессии его видели через
// `read`, и содержимое с тех пор то же (sha1; для файлов >8 МБ — size+mtime).
//
// Не блокируется: создание нового файла (читать нечего), инструменты, которых
// нет в EDIT_TOOLS, и пути, которые не удалось разобрать (fail-open на форму
// аргументов, не на содержимое). Правки через `bash` (heredoc, tee, sed -i)
// этот слой не видит — это записанный риск, а не «проверено».
//
// Переключатели: MSCODEBASE_EDIT_GATE=block|warn|off (default block).
// Лог: MSCODEBASE_GATE_LOG — общий с остальными гейтами плагина.
//
// Модуль намеренно без зависимостей и без TS: логика тестируется `node --test`
// там, где нет ни opencode, ни node_modules.

import { createHash } from "node:crypto"
import { readFileSync, realpathSync, statSync } from "node:fs"
import { isAbsolute, join, normalize } from "node:path"

export const MODES = new Set(["block", "warn", "off"])

// Инструменты, которые пишут файл. `patch`/`apply_patch` могут не отдать путь
// в аргументах — тогда гейт молчит (fail-open на форму), см. шапку.
export const EDIT_TOOLS = new Set(["edit", "write", "patch", "apply_patch", "multiedit"])

// Только `read` считается фактом: grep/glob показывают совпадения, но не дают
// содержимого файла, на которое можно опереться при правке.
export const READ_TOOLS = new Set(["read"])

const MAX_HASH_BYTES = 8 * 1024 * 1024
const MAX_FACTS_PER_SESSION = 4096

export function resolveTarget(args, directory) {
  const raw = args?.path ?? args?.filePath ?? args?.file ?? args?.filename
  if (typeof raw !== "string" || raw.trim() === "") return null
  const value = raw.trim()
  return isAbsolute(value) ? normalize(value) : join(directory, value)
}

export function canonicalPath(absPath) {
  try {
    return realpathSync(absPath)
  } catch {
    return normalize(absPath)
  }
}

/** @returns {{hash: string|null, size: number, mtimeMs: number}|null} */
export function fingerprint(absPath) {
  let st
  try {
    st = statSync(absPath)
  } catch {
    return null
  }
  if (!st.isFile()) return null
  if (st.size > MAX_HASH_BYTES) {
    // Не читаем гигантский файл ради гейта: size+mtime достаточно, чтобы
    // заметить правку, и не даёт ложного «тот же файл» после записи.
    return { hash: null, size: st.size, mtimeMs: st.mtimeMs }
  }
  let buf
  try {
    buf = readFileSync(absPath)
  } catch {
    return null
  }
  return { hash: createHash("sha1").update(buf).digest("hex"), size: st.size, mtimeMs: st.mtimeMs }
}

export function sameContent(a, b) {
  if (!a || !b) return false
  if (a.hash && b.hash) return a.hash === b.hash
  return a.size === b.size && a.mtimeMs === b.mtimeMs
}

/**
 * Чистое решение, без файловой системы.
 * @returns {{action: "allow"|"block", reason: string, message?: string}}
 */
export function decide({ relPath, exists, seen, current, mode }) {
  if (mode === "off") return { action: "allow", reason: "off" }
  if (!exists) return { action: "allow", reason: "new-file" }
  if (!seen) {
    return {
      action: mode === "warn" ? "allow" : "block",
      reason: "not-read",
      message:
        `EDIT-GATE: ${relPath} was not read in this session. ` +
        `Read it first (read tool), then edit. ` +
        `(MSCODEBASE_EDIT_GATE=warn disables blocking, =off disables the gate.)`,
    }
  }
  if (!sameContent(seen, current)) {
    return {
      action: mode === "warn" ? "allow" : "block",
      reason: "stale-read",
      message:
        `EDIT-GATE: ${relPath} changed on disk after you read it ` +
        `(another session or a process wrote it). Re-read it before editing.`,
    }
  }
  return { action: "allow", reason: "fresh-read" }
}

export function relativeTo(directory, absPath) {
  const base = normalize(directory)
  const p = normalize(absPath)
  if (p.startsWith(base)) return p.slice(base.length).replace(/^[\\/]+/, "")
  return p
}

/**
 * Хуки плагина: `tool.execute.before` (проверка) и `tool.execute.after`
 * (после успешной правки факт обновляется, иначе вторая правка того же файла
 * блокировалась бы собственной записью).
 */
export function createEditGate({ directory, env = process.env, log = () => {} } = {}) {
  const raw = String(env.MSCODEBASE_EDIT_GATE ?? "block").toLowerCase()
  const mode = MODES.has(raw) ? raw : "block"
  const sessions = new Map()

  function factsFor(sessionID) {
    let facts = sessions.get(sessionID)
    if (!facts) {
      facts = new Map()
      sessions.set(sessionID, facts)
    }
    while (facts.size > MAX_FACTS_PER_SESSION) {
      facts.delete(facts.keys().next().value)
    }
    return facts
  }

  async function before(input, output) {
    const tool = String(input?.tool ?? "")
    const args = output?.args ?? {}
    const target = resolveTarget(args, directory)
    if (!target) return
    const abs = canonicalPath(target)
    const sessionID = String(input?.sessionID ?? "default")

    if (READ_TOOLS.has(tool)) {
      const fp = fingerprint(abs)
      if (fp) factsFor(sessionID).set(abs, fp)
      return
    }
    if (!EDIT_TOOLS.has(tool)) return
    if (mode === "off") return

    const current = fingerprint(abs)
    const decision = decide({
      relPath: relativeTo(directory, abs),
      exists: current !== null,
      seen: factsFor(sessionID).get(abs) ?? null,
      current,
      mode,
    })
    log({ kind: "edit_gate", tool, path: abs, action: decision.action, reason: decision.reason })
    if (decision.action === "block") throw new Error(decision.message)
  }

  async function after(input) {
    const tool = String(input?.tool ?? "")
    if (!EDIT_TOOLS.has(tool)) return
    const target = resolveTarget(input?.args, directory)
    if (!target) return
    const abs = canonicalPath(target)
    const fp = fingerprint(abs)
    if (!fp) return
    factsFor(String(input?.sessionID ?? "default")).set(abs, fp)
  }

  return { "tool.execute.before": before, "tool.execute.after": after }
}
