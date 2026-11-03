"""E-OUTCOME-1 runner: outcome bias in model blame judgments.

Frozen design lives in frozen/. This script only executes it and writes raw output.
No tuning after seeing results. T10: exits 2 on empty input or zero parsed digits.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
FROZEN = ROOT / "frozen"
RESULTS = ROOT / "results"

BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_MODELS = ["qwen/qwen3.6-flash", "deepseek/deepseek-v4-flash", "z-ai/glm-4.7-flash"]
from prompts import question_tail, system_prompt  # noqa: E402  (same directory)


TRIALS = 5
TEMPERATURE = 0
SEED = 42
MAX_TOKENS = 24
# Reasoning models spend the whole budget on hidden reasoning and return content=null
# (verified in probe: finish_reason=length, reasoning_tokens=64). Disable it so the
# readout is the digit, not the reasoning trace.
REASONING_DISABLED = True


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    return load_env(ROOT.parent.parent / ".env").get("OPENROUTER_API_KEY", "").strip()


def ask(httpx, key: str, model: str, user: str, trial: int, *, base_url: str,
        system: str, max_tokens: int, timeout: float, send_reasoning: bool) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": TEMPERATURE,
        "seed": SEED,
        "max_tokens": max_tokens,
    }
    if send_reasoning:
        body["reasoning"] = {"enabled": False}
    last_err = ""
    for attempt in range(3):
        try:
            headers = {"HTTP-Referer": "https://github.com/mscodebase", "X-Title": "MSCodeBase E-OUTCOME-1"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            r = httpx.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=body,
                timeout=timeout,
            )
            if r.status_code >= 400:
                last_err = f"HTTP {r.status_code}: {r.text[:300]}"
                time.sleep(1.5 * (attempt + 1))
                continue
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message", {}) or {}).get("content", "") or ""
            return {
                "ok": True,
                "content": content,
                "finish_reason": choice.get("finish_reason"),
                "usage": data.get("usage", {}),
            }
        except Exception as e:  # noqa: BLE001 - diagnostics only
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (attempt + 1))
    return {"ok": False, "error": last_err}


def parse_digit(content: str, scale_max: int) -> int | None:
    if scale_max == 9:
        m = re.search(r"(?<!\d)([0-9])(?!\d)", content)
        return int(m.group(1)) if m else None
    m = re.search(r"(?<!\d)(\d{1,3})(?!\d)", content)
    if not m:
        return None
    value = int(m.group(1))
    return value if 0 <= value <= scale_max else None


def build_cases(stories: list[dict], scale_max: int = 9) -> list[dict]:
    cases: list[dict] = []
    for s in stories:
        name = s["name"]
        tail = question_tail(name, scale_max)
        if s["group"] == "outcome":
            cases.append({"case": s["id"], "group": "outcome", "variant": "no_harm", "text": s["base"] + " " + s["no_harm"] + tail})
            cases.append({"case": s["id"], "group": "outcome", "variant": "harm", "text": s["base"] + " " + s["harm"] + tail})
        elif s["group"] == "action_severity":
            cases.append({"case": s["id"], "group": "action_severity", "variant": "mild", "text": s["mild"] + " " + s["shared_outcome"] + tail})
            cases.append({"case": s["id"], "group": "action_severity", "variant": "severe", "text": s["severe"] + " " + s["shared_outcome"] + tail})
        elif s["group"] == "cosmetic":
            cases.append({"case": s["id"], "group": "cosmetic", "variant": "a", "text": s["variant_a"] + tail})
            cases.append({"case": s["id"], "group": "cosmetic", "variant": "b", "text": s["variant_b"] + tail})
    return cases


def aggregate(raw: list[dict]) -> dict:
    cells: dict[str, dict[str, list[int]]] = {}
    errors = 0
    empty = 0
    for row in raw:
        key_model = row["model"]
        cell = f"{row['case']}::{row['variant']}"
        cells.setdefault(key_model, {}).setdefault(cell, [])
        if not row.get("ok"):
            errors += 1
            continue
        d = row.get("digit")
        if d is None:
            empty += 1
            continue
        cells[key_model][cell].append(d)
    return {"cells": cells, "errors": errors, "empty": empty}


def mean(xs: list[int]) -> float | None:
    return round(statistics.fmean(xs), 3) if xs else None


def fmt(xs: list[int]) -> str:
    if not xs:
        return "n=0"
    return f"{mean(xs)} sd={round(statistics.pstdev(xs), 2)} n={len(xs)} vals={xs}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--trials", type=int, default=TRIALS)
    ap.add_argument("--scale", type=int, default=9)
    ap.add_argument("--tag", default="e1")
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--key", default="", help="empty = read OPENROUTER_API_KEY; menu: pass 'none' to send no auth")
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--no-reasoning-param", action="store_true")
    args = ap.parse_args()

    stories = [json.loads(line) for line in (FROZEN / "STORIES.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if not stories:
        print("T10: empty story set", file=sys.stderr)
        return 2

    if args.key == "none":
        key = ""
    elif args.key:
        key = args.key
    else:
        key = api_key()
    if not key and "localhost" not in args.base_url and "127.0.0.1" not in args.base_url:
        print("ERROR: no API key for non-local endpoint", file=sys.stderr)
        return 2

    import httpx

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    system = system_prompt(args.scale)
    ask_kw = dict(base_url=args.base_url, system=system, max_tokens=args.max_tokens,
                  timeout=args.timeout, send_reasoning=not args.no_reasoning_param)

    if args.probe:
        for m in models:
            res = ask(httpx, key, m, "Blame for reading a phone while driving, 0-9. One digit.", 0, **ask_kw)
            print(json.dumps({"model": m, "ok": res.get("ok"), "content": res.get("content"), "error": res.get("error")}, ensure_ascii=False))
        return 0

    cases = build_cases(stories, args.scale)
    if not cases:
        print("T10: no cases built", file=sys.stderr)
        return 2

    raw: list[dict] = []
    total = len(models) * len(cases) * args.trials
    done = 0
    for model in models:
        for case in cases:
            for trial in range(args.trials):
                res = ask(httpx, key, model, case["text"], trial, **ask_kw)
                digit = parse_digit(res.get("content", ""), args.scale) if res.get("ok") else None
                raw.append({
                    "model": model,
                    "case": case["case"],
                    "group": case["group"],
                    "variant": case["variant"],
                    "trial": trial,
                    "ok": res.get("ok", False),
                    "content": res.get("content"),
                    "digit": digit,
                    "finish_reason": res.get("finish_reason"),
                    "error": res.get("error"),
                    "usage": res.get("usage"),
                })
                done += 1
                print(f"[{done}/{total}] {model} {case['case']}/{case['variant']} t{trial} -> {digit}", flush=True)

    RESULTS.mkdir(parents=True, exist_ok=True)
    tag = args.tag
    (RESULTS / f"raw_{tag}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in raw) + "\n", encoding="utf-8")

    agg = aggregate(raw)
    parsed_total = sum(len(v) for cells in agg["cells"].values() for v in cells.values())
    if parsed_total == 0:
        print("T10: zero parsed digits — run is not interpretable", file=sys.stderr)
        return 2

    lines = ["# E-OUTCOME-1 — raw aggregation", "", f"Models: {', '.join(models)}", f"Calls: {len(raw)}, errors: {agg['errors']}, unparsed: {agg['empty']}", ""]
    verdict_rows = []
    for model in models:
        cells = agg["cells"].get(model, {})
        lines.append(f"## {model}")
        lines.append("")
        for cell in sorted(cells):
            lines.append(f"- {cell}: {fmt(cells[cell])}")
        lines.append("")
        leak = {}
        for s in stories:
            if s["group"] != "outcome":
                continue
            nh = cells.get(f"{s['id']}::no_harm", [])
            hm = cells.get(f"{s['id']}::harm", [])
            if nh and hm:
                leak[s["id"]] = round(statistics.fmean(hm) - statistics.fmean(nh), 3)
        pos_gap = None
        mild = cells.get("pos_control::mild", [])
        sev = cells.get("pos_control::severe", [])
        if mild and sev:
            pos_gap = round(statistics.fmean(sev) - statistics.fmean(mild), 3)
        neg_delta = None
        na = cells.get("neg_control::a", [])
        nb = cells.get("neg_control::b", [])
        if na and nb:
            neg_delta = round(statistics.fmean(na) - statistics.fmean(nb), 3)
        verdict_rows.append({"model": model, "leak": leak, "pos_gap": pos_gap, "neg_delta": neg_delta})
        lines.append(f"- **outcome leak** (harm - no_harm): {leak}")
        lines.append(f"- **positive control gap** (severe - mild, both harm): {pos_gap}")
        lines.append(f"- **negative control delta** (Elm vs Pine, same action+outcome): {neg_delta}")
        lines.append("")

    (RESULTS / f"aggregate_{tag}.json").write_text(json.dumps({"verdict_rows": verdict_rows, "cells": agg["cells"], "errors": agg["errors"], "empty": agg["empty"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS / f"SUMMARY_{tag}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n=== AGGREGATE ===")
    print(json.dumps(verdict_rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
