"""Code Mode experiment: cost and recall of three delivery mechanisms.

Arms (frozen in frozen/HYPOTHESES.md):
  A  three sequential tools/call -> full client-visible payloads
  C  the SAME three results, projected by code (same data, only the projection differs)
  B  one composite tool: investigate(query)

No model in the loop: the projection is hand-written, so this measures the cost of
the CONTRACT, not the model's skill at writing scripts.

Run:
  python experiments/code_mode_2026_11/scripts/run_experiment.py
Output: results/arms.json, results/SUMMARY.json (raw, unedited).
"""
from __future__ import annotations

import contextlib
import gzip
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import tiktoken
except ModuleNotFoundError:  # experiment-only dependency, deliberately not in pyproject
    sys.stderr.write(
        "run_experiment.py needs tiktoken for token counts: pip install tiktoken\n"
        "(the project does not depend on it; this is a measurement-only dependency)\n"
    )
    raise SystemExit(2)

REPO = Path(__file__).resolve().parents[3]
FROZEN = REPO / "experiments" / "code_mode_2026_11" / "frozen" / "QUERIES.jsonl"
OUT = REPO / "experiments" / "code_mode_2026_11" / "results"
PY = os.path.join(
    os.environ["LOCALAPPDATA"],
    "Zed", "extensions", "mscodebase-intelligence", "venv", "Scripts", "python.exe",
)
ENC = tiktoken.get_encoding("cl100k_base")
INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
               "clientInfo": {"name": "codemode-exp", "version": "1"}},
}

PATH_RE = re.compile(r"(?:[A-Za-z]:)?[\\/]?(?:src|tests|scripts|docs|tools|adapters)"
                     r"[\\/][\w./\\-]+?\.(?:py|md|json|toml|sh|ps1)")
KEY_RE = re.compile(r"defs|callers|callees|Definition|risk|affected|line", re.I)
RAW_DIR = OUT / "raw_texts"


def toks(text: str) -> int:
    return len(ENC.encode(text))


def read_msg(stream, timeout: float):
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = stream.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


class Client:
    """Minimal MCP stdio client (initialize + tools/call)."""

    def __init__(self) -> None:
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(REPO), "PROJECT_PATH": str(REPO), "PYTHONUTF8": "1",
            "LOG_LEVEL": "ERROR", "MSCODEBASE_MCP_PROFILE": "core",
        })
        self._err: list[str] = []
        self.calls = 0
        with contextlib.nullcontext(str(REPO)) as cwd:
            self.proc = subprocess.Popen(
                [PY, "-u", "-m", "src.main"], cwd=cwd, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
        threading.Thread(target=self._drain, daemon=True).start()
        self.proc.stdin.write(json.dumps(INITIALIZE) + "\n")
        self.proc.stdin.flush()
        if not read_msg(self.proc.stdout, 300):
            raise RuntimeError("server did not initialize: " + " | ".join(self._err[-5:]))
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )

    def _drain(self) -> None:
        for line in iter(self.proc.stderr.readline, ""):
            self._err.append(line.rstrip())

    def call(self, name: str, args: dict) -> tuple[str, float]:
        """Returns (tool text, ms). Text is what the client hands to the model."""
        self.calls += 1
        t0 = time.time()
        req = {"jsonrpc": "2.0", "id": 1000 + self.calls, "method": "tools/call",
               "params": {"name": name, "arguments": args}}
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        resp = read_msg(self.proc.stdout, 300)
        dt = (time.time() - t0) * 1000
        if not resp:
            return "", dt
        text = ""
        try:
            for block in resp["result"].get("content", []):
                text += block.get("text", "")
        except (KeyError, TypeError):
            text = json.dumps(resp, ensure_ascii=False)
        return text, dt

    def close(self) -> None:
        try:
            self.proc.kill()
            self.proc.wait(timeout=30)
        except OSError:
            pass


def project(raw_texts: list[str]) -> str:
    """Code projection: keep only path-bearing / fact-bearing lines, dedupe."""
    seen: list[str] = []
    for text in raw_texts:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if PATH_RE.search(line) or KEY_RE.search(line):
                if line not in seen:
                    seen.append(line)
    return "\n".join(seen)


