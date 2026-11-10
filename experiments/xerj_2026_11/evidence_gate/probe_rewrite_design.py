"""Dry analysis: which panel questions does each rewrite rule gate, and why.

No retrieval: this is the design pass before the three-arm experiment.
"""

import json
import re
import sys
from pathlib import Path

REPO = Path(r"D:\Project\MSCodeBase")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "xerj_2026_11"))
sys.stdout.reconfigure(encoding="utf-8")

from run_baseline import parse_tasks  # noqa: E402
from src.mcp.tools.investigate_tool import (  # noqa: E402
    _identifiers,
    _needs_identifier_rewrite,
)

PROPER = re.compile(r"\b[A-Z][a-z]{2,}\b")
BACKTICK_LATIN = re.compile(r"`[^`]*[A-Za-z][^`]*`")
CYR = re.compile(r"[А-Яа-яЁё]")


def smart_gate(query: str) -> bool:
    """Candidate rule: gate only when the question names a proper-noun-like
    Latin word and no code-shaped token / backticked Latin token."""
    if not CYR.search(query):
        return False
    if BACKTICK_LATIN.search(query):
        return False
    if _needs_identifier_rewrite(query, _identifiers(query)) is None:
        return False
    return bool(PROPER.search(query))


def rows():
    task = parse_tasks()
    for t in task:
        if CYR.search(t["question"]):
            yield t["id"], t["kind"], t["question"]
    data = json.loads(
        (REPO / "experiments/xerj_2026_11/mcp_audit/questions.json").read_text(
            encoding="utf-8"
        )
    )
    for project, spec in data["projects"].items():
        for index, (question, _gold) in enumerate(spec.get("ru") or [], 1):
            yield f"{project[:3].upper()}RU{index}", "positive", question


print(f"{'id':<8}{'current':>9}{'smart':>7}  latin tokens")
counts = {"current": 0, "smart": 0, "n": 0}
for task_id, kind, question in rows():
    counts["n"] += 1
    current = _needs_identifier_rewrite(question, _identifiers(question)) is not None
    smart = smart_gate(question)
    counts["current"] += int(current)
    counts["smart"] += int(smart)
    tokens = _identifiers(question)
    print(f"{task_id:<8}{str(current):>9}{str(smart):>7}  {tokens}  {question[:64]}")

print(f"\nqueries: {counts['n']}  current gates: {counts['current']}  smart gates: {counts['smart']}")
