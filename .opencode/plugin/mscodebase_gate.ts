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
//
// LOADER CONTRACT (opencode ≥1.16): legacy plugin loader итерирует
// Object.values(module) и ВЫЗЫВАЕТ каждый function-экспорт как фабрику плагина
// (см. opencode issues #41234/#31575/#42451). Поэтому этот входной модуль обязан
// экспортировать ТОЛЬКО default-фабрику — никаких других runtime-экспортов
// (включая const). Все хелперы живут в ../../tools/gate_helpers.ts; тесты хелперов
// импортируют gate_helpers.ts напрямую, а loader-safety тест импортирует ЭТОТ
// модуль и проверяет Object.keys(entry) === ["default"].

import type { Plugin } from "@opencode-ai/plugin"
import { appendFileSync, mkdirSync } from "node:fs"
import { dirname } from "node:path"
import {
  resolveGateLog,
  makeRow,
  parseStale,
  parseIsolation,
  decideStale,
  decideIsolation,
  buildAdvisoryNote,
  isolationRowExtra,
  cli,
  actOf,
  isGitCommit,
} from "../../tools/gate_helpers.ts"
import type { GateRow } from "../../tools/gate_helpers.ts"

// Module-local config + stash (identical lines to the pre-split module):
// the entry must export ONLY default, so values the factory closes over live here,
// not as helper exports (opencode ≥1.16 legacy loader would invoke function
// exports and choke on non-function ones — issues #41234/#31575).
// Project-local venv by default; MSCODEBASE_PY overrides. No machine-specific path.
const STALE_MODE = process.env.MSCODEBASE_STALE_GATE ?? "block"
const ISO_MODE = process.env.MSCODEBASE_ISOLATION_GATE ?? "advisory"

const STALE_ARGS = "{}"
const ISO_ARGS = '{"action":"isolation","kwargs":{"restraint":true}}'

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
      // Контракт хоста: хук никогда не бросает. opencode ≥1.18 вызывает хуки с
      // формами входа, которые мы не контролируем (undefined input/output) —
      // непроверенный доступ ронял весь сервер (M4 smoke, попытки 2–3).
      if (!input || typeof input !== "object" || !output || typeof output !== "object") return
      if (input.tool !== "bash") return
      const cmd = String(output.args?.command ?? "")
      // Tokenizer, not /\bgit\s+commit\b/: global options such as `git -C <dir> commit`
      // are the same command and must be gated too (M4 full-30 run 11 slipped through).
      if (!isGitCommit(cmd)) return
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
      if (!input || typeof input !== "object" || !output || typeof output !== "object") return
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