def _first_path(text: str) -> Path | None:
    """First code/doc path a reader would take from a tool answer (no gold peeking)."""
    m = re.search(r"([A-Za-z]:[\\/][^\s`*)\]]+|(?:src|tests|scripts|tools|docs)[\\/][^\s`*)\]]+)"
                  r"\.(?:py|md)", text)
    if not m:
        return None
    return Path(m.group(0).strip("`*,;:"))


def _path_char(ch: str) -> bool:
    """True if `ch` can be part of a path segment (so a match touching it is not whole)."""
    return bool(ch) and (ch.isalnum() or ch in "_./-\\")


def hit(text: str, gold: str) -> bool:
    """Substring match with path boundaries.

    Normalises separators, strips the repo root (an absolute path under the repo
    is a legitimate mention), then requires the match to be a whole path segment.
    Without this, ``tests/src/core/x.py`` and ``src/core/x.py.bak`` count as hits.
    """
    flat = text.replace("\\", "/").lower()
    for prefix in (str(REPO).replace("\\", "/").lower(), "./"):
        flat = flat.replace(prefix + "/", "").replace(prefix, "")
    target = gold.replace("\\", "/").lower()
    start = 0
    while True:
        i = flat.find(target, start)
        if i < 0:
            return False
        before = flat[i - 1] if i > 0 else ""
        after = flat[i + len(target)] if i + len(target) < len(flat) else ""
        if not _path_char(before) and not _path_char(after):
            return True
        start = i + 1


