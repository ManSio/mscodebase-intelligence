// mscodebase_gate.ts — opencode-хук: детерминированные заметки MSCodeBase в момент действия.
//
// Два гейта на `git commit` (мост: `python -m src.cli <tool> <json>`, cwd=проект; CLI --project игнорирует):
//   1. stale_detector — BLOCK при дрейфе версий (доказан в E6: модель отказ не обходит).
//   2. graph_query isolation — ADVISORY: «тихий слом» графа (осиротение узла). Soft: у гейта есть FP.
//
// Advisory реализован через before+after: pre-commit diff считается в `before` и кладётся в stash по
// callID; текст дописывается в результат в `after` (не блокирует). Блокирующий режим — только stale
// (объективный) и явный MSCODEBASE_ISOLATION_GATE=block.
//
// Переключатели (env): MSCODEBASE_PY, MSCODEBASE_STALE_GATE=block|off,
//                      MSCODEBASE_ISOLATION_GATE=advisory|block|off,
//                      MSCODEBASE_GATE_LOG (явный путь к JSONL),
//                      MSCODEBASE_ADVISORY_TEXT (M4 override: фиксированный текст
//                        advisory-заметки вместо вывода гейта; additive, default-off),
//                      MSCODEBASE_DATA_DIR / BASE_INDEX_DIR (корень данных для пути по умолчанию).
// Хук никогда не роняет хост: любые сбои → лог, без throw (кроме намеренного блока).
//
// Телеметрия: на КАЖДУЮ оценку гейта — РОВНО ОДНА JSON-строка в gate_telemetry.jsonl
// (data dir проекта, см. src/core/artifact_paths.get_gate_log_path — НЕ %TEMP%):
//   {t, gate: stale|isolation, mode, act, drift|count, delivered, reason, restraint?, latency_ms, refusal_len?}
// reason ∈ fired_block | fired_advisory | suppressed_restraint | suppressed_zero_findings
//          | skipped_off | error_unavailable | error_exception.
// Правило: та же ветка, что РЕШАЕТ (throw/stash/suppress), и ПИШЕТ строку —
// второго кодового пути нет (комментарий у каждой эмиссии называет зеркалимое решение).
// В лог НЕ пишутся тела findings/выводы CLI (только refusal_len) — секретоподобный
// текст в принципе не попадает в файл (вывод CLI и так проходит redact.py на стороне src/cli.py).
//
// ВАЖНО: вызов python — через node:child_process, НЕ через `$` из контекста плагина: в opencode
// 1.18.23 контекст фабрики не содержит `$` (API дрейфанул) → `TypeError: $ is not a function`.

import type { Plugin } from "@opencode-ai/plugin"
import { appendFileSync, mkdirSync } from "node:fs"
import { execFile } from "node:child_process"
import { createHash } from "node:crypto"
import { dirname, isAbsolute, join, resolve } from "node:path"
import { homedir, tmpdir } from "node:os"

// Project-local venv by default; MSCODEBASE_PY overrides. No machine-specific path.
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

function actOf(output: unknown): string {
  const cmd = String((output as { args?: { command?: unknown } })?.args?.command ?? "")
  return `bash ${cmd}`.replace(/\s+/g, " ").trim().slice(0, 200)
}

