# Archive

Material kept for provenance. **Nothing here describes the current product.** Every
file is either a dated snapshot (diaries, monthly issue logs), a superseded plan, or a
consumed research spec.

| Path | What it is | Rule |
|---|---|---|
| `AGENT_DIARY_YYYY_MM.md` | monthly rotations of the live diary | append-only history |
| `KNOWN_ISSUES_YYYY_MM.md` | monthly rotations of the live issue board | **required** by `scripts/check_known_issues.py` R2 — do not delete a month that the live board still references |
| `KNOWN_ISSUES_REDIRECT.md` | redirect stub after the first rotation | keep (tiny) |
| `DEV_DIARY_2026_07.md`, `AGENT_DIARY_2026_0*.md` | pre-rotation diaries | keep |
| `ARCHITECTURE_2026-07-20.md` | architecture snapshot from the LSP-bridge era | keep as history |
| `ARCHITECTURE_AUDIT_MCP_vs_IDE.md`, `BENCHMARK*.md`, `SANATION_REPORT.md` | 2026-07 reports; the configs and tools they describe are gone | keep as history |
| `ISSUES/*.md` | external review verdicts (2026-08) whose outcomes already moved into `KNOWN_ISSUES.md` | keep as history |
| `research/*.md` | consumed research notes and benchmarks from the dense-first era | keep as history |
| `i18n/{en,ru,zh}/` | archived translated pages (HANDOFF, ARCHITECTURE_LAYERS, ARCHITECTURE_DEEP) with a banner | keep as history |

Current documentation: `README.md`, `docs/en/*` (canon), `docs/ru/*`, `docs/zh/*`,
numbers in `docs/FACTS.md`.

Removal rule: an archived file may be deleted only when nothing references it **and**
a gate does not depend on it. Duplicated auto-generated entries inside a month are the
only case where deletion was already done (2026-11-08).