def main() -> int:
    queries = [json.loads(line) for line in FROZEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    client = Client()
    # Run metadata: without it the `hit` column cannot be told apart from a
    # different index state. Captured before the first tool call.
    meta = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO),
                                   capture_output=True, text=True).stdout.strip(),
        "git_dirty": bool(subprocess.run(["git", "status", "--porcelain"], cwd=str(REPO),
                                         capture_output=True, text=True).stdout.strip()),
        "index_status": client.call("codebase", {"action": "index", "path": "status"})[0][:2000],
        "python": PY,
        "tokenizer": "cl100k_base",
    }
    rows = []
    raw_dump = {}
    try:
        for i, q in enumerate(queries, 1):
            gold = q["gold_file"]
            # --- arm A (+ raw for arm C): the naive agent squeezes each answer for
            # the next step instead of being handed the gold name. The symbol the
            # follow-up calls use is whatever path the search answer printed FIRST.
            ms_a = 0.0
            raws = []
            search_text, dt = client.call("search_code", {"query": q["query"], "mode": "quality"})
            raws.append(search_text)
            ms_a += dt
            first = _first_path(search_text)
            if first is not None:
                for name, args in (
                    ("get_symbol_info", {"query": first.stem}),
                    ("impact_analysis", {"symbol": first.stem}),
                ):
                    text, dt = client.call(name, args)
                    raws.append(text)
                    ms_a += dt
            arm_a = "\n\n".join(raws)
            arm_c = project(raws)
            # --- arm B: composite (its own defaults)
            arm_b, ms_b = client.call("investigate", {"query": q["query"]})
            raw_dump[q["id"]] = {"A": arm_a, "C": arm_c, "B": arm_b,
                                 "A_first_path": str(first) if first else None}
            rows.append({
                "id": q["id"], "gold": gold, "first_path": str(first) if first else None,
                "A": {"tokens": toks(arm_a), "chars": len(arm_a), "hit": hit(arm_a, gold), "ms": round(ms_a)},
                # C makes the same three calls as A in one program: wall clock is identical
                # by construction, so it is recorded as null, not as a second measurement.
                "C": {"tokens": toks(arm_c), "chars": len(arm_c), "hit": hit(arm_c, gold), "ms": None},
                "B": {"tokens": toks(arm_b), "chars": len(arm_b), "hit": hit(arm_b, gold), "ms": round(ms_b)},
            })
            print(f"[{i:2d}/{len(queries)}] {q['id']} A={rows[-1]['A']['tokens']}tok/"
                  f"{'hit' if rows[-1]['A']['hit'] else 'miss'} C={rows[-1]['C']['tokens']}tok/"
                  f"{'hit' if rows[-1]['C']['hit'] else 'miss'} B={rows[-1]['B']['tokens']}tok/"
                  f"{'hit' if rows[-1]['B']['hit'] else 'miss'}", flush=True)
    finally:
        client.close()

    # --- control that must be able to fail: the scorer is checked on synthetic
    # positives/negatives BEFORE its numbers are trusted. Boundary cases are the
    # ones a naive substring match gets wrong (see the 2026-11-15 audit).
    control = scorer_control(rows)
    summary = summarise(rows, control)
    meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with gzip.open(RAW_DIR / "arm_texts.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(raw_dump, fh, ensure_ascii=False)
    (OUT / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "arms.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


def scorer_control(rows: list[dict]) -> dict:
    g = rows[0]["gold"]
    control = {
        "positive_full_path": hit(f"Definition: {g} line 12", g),
        "positive_absolute_path": hit(f"Definition: {REPO}\\{g.replace('/', chr(92))}", g),
        "positive_bare_at_start": hit(g, g),
        "positive_backslash_variant": hit(f"Definition: {g.replace('/', chr(92))} line 12", g),
        "positive_dot_slash": hit(f"Definition: ./{g} line 12", g),
        "positive_uppercase": hit(f"Definition: {g.upper()} line 12", g),
        "negative_spurious_segment": hit(f"Definition: {g.replace('/', '/__zz__/')}", g),
        "negative_basename_only": hit(f"Definition: {Path(g).name} line 12", g),
        "negative_other_dir_prefix": hit(f"tests/{g}", g),
        "negative_suffix_extension": hit(f"{g}.bak", g),
    }
    assert control["positive_full_path"] is True, control
    assert control["positive_absolute_path"] is True, control
    assert control["positive_bare_at_start"] is True, control
    assert control["positive_backslash_variant"] is True, control
    assert control["negative_spurious_segment"] is False, control
    assert control["negative_basename_only"] is False, control
    assert control["negative_other_dir_prefix"] is False, control
    assert control["negative_suffix_extension"] is False, control
    return control


def summarise(rows: list[dict], control: dict) -> dict:
    return {
        "population": len(rows),
        "arms": ["A", "C", "B"],
        "median_tokens": {arm: median([r[arm]["tokens"] for r in rows]) for arm in "ACB"},
        "median_ms": {arm: median([r[arm]["ms"] for r in rows if r[arm]["ms"] is not None])
                      for arm in "ACB"},
        "ms_measured": {arm: any(r[arm]["ms"] is not None for r in rows) for arm in "ACB"},
        "hit_rate": {arm: round(sum(r[arm]["hit"] for r in rows) / len(rows), 3) for arm in "ACB"},
        "C_tokens_over_A_median": round(
            median([r["C"]["tokens"] / r["A"]["tokens"] for r in rows if r["A"]["tokens"]]), 3
        ),
        "C_lost_gold_where_A_had_it": [r["id"] for r in rows if r["A"]["hit"] and not r["C"]["hit"]],
        "B_lost_gold_where_A_had_it": [r["id"] for r in rows if r["A"]["hit"] and not r["B"]["hit"]],
        "C_over_800": [r["id"] for r in rows if r["C"]["tokens"] > 800],
        "C_over_1000": [r["id"] for r in rows if r["C"]["tokens"] > 1000],
        "A_first_path_is_gold": {
            "count": sum(1 for r in rows if r.get("first_path", "").replace("\\", "/").lower()
                         .endswith(r["gold"].replace("\\", "/").lower())),
            "of": len(rows),
            "note": "the naive follow-up step used the first path printed by search, "
                    "never the gold name (audit 2026-11-15, blocker 2)",
        },
        "control_scorer": control,
        "raw_texts": "results/raw_texts/arm_texts.json.gz",
        "run_meta": "results/run_meta.json",
    }


def median(values: list[float]) -> float | None:
    if not values:
        return None  # not measured, never 0.0 (a 0 would enter medians as a real value)
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def resummarise() -> int:
    """Rebuild SUMMARY.json from arms.json with the same code path as main()."""
    rows = json.loads((OUT / "arms.json").read_text(encoding="utf-8"))
    summary = summarise(rows, scorer_control(rows))
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    if "--resummarise" in sys.argv:
        raise SystemExit(resummarise())
    raise SystemExit(main())
