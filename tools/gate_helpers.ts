// gate_helpers.ts — чистые хелперы гейтов MSCodeBase (без default-экспорта).
//
// Этот модуль содержит ВСЁ из mscodebase_gate.ts КРОМЕ default-фабрики:
// импорты, константы, типы/интерфейсы и все функции решения/разбора.
// Поведение побайтово идентично исходнику — это ПЕРЕНОС, а не переписывание.
//
// Причина выноса: opencode ≥1.16 legacy plugin loader итерирует
// Object.values(module) и ВЫЗЫВАЕТ каждый function-экспорт как фабрику плагина.
// Поэтому входной модуль (.opencode/plugin/mscodebase_gate.ts) обязан
// экспортировать ТОЛЬКО default-фабрику; все хелперы живут здесь.
// См. opencode issues #41234/#31575/#42451.

import { appendFileSync, mkdirSync } from "node:fs"
import { execFile } from "node:child_process"
import { createHash } from "node:crypto"
import { dirname, isAbsolute, join, resolve } from "node:path"
import { homedir, tmpdir } from "node:os"

// Project-local venv by default; MSCODEBASE_PY overrides. No machine-specific path.
// Non-exported on purpose: gate_helpers.ts must export ONLY functions (see the
// "every runtime export is a function" test). The live copies used by the factory
// live in mscodebase_gate.ts (identical lines); these copies preserve the original
// module text verbatim (MOVE, not rewrite).
const STALE_MODE = process.env.MSCODEBASE_STALE_GATE ?? "block"
const ISO_MODE = process.env.MSCODEBASE_ISOLATION_GATE ?? "advisory"

const STALE_ARGS = "{}"
const ISO_ARGS = '{"action":"isolation","kwargs":{"restraint":true}}'

// ── Путь лога: зеркало src/core/artifact_paths.get_gate_log_path ──
// <data_root>/projects/<hash8>/gate_telemetry.jsonl, hash8 = md5(lower(path с `/`))[:8].
// MSCODEBASE_GATE_LOG имеет приоритет (обратная совместимость).
export function projectHash(projectPath: string): string {
  const normalized = resolve(projectPath).toLowerCase().replace(/\\/g, "/")
  return createHash("md5").update(normalized).digest("hex").slice(0, 8)
}

export function dataRoot(): string {
  const explicit = (process.env.MSCODEBASE_DATA_DIR ?? "").trim()
  if (explicit) return explicit
  const legacy = (process.env.BASE_INDEX_DIR ?? "").trim()
  if (legacy && isAbsolute(legacy)) return legacy
  if (process.platform === "win32") return join(process.env.LOCALAPPDATA ?? tmpdir(), "mscodebase")
  const xdg = (process.env.XDG_CACHE_HOME ?? "").trim()
  if (xdg) return join(xdg, "mscodebase")
  return join(homedir(), ".cache", "mscodebase")
}

export function resolveGateLog(directory: string): string {
  const override = (process.env.MSCODEBASE_GATE_LOG ?? "").trim()
  if (override) return override
  try {
    return join(dataRoot(), "projects", projectHash(directory), "gate_telemetry.jsonl")
  } catch {
    return join(tmpdir(), "opencode", "mscodebase_gate.log") // never break the host
  }
}

// ── Чистые функции решения/разбора (экспортированы для node --test; без I/O) ──
export type GateReason =
  | "fired_block"
  | "fired_advisory"
  | "suppressed_restraint"
  | "suppressed_zero_findings"
  | "skipped_off"
  | "error_unavailable"
  | "error_exception"

export interface StaleParsed {
  drift: number
  unavailable: boolean
}

export interface RestraintDetail {
  signature: string
  strikes: number
  cooldown_s_left: number
}

export interface IsolationParsed {
  count: number
  suppressed: boolean
  restraint: RestraintDetail | null
  unavailable: boolean
}

export interface GateDecision {
  delivered: boolean
  reason: GateReason
}