function cli(directory: string, tool: string, argsJson: string): Promise<string> {
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

const stash = new Map<string, string>()

export default (async ({ directory }) => {
  const LOG = resolveGateLog(directory ?? "")
  const emit = (rec: Record<string, unknown>) => {
    try {
      mkdirSync(dirname(LOG), { recursive: true })
      // единый конструктор строки (makeRow): вся телеметрия идёт через эту точку
      appendFileSync(LOG, JSON.stringify(makeRow(rec as GateRow)) + "\n")
    } catch {
      // never break the host
    }
  }
  emit({ kind: "init", directory, stale: STALE_MODE, isolation: ISO_MODE, log: LOG })
  return {
    "tool.execute.before": async (input: any, output: any) => {
      if (input.tool !== "bash") return
      const cmd = String(output.args?.command ?? "")
      if (!/\bgit\s+commit\b/.test(cmd)) return
      const act = actOf(output)

      // ── Gate 1: stale_detector ──
      if (STALE_MODE === "off") {
        // mirrors the skip branch: gate off → no CLI call, nothing delivered
        emit({ gate: "stale", mode: STALE_MODE, act, drift: 0, delivered: false, reason: "skipped_off", latency_ms: 0 })
      } else {
        const t0 = Date.now()
        try {
          const out = await cli(directory, "stale_detector", STALE_ARGS)
          const parsed = parseStale(out)
          const latency_ms = Date.now() - t0
          if (STALE_MODE === "block" && parsed.drift > 0) {
            const err = new Error(
              `CRYSTAL-GATE: ${parsed.drift} doc-drift instance(s). Docs assert a version the code no longer is.\n${out.slice(0, 500)}`,
            )
            // mirrors the throw below: refusal length, never the text
            emit({ gate: "stale", mode: STALE_MODE, act, drift: parsed.drift, delivered: true, reason: "fired_block", refusal_len: String(err).length, latency_ms })
            throw err
          }
          // mirrors the fall-through branch: no block → nothing delivered, reason from the same parse
          const d = decideStale(STALE_MODE, parsed, false)
          emit({ gate: "stale", mode: STALE_MODE, act, drift: parsed.drift, delivered: d.delivered, reason: d.reason, latency_ms })
        } catch (e) {
          if (String(e).includes("CRYSTAL-GATE")) throw e
          // mirrors the swallow-and-continue branch: host never breaks on gate errors
          emit({ gate: "stale", mode: STALE_MODE, act, drift: 0, delivered: false, reason: "error_exception", latency_ms: Date.now() - t0 })
        }
      }

      // ── Gate 2: graph isolation ──
      if (ISO_MODE === "off") {
        // mirrors the skip branch: gate off → no CLI call, nothing delivered
        emit({ gate: "isolation", mode: ISO_MODE, act, count: 0, delivered: false, reason: "skipped_off", latency_ms: 0 })
      } else {
        const t0 = Date.now()
        try {
          const out = await cli(directory, "graph_query", ISO_ARGS)
          const parsed = parseIsolation(out)
          const latency_ms = Date.now() - t0
          if (parsed.count > 0 && ISO_MODE === "block") {
            const err = new Error(`GRAPH-GATE (block): this commit isolates ${parsed.count} graph node(s).\n${out.slice(0, 500)}`)
            // mirrors the throw below: refusal length, never the text
            emit({ gate: "isolation", mode: ISO_MODE, act, count: parsed.count, delivered: true, reason: "fired_block", refusal_len: String(err).length, ...(parsed.restraint ? { restraint: parsed.restraint } : {}), latency_ms })
            throw err
          }
          // mirrors the stash/suppress/fall-through branch below: the SAME parsed values feed the row
          if (parsed.count > 0 && ISO_MODE === "advisory" && !parsed.suppressed) stash.set(input.callID, out)
          const d = decideIsolation(ISO_MODE, parsed, false)
          emit({ gate: "isolation", mode: ISO_MODE, act, count: parsed.count, delivered: d.delivered, reason: d.reason, ...(parsed.restraint ? { restraint: parsed.restraint } : {}), ...isolationRowExtra(out, parsed, ISO_MODE), latency_ms })
        } catch (e) {
          if (String(e).includes("GRAPH-GATE")) throw e
          // mirrors the swallow-and-continue branch: host never breaks on gate errors
          emit({ gate: "isolation", mode: ISO_MODE, act, count: 0, delivered: false, reason: "error_exception", latency_ms: Date.now() - t0 })
        }
      }
    },

    "tool.execute.after": async (input: any, output: any) => {
      if (ISO_MODE !== "advisory") return
      const cached = stash.get(input.callID)
      if (!cached) return
      stash.delete(input.callID)
      // без лог-строки: fired_advisory уже записана в before (одна оценка — одна строка)
      const note = buildAdvisoryNote(cached, ISO_MODE)
      if (!note) return // тихий гейт молчит и с включённым override: доставка не выдумывается
      output.output = (output.output ?? "") + note.text
    },
  }
}) satisfies Plugin
