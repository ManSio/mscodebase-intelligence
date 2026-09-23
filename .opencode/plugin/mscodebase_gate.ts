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
//                      MSCODEBASE_ISOLATION_GATE=advisory|block|off, MSCODEBASE_GATE_LOG.
// Хук никогда не роняет хост: любые сбои → лог, без throw (кроме намеренного блока).
//
// ВАЖНО: вызов python — через node:child_process, НЕ через `$` из контекста плагина: в opencode
// 1.18.23 контекст фабрики не содержит `$` (API дрейфанул) → `TypeError: $ is not a function`.

import type { Plugin } from "@opencode-ai/plugin"
import { appendFileSync, mkdirSync } from "node:fs"
import { execFile } from "node:child_process"
import { dirname } from "node:path"

const PY = process.env.MSCODEBASE_PY ?? "D:/Project/MSCodeBase/venv/Scripts/python.exe"
const LOG = process.env.MSCODEBASE_GATE_LOG ?? "C:/Users/misha/AppData/Local/Temp/opencode/mscodebase_gate.log"
const STALE_MODE = process.env.MSCODEBASE_STALE_GATE ?? "block"
const ISO_MODE = process.env.MSCODEBASE_ISOLATION_GATE ?? "advisory"

const STALE_ARGS = "{}"
const ISO_ARGS = '{"action":"isolation","kwargs":{"restraint":true}}'

function log(rec: Record<string, unknown>) {
  try {
    mkdirSync(dirname(LOG), { recursive: true })
    appendFileSync(LOG, JSON.stringify({ t: Date.now(), ...rec }) + "\n")
  } catch {
    // never break the host
  }
}

function cli(directory: string, tool: string, argsJson: string): Promise<string> {
  return new Promise((resolve) => {
    try {
      execFile(
        PY,
        ["-m", "src.cli", tool, argsJson],
        { cwd: directory, timeout: 90000, windowsHide: true, maxBuffer: 4 * 1024 * 1024 },
        (_err, stdout) => resolve(stdout ?? ""),
      )
    } catch (e) {
      log({ kind: "cli_spawn_error", err: String(e).slice(0, 200) })
      resolve("")
    }
  })
}

function staleDrift(out: string): number {
  const m = /Total drift instances:\s*(\d+)/i.exec(out)
  return m ? parseInt(m[1], 10) : 0
}

function isolationCount(out: string): number {
  const r = /removed_last_caller:\s*(\d+)/i.exec(out)
  const n = /new_orphan:\s*(\d+)/i.exec(out)
  return (r ? parseInt(r[1], 10) : 0) + (n ? parseInt(n[1], 10) : 0)
}

function isolationSuppressed(out: string): boolean {
  return /deliver:\s*✗/i.test(out) || /deliver:\s*false/i.test(out)
}

const stash = new Map<string, string>()

export default (async ({ directory }) => {
  log({ kind: "init", directory, stale: STALE_MODE, isolation: ISO_MODE })
  return {
    "tool.execute.before": async (input: any, output: any) => {
      if (input.tool !== "bash") return
      const cmd = String(output.args?.command ?? "")
      if (!/\bgit\s+commit\b/.test(cmd)) return

      // ── Gate 1: stale_detector (block) ──
      if (STALE_MODE !== "off") {
        try {
          const out = await cli(directory, "stale_detector", STALE_ARGS)
          const drift = staleDrift(out)
          log({ kind: "stale", drift, out: out.slice(0, 400) })
          if (STALE_MODE === "block" && drift > 0) {
            log({ kind: "stale_block", drift })
            throw new Error(
              `CRYSTAL-GATE: ${drift} doc-drift instance(s). Docs assert a version the code no longer is.\n${out.slice(0, 500)}`,
            )
          }
        } catch (e) {
          if (String(e).includes("CRYSTAL-GATE")) throw e
          log({ kind: "stale_error", err: String(e).slice(0, 200) })
        }
      }

      // ── Gate 2: graph isolation (advisory/block) ──
      if (ISO_MODE !== "off") {
        try {
          const out = await cli(directory, "graph_query", ISO_ARGS)
          const count = isolationCount(out)
          log({ kind: "isolation", count, out: out.slice(0, 400) })
          if (count > 0) {
            if (ISO_MODE === "block") {
              log({ kind: "isolation_block", count })
              throw new Error(`GRAPH-GATE (block): this commit isolates ${count} graph node(s).\n${out.slice(0, 500)}`)
            }
            if (!isolationSuppressed(out)) stash.set(input.callID, out)
          }
        } catch (e) {
          if (String(e).includes("GRAPH-GATE")) throw e
          log({ kind: "isolation_error", err: String(e).slice(0, 200) })
        }
      }
    },

    "tool.execute.after": async (input: any, output: any) => {
      if (ISO_MODE !== "advisory") return
      const cached = stash.get(input.callID)
      if (!cached) return
      stash.delete(input.callID)
      log({ kind: "isolation_advisory", len: cached.length })
      output.output =
        (output.output ?? "") +
        `\n\n✦ GRAPH-GATE (advisory): this commit isolates graph node(s).\n${cached.slice(0, 500)}`
    },
  }
}) satisfies Plugin