// ── Строка телеметрии: единый конструктор (одна оценка — одна строка) ──
export interface GateRow {
  t?: number
  gate: "stale" | "isolation"
  mode: string
  act: string
  drift?: number
  count?: number
  delivered: boolean
  reason: GateReason
  restraint?: RestraintDetail
  latency_ms: number
  refusal_len?: number
  // M4 advisory-text override (только когда override вооружён; иначе ключей нет —
  // строки по умолчанию побайтово идентичны форме до изменения):
  override?: boolean
  real_len?: number
  real_hash?: string
}

// Module-local on purpose: opencode >=1.16 legacy loader throws on any non-function
// module export ("Plugin export is not a function"), which kills the whole plugin before
// hooks register. Tests assert the schema against their own copy (see gate_telemetry.test.mjs).
const ROW_REQUIRED_KEYS = ["t", "gate", "mode", "act", "delivered", "reason", "latency_ms"] as const

export function makeRow(r: GateRow): GateRow {
  return { t: Date.now(), ...r }
}

export function parseStale(out: string): StaleParsed {
  const m = /Total drift instances:\s*(\d+)/i.exec(out ?? "")
  return {
    drift: m ? parseInt(m[1], 10) : 0,
    unavailable: !out || /not available|cannot determine|not found/i.test(out),
  }
}

export function parseIsolation(out: string): IsolationParsed {
  const text = out ?? ""
  const r = /removed_last_caller:\s*(\d+)/i.exec(text)
  const n = /new_orphan:\s*(\d+)/i.exec(text)
  const count = (r ? parseInt(r[1], 10) : 0) + (n ? parseInt(n[1], 10) : 0)
  const sig = /signature:\s*([0-9a-f]{8,64})/i.exec(text)
  const strikes = /strikes:\s*(\d+)/i.exec(text)
  const left = /cooldown_s_left:\s*(\d+)/i.exec(text)
  return {
    count,
    suppressed: /deliver:\s*✗/i.test(text) || /deliver:\s*false/i.test(text),
    restraint:
      sig && strikes && left
        ? { signature: sig[1], strikes: parseInt(strikes[1], 10), cooldown_s_left: parseInt(left[1], 10) }
        : null,
    unavailable: !text || /not available|not found|unavailable/i.test(text),
  }
}

export function decideStale(mode: string, parsed: StaleParsed, cliFailed: boolean): GateDecision {
  if (mode === "off") return { delivered: false, reason: "skipped_off" }
  if (cliFailed) return { delivered: false, reason: "error_exception" }
  if (parsed.unavailable) return { delivered: false, reason: "error_unavailable" }
  if (mode === "block" && parsed.drift > 0) return { delivered: true, reason: "fired_block" }
  // stale без блокировки доставлять некуда (advisory-канала нет): оценка сработала, доставки нет.
  if (parsed.drift > 0) return { delivered: false, reason: "fired_advisory" }
  return { delivered: false, reason: "suppressed_zero_findings" }
}

export function decideIsolation(mode: string, parsed: IsolationParsed, cliFailed: boolean): GateDecision {
  if (mode === "off") return { delivered: false, reason: "skipped_off" }
  if (cliFailed) return { delivered: false, reason: "error_exception" }
  if (parsed.unavailable && parsed.count === 0) return { delivered: false, reason: "error_unavailable" }
  if (parsed.count > 0) {
    if (mode === "block") return { delivered: true, reason: "fired_block" }
    if (mode === "advisory")
      return parsed.suppressed
        ? { delivered: false, reason: "suppressed_restraint" }
        : { delivered: true, reason: "fired_advisory" }
    // недокументированный режим: как раньше — ни throw, ни stash; оценка сработала, доставки нет.
    return { delivered: false, reason: "fired_advisory" }
  }
  return { delivered: false, reason: "suppressed_zero_findings" }
}

