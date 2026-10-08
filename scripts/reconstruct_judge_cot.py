#!/usr/bin/env python3
"""Backfill judge CoT from opencode.db (read-only) to qid-level artifact.

Recovers the judge reasoning/final-text lost by scripts/f5_judged_run.py
(which persisted only parsed verdicts). Trial-exact join is impossible
(opaque cand tokens lost, cand_*.txt deleted) -> granularity is QUERY (qid).

Usage:
    python scripts/reconstruct_judge_cot.py --out experiments/4A_unit_of_return/results/f5judged/judged_cot_backfill.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import traceback
from pathlib import Path

if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
WORKDIR = "D:/Project/MSCodeBase/experiments/4A_unit_of_return/results/f5judged/work"
FROZEN = ROOT / "experiments" / "4A_unit_of_return" / "frozen" / "f5" / "queries.jsonl"

try:  # both invocation shapes: `python scripts/x.py` and import-by-path in tests
    from scripts.judge_verdict import VERDICT_RE, parse_verdict as _parse_verdict
except ImportError:  # pragma: no cover
    from judge_verdict import VERDICT_RE, parse_verdict as _parse_verdict


def _norm(s: str) -> str:
    return " ".join((s or "").split())


# Verdict parsing used to live here as a FIRST-match substring scan, which
# inverted self-correcting judges. The contract and its measurement now live in
# scripts/judge_verdict.py, shared with f5_judged_run.py.


def _split_prompt(user_text: str) -> tuple[str, str]:
    """Extract (question, reference) from the single-line judge prompt."""
    t = _norm(user_text)
    mq = re.search(r"Question:\s*(.*)", t)
    if not mq:
        return "", ""
    rest = mq.group(1)
    mr = re.search(r"Reference answer:\s*(.*)$", rest)
    if mr:
        return rest[: mr.start()].strip(), mr.group(1).strip()
    return rest.strip(), ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out", default="experiments/4A_unit_of_return/results/f5judged/judged_cot_backfill.json")
    args = ap.parse_args()

    frozen = [_norm_q(q) for q in (_load_jsonl(FROZEN))]
    by_question = {_norm(q["question"]): q for q in frozen}
    by_id = {q["id"]: q for q in frozen}

    con = sqlite3.connect("file:" + args.db + "?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row

    # Negative control A: reader sessions must NOT match the judge filter.
    n_reader_probe = con.execute(
        "SELECT COUNT(*) FROM session WHERE directory=?", (WORKDIR,)
    ).fetchone()[0]

    sess_rows = list(
        con.execute(
            """SELECT s.id, s.time_created FROM session s WHERE s.directory=?
               AND EXISTS (SELECT 1 FROM message m JOIN part p ON p.message_id=m.id
                           WHERE m.session_id=s.id AND p.data LIKE '%grading an answer%')
               ORDER BY s.time_created""",
            (WORKDIR,),
        )
    )

    sessions_out: list[dict] = []
    unmatched = 0
    for srow in sess_rows:
        sid = srow["id"]
        user_text, reasoning, final_text, model = "", "", "", ""
        for m in con.execute("SELECT id, data FROM message WHERE session_id=?", (sid,)):
            try:
                d = json.loads(m[1])
            except json.JSONDecodeError:
                continue
            if d.get("role") == "user":
                for p in con.execute("SELECT data FROM part WHERE message_id=?", (m[0],)):
                    try:
                        pd = json.loads(p[0])
                    except json.JSONDecodeError:
                        continue
                    if pd.get("type") == "text" and not pd.get("synthetic"):
                        if "grading an answer" in (pd.get("text") or ""):
                            user_text = pd.get("text") or ""
            elif d.get("role") == "assistant":
                model = model or d.get("modelID", "")
                for p in con.execute("SELECT data FROM part WHERE message_id=?", (m[0],)):
                    try:
                        pd = json.loads(p[0])
                    except json.JSONDecodeError:
                        continue
                    if pd.get("type") == "reasoning":
                        reasoning += pd.get("text") or ""
                    elif pd.get("type") == "text" and not pd.get("synthetic"):
                        final_text += pd.get("text") or ""
        # Negative control B: every kept session MUST carry the judge prompt.
        if "grading an answer" not in user_text:
            unmatched += 1
            continue
        question, reference = _split_prompt(user_text)
        q = by_question.get(_norm(question))
        qid = q["id"] if q else ""
        if not qid:
            unmatched += 1
        verdict_final = _parse_verdict(final_text)
        mentions = sorted({w.lower() for w in VERDICT_RE.findall(reasoning)})
        final_in_reasoning = verdict_final in mentions
        other = [w for w in mentions if w != verdict_final]
        sessions_out.append(
            {
                "session_id": sid,
                "time_created": srow["time_created"],
                "qid": qid,
                "question": question,
                "reference": reference,
                "model": model,
                "verdict_final": verdict_final,
                "reasoning_mentions": mentions,
                "has_flip": bool(other) and final_in_reasoning,
                "multi_mention": len(mentions) >= 2,
                "reasoning_len": len(reasoning),
                "final_text": final_text,
                "cot_text": reasoning,
            }
        )

    by_q: dict[str, list[dict]] = {}
    for s in sessions_out:
        by_q.setdefault(s["qid"] or "UNMATCHED", []).append(s)
    queries = []
    for qid in sorted(by_q):
        ss = by_q[qid]
        queries.append(
            {
                "qid": qid,
                "n_sessions": len(ss),
                "n_multi_mention": sum(1 for s in ss if s["multi_mention"]),
                "n_flip": sum(1 for s in ss if s["has_flip"]),
                "verdicts": {v: sum(1 for s in ss if s["verdict_final"] == v) for v in ("correct", "incorrect", "uncertain")},
                "sessions": [{k: s[k] for k in ("session_id", "time_created", "model", "verdict_final", "reasoning_mentions", "has_flip", "multi_mention", "reasoning_len", "final_text", "cot_text")} for s in ss],
            }
        )

    out = {
        "config": {"workdir": WORKDIR, "frozen": str(FROZEN), "n_sessions_total": n_reader_probe,
                   "n_judge_sessions": len(sess_rows), "n_unmatched": unmatched},
        "queries": queries,
    }
    out_path = Path(args.out)
    if not str(out_path).startswith(str(ROOT)) and not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    print(f"sessions_in_workdir={n_reader_probe} judge_sessions={len(sess_rows)} "
          f"kept={len(sessions_out)} unmatched={unmatched}")
    print(f"qid_groups={len(queries)} sha256={sha}")
    print(f"-> {out_path}")
    return 0


def _norm_q(q: dict) -> dict:
    return q


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
