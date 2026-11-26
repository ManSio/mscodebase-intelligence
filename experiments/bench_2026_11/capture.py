"""Capture cache for the commit-localization benchmark.

`run.py` writes one JSON row per finished task to `results_<split>.partial.jsonl`
so a run that dies at task 16 does not start over. That convenience produced a
bug worth more than the feature: the capture was committed to git, every later
run resumed from it, and the benchmark reprinted November's numbers for four
days after the gate under test had changed (E74).

Rule enforced here: **reuse requires an explicit `--resume`**. Without it the
stale capture is dropped and the panel is executed from scratch, because an
appended run on top of old rows would silently mix two products.

Since 2026-11-26 a row also carries `runtime` (see `runtime.py`): the backend the
scoring path actually used, the embedder call count, and the rerank modes. A
capture that mixes runtime stamps is refused when the differing component was
used; a text-only panel that never called the embedder may survive a daemon flap,
but the row must say `embed_calls=0` instead of the author remembering it.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_capture(path: Path, resume: bool) -> tuple[list[dict], set[str]]:
    """Return (rows, ids) from a previous capture, or nothing.

    `resume=False` also deletes the stale file: `run.py` appends to it, so
    keeping it would mix the new run with the old one.
    """
    path = Path(path)
    if not path.is_file():
        return [], set()
    if not resume:
        print(
            f"stale capture {path.name} ignored and dropped: "
            "pass --resume to reuse it, otherwise the panel runs from scratch",
            flush=True,
        )
        path.unlink(missing_ok=True)
        return [], set()

    rows: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(
                f"capture {path.name} is corrupt at line {number} ({exc.msg}): "
                "dropping it and running the panel from scratch",
                flush=True,
            )
            path.unlink(missing_ok=True)
            return [], set()
    unique = {}
    for row in rows:
        unique.setdefault(row["id"], row)
    if len(unique) != len(rows):
        print(f"capture {path.name}: {len(rows) - len(unique)} duplicate rows ignored",
              flush=True)
        rows = list(unique.values())
    print(f"resuming: {len(rows)} tasks already captured", flush=True)
    return rows, {row["id"] for row in rows}


_RUNTIME_FIELDS = frozenset({
    "embedder", "embed_calls", "rerank_modes", "dense_off", "ondemand_rerank",
})
_INERT_RERANK_MODES = frozenset({"sqlite_fts5"})


def _runtime_complete(runtime: object) -> bool:
    """A stamp is usable only if every field has the type the writer emits.

    `{}`, a string count, a bool count, or an empty rerank list are not "inert";
    they are measurements that did not happen. Treating them as inert would let a
    malformed row bypass the guard.
    """
    if not isinstance(runtime, dict) or not _RUNTIME_FIELDS <= set(runtime):
        return False
    if not isinstance(runtime["embedder"], str) or not runtime["embedder"]:
        return False
    calls = runtime["embed_calls"]
    if isinstance(calls, bool) or not isinstance(calls, int) or calls < 0:
        return False
    modes = runtime["rerank_modes"]
    if not isinstance(modes, list) or not modes:
        return False
    if any(not isinstance(mode, str) or not mode for mode in modes):
        return False
    return all(isinstance(runtime[key], bool) for key in ("dense_off", "ondemand_rerank"))


def _runtime_used(runtime: dict) -> bool:
    """True when the row's score could depend on the differing component.

    `embed_calls > 0` is direct evidence. `unknown` or any non-text rerank mode
    is treated as used: a missing measurement is not proof of inertness.
    """
    try:
        calls = int(runtime.get("embed_calls"))
    except (TypeError, ValueError):
        return True
    if calls > 0:
        return True
    modes = runtime.get("rerank_modes") or []
    return any(str(mode) not in _INERT_RERANK_MODES for mode in modes)


def _runtime_conflict(rows: list[dict]) -> str | None:
    """Refuse a capture whose rows disagree on runtime provenance.

    A text-only run (0 embedder calls, `sqlite_fts5`) may differ in the daemon
    that happened to be up; that difference cannot move the score, so it is
    allowed. The moment a row used the component, the two rows are not
    comparable and the capture is refused instead of averaged.
    """
    if not rows:
        return None

    incomplete = []
    for row in rows:
        if not _runtime_complete(row.get("runtime")):
            incomplete.append(str(row.get("id")))
    if incomplete:
        return f"{len(incomplete)} capture rows have no complete runtime stamp: {incomplete[:3]}"

    variants = {json.dumps(row["runtime"], sort_keys=True, ensure_ascii=False) for row in rows}
    if len(variants) <= 1:
        return None
    if any(_runtime_used(row["runtime"]) for row in rows):
        return (
            f"capture mixes runtime provenance ({len(variants)} variants) and the "
            "differing component was used"
        )
    return None


def check_capture_before_run(
    rows: list[dict],
    done: set[str],
    panel_ids: list[str],
    *,
    rev: str,
    corpus_head: str,
    allow_replay: bool = False,
    allow_mixed: bool = False,
) -> tuple[int, int, str | None]:
    """Refuse a capture that cannot describe this panel or this product.

    Returns `(executed, resumed, refusal)`. The caller prints the counters: a
    score is only trustworthy next to the number of tasks this run executed.
    `rev`/`corpus_head` are the provenance of *this* run; a row that carries a
    different one came from another product or another corpus, and mixing them
    is the E74 bug at a smaller scale (found by red-teaming the counter guard).
    `runtime` is the third provenance: rows may differ in the daemon that was
    up, but only a row with `embed_calls=0` and a text rerank mode can call that
    difference inert.
    """
    panel = set(panel_ids)
    executed = len(panel - done)
    resumed = len(rows)
    foreign = sorted({row["id"] for row in rows} - panel)
    if foreign:
        return executed, resumed, f"{len(foreign)} capture rows are not in this panel: {foreign[:3]}"
    if not allow_mixed:
        stale_rev = [row["id"] for row in rows if str(row.get("rev")) != rev]
        if stale_rev:
            return executed, resumed, (
                f"{len(stale_rev)} capture rows came from another revision "
                f"(this run is {rev[:12]}): {stale_rev[:2]}"
            )
        stale_corpus = [row["id"] for row in rows if str(row.get("corpus_head")) != corpus_head]
        if stale_corpus:
            return executed, resumed, (
                f"{len(stale_corpus)} capture rows came from another corpus "
                f"(this corpus is {corpus_head}): {stale_corpus[:2]}"
            )
        runtime_refusal = _runtime_conflict(rows)
        if runtime_refusal:
            return executed, resumed, runtime_refusal
    if executed == 0 and panel and not allow_replay:
        return executed, resumed, "0 tasks executed: this is a replay, pass --allow-replay to score it"
    return executed, resumed, None


def check_denominator_after_run(rows: list[dict], panel_ids: list[str]) -> str | None:
    """Refuse to write a score whose denominator is not the panel."""
    missing = sorted(set(panel_ids) - {row["id"] for row in rows})
    if missing:
        return f"{len(missing)} panel tasks have no row: {missing[:3]}"
    return None