// ── M4 advisory-text override (additive, default-off; см. REDTEAM-M4 harness amendment) ──
// MSCODEBASE_ADVISORY_TEXT: когда задан И непуст И isolation в advisory И findings > 0,
// tool.execute.after дописывает ЭТОТ текст дословно вместо вывода гейта.
// Всё остальное нетронуто: реальный вывод всё равно считается, стэшится и логируется
// (строка несёт override:true + real_len/real_hash); block-режим override игнорирует
// полностью; тихий гейт (0 findings) молчит и с включённым override.
export function advisoryOverrideText(): string {
  const raw = process.env.MSCODEBASE_ADVISORY_TEXT
  return raw !== undefined && raw !== null && raw.length > 0 ? raw : ""
}

export function realOutputHash(out: string): string {
  return createHash("md5").update(out ?? "").digest("hex")
}

export interface AdvisoryNote {
  text: string
  override: boolean
  realLen: number
  realHash: string
}

// Чистое решение для tool.execute.after: null = ничего не дописывать
// (не-advisory режим; пустой stash; count == 0 — доставка не выдумывается никогда).
export function buildAdvisoryNote(cached: string | undefined, mode: string): AdvisoryNote | null {
  if (mode !== "advisory") return null
  if (!cached) return null
  if (parseIsolation(cached).count <= 0) return null // тихий гейт молчит: override доставку не изобретает
  const override = advisoryOverrideText()
  if (override) {
    return { text: override, override: true, realLen: cached.length, realHash: realOutputHash(cached) }
  }
  return {
    text: `\n\n✦ GRAPH-GATE (advisory): this commit isolates graph node(s).\n${cached.slice(0, 500)}`,
    override: false,
    realLen: cached.length,
    realHash: realOutputHash(cached),
  }
}

// Дополнительные ключи строки isolation. ПУСТОЙ объект когда override выключен или
// неприменим → строки по умолчанию побайтово идентичны форме до изменения.
export function isolationRowExtra(out: string, parsed: IsolationParsed, mode: string): Record<string, unknown> {
  const override = advisoryOverrideText()
  if (!override || mode !== "advisory" || parsed.count <= 0) return {}
  return { override: true, real_len: out.length, real_hash: realOutputHash(out) }
}

export function actOf(output: unknown): string {
  const cmd = String((output as { args?: { command?: unknown } })?.args?.command ?? "")
  return `bash ${cmd}`.replace(/\s+/g, " ").trim().slice(0, 200)
}

// Global git options that take a separate value token. `git -C <path> commit` and
// `git -c k=v commit` are the SAME command as `git commit`; a regex requiring
// adjacency let them through un-gated (M4 full-30 run 11, 30/30 transcripts).
const GIT_VALUE_OPTS = new Set([
  "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
])

export function isGitCommit(cmd: string): boolean {
  // Quoted segments are data, not commands: `echo 'git commit -m x'` must not be
  // gated, otherwise printing a command triggers the gate (over-gating is safe but
  // noisy and trains agents to ignore advisory output).
  const tokens = String(cmd).replace(/'[^']*'/g, " ").replace(/"[^"]*"/g, " ").split(/\s+/).filter(Boolean)
  for (let i = 0; i < tokens.length; i++) {
    if (!/\bgit(?:\.exe)?$/i.test(tokens[i])) continue
    for (let j = i + 1; j < tokens.length; j++) {
      const t = tokens[j]
      if (t === "--") break
      if (GIT_VALUE_OPTS.has(t)) { j++; continue }
      if (t.startsWith("-")) continue
      return t === "commit"
    }
    return false
  }
  return false
}

export function cli(directory: string, tool: string, argsJson: string): Promise<string> {
  const py = process.env.MSCODEBASE_PY ?? join(directory, "venv", "Scripts", "python.exe")
  return new Promise((resolve) => {
    try {
      execFile(
        py,
        ["-m", "src.cli", tool, argsJson],
        { cwd: directory, timeout: 90000, windowsHide: true, maxBuffer: 4 * 1024 * 1024 },
        (_err, stdout) => resolve(stdout ?? ""),
      )
    } catch {
      resolve("") // fail-open: пустой вывод → error_unavailable в строке гейта
    }
  })
}

// Non-exported on purpose (see note on STALE_MODE above): the live stash used by
// the factory lives in mscodebase_gate.ts; this copy preserves the original text.
const stash = new Map<string, string>()
