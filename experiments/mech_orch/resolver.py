"""E4.2 — deterministic concept→symbol resolver (mechanical, no LLM).

Extends E4.1's lexical extract_symbol with a concept-phrase registry consulted
BEFORE lexical extraction. Fixes the two "wordless" verify_change failures
where the target is described by consequence/concept rather than by symbol name:
  - T9  : "какой инструмент … для обновления индекса" -> notify_change
          (lexical pulled "engine" — wrong-anchor)
  - T29 : "паттерны извлечения" -> _extract_symbol_name
          (no lexical anchor at all -> cascade fallback)

Table lookup is intentionally not an LLM classifier — it matches the mechanical
intent-router recommendation (RESEARCH.md rec #3): deterministic recipe registry,
fail-open (no hit -> caller falls back to lexical extraction).

Seed set covers the E4.1 verify_change failures; mechanism generalizes.
Corpus-tuned seeding from the 3300-call corpus (RESEARCH.md rec 3) = follow-up.
"""
from pathlib import Path

# (phrases, klass, symbol).  klass=None => applies to any klass.
# Checked in order; first matching recipe wins. Phrases matched as lowercase
# substrings (more robust than regex on Russian morphology for fixed phrases).
CONCEPT_RECIPES = [
    {
        "phrases": [
            "инструмент для обновления индекса",
            "обновления индекса",
            "обновление индекса",
            "обновить индекс",
        ],
        "klass": "verify_change",
        "symbol": "notify_change",
    },
    {
        "phrases": [
            "паттерны извлечения",
            "паттернов извлечения",
            "паттерн извлечения",
            "извлечения паттерн",
            "паттерны извлечений",
        ],
        "klass": "verify_change",
        "symbol": "_extract_symbol_name",
    },
]


def concept_symbol(prompt: str, klass: str) -> str:
    """Return the concept-mapped symbol for a prompt+klass, or "" if no recipe
    hits. Fail-open: caller falls back to lexical extract_symbol.
    """
    if not prompt:
        return ""
    low = " ".join(prompt.lower().split())
    for recipe in CONCEPT_RECIPES:
        if recipe["klass"] and recipe["klass"] != klass:
            continue
        for phrase in recipe["phrases"]:
            if phrase in low:
                return recipe["symbol"]
    return ""


def read_snippet(file_path, line, before=3, after=9):
    """Read a small source window around `line` (1-based). '' on error/absent."""
    try:
        fp = Path(file_path)
        if not fp.exists():
            return ""
        lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
        lo = max(0, int(line) - 1 - before)
        hi = min(len(lines), int(line) - 1 + after)
        return "\n".join(lines[lo:hi])
    except Exception:  # noqa: BLE001 — fail-open by design: snippet read must never break resolution
        return ""


def graph_fact_text(adapter, sym: str) -> str:
    """Gather definition file paths + source snippets for `sym` into a text blob
    to run required_facts coverage against (Option V: graph rows carry evidence,
    not just file paths). Adapter.definitions expose file_path+line only."""
    parts = []
    try:
        defs = adapter.find_definitions(sym) or []
    except Exception:  # noqa: BLE001 — fail-open by design: unknown adapter surface
        defs = []
    for r in defs:
        fp = getattr(r, "file_path", "") or ""
        line = getattr(r, "line", 0) or 0
        if fp:
            parts.append(fp)
        if fp and line:
            parts.append(read_snippet(fp, line))
    return "\n".join(p for p in parts if p)
