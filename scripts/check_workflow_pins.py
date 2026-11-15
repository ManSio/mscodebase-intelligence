"""Supply-chain gate: workflow actions are pinned to a commit, checkouts drop the token.

`uses: actions/checkout@v5` follows a moving tag. Whoever can move that tag runs
code in our CI with the workflow token, on every push. On 2026-11-14 all ten
`uses:` references in this repository were tag-pinned (`.github/workflows/*.yml`),
so the invariant now lives here instead of in a reviewer's memory
(benchmark: affaan-m/ECC pins `owner/action@<40 hex> # vX.Y.Z` and sets
`persist-credentials: false`).

Rules per workflow file:
  R1  every remote `uses:` is `owner/action@<40 hex>` and names the version in a
      trailing comment (`# v5.1.0`) — the SHA alone is unreadable six months later;
  R2  every `actions/checkout` step sets `persist-credentials: false` — no token
      is left in `.git/config` for later steps to find.

Local (`./path`) and `docker://` references are not tag-pinned actions and are
skipped. An empty scan (no workflows, or no `uses:`) is a failure, not a pass:
"nothing found" must never look green.

Exit codes: 0 clean, 1 violations or empty scan.

Usage:
    python scripts/check_workflow_pins.py
    python scripts/check_workflow_pins.py --root .
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

USES_RE = re.compile(r"^(?P<indent>\s*)(?:-\s+)?uses:\s*(?P<ref>\S+)(?P<tail>.*)$")
PINNED_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")
VERSION_RE = re.compile(r"#\s*v\d")
CHECKOUT = "actions/checkout@"


def scan_text(text: str) -> tuple[list[str], int, int]:
    """Return (problems, uses_count, checkout_count) for one workflow file."""
    lines = text.splitlines()
    problems: list[str] = []
    uses = 0
    checkouts = 0

    for idx, line in enumerate(lines, start=1):
        m = USES_RE.match(line)
        if not m:
            continue
        ref, tail = m.group("ref"), m.group("tail")
        if ref.startswith("./") or ref.startswith("docker://"):
            continue
        uses += 1
        if not PINNED_RE.match(ref):
            problems.append(
                f"line {idx}: `{ref}` is not pinned to a 40-character commit SHA "
                f"(a tag can be moved under us)"
            )
            continue
        if not VERSION_RE.search(tail):
            problems.append(
                f"line {idx}: `{ref}` has no version comment (`# vX.Y.Z`) — "
                f"the SHA is unreadable on the next bump"
            )
        if not ref.startswith(CHECKOUT):
            continue
        checkouts += 1
        indent = len(m.group("indent"))
        block: list[str] = []
        for follow in lines[idx:]:
            stripped = follow.strip()
            if stripped.startswith("- ") and (len(follow) - len(follow.lstrip())) <= indent:
                break
            block.append(stripped)
        if "persist-credentials: false" not in block:
            problems.append(
                f"line {idx}: checkout does not set `persist-credentials: false` — "
                f"the git token stays in .git/config for later steps"
            )
    return problems, uses, checkouts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()

    root = Path(args.root).resolve()
    workflows = sorted((root / ".github" / "workflows").glob("*.yml"))
    if not workflows:
        print("workflow-pins: no workflow files found — refusing to pass", file=sys.stderr)
        return 1

    total_uses = total_checkouts = 0
    problems: list[tuple[str, str]] = []
    for wf in workflows:
        found, uses, checkouts = scan_text(wf.read_text(encoding="utf-8", errors="replace"))
        total_uses += uses
        total_checkouts += checkouts
        problems.extend((wf.name, p) for p in found)

    if total_uses == 0:
        print("workflow-pins: no `uses:` references found — refusing to pass", file=sys.stderr)
        return 1

    for name, problem in problems:
        print(f"  FAIL {name}: {problem}")
    print(
        f"workflow-pins: {len(workflows)} workflow(s), {total_uses} uses, "
        f"{total_checkouts} checkout(s), {len(problems)} problem(s)"
    )
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
