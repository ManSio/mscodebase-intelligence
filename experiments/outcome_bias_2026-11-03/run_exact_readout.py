"""E-OUTCOME-5: exact readout.

Local model: expected blame from token logprobs (0-9, single digit token).
Hosted model: binary liability (YES/NO) because OpenRouter returns logprobs: null.

Run both arms, write raw JSONL, print metrics. T10: exit 2 on zero parsed reads.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import readout  # noqa: E402
from prompts import binary_prompt, binary_system_prompt, question_tail, system_prompt  # noqa: E402

LOCAL_MODEL = "qwen2.5-3b-instruct"
LOCAL_URL = "http://localhost:1234/v1/chat/completions"
HOSTED_MODEL = "z-ai/glm-4.7-flash"
HOSTED_URL = "https://openrouter.ai/api/v1/chat/completions"
TRIALS = 5


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = ROOT.parent.parent / ".env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_stories() -> list[dict]:
    return [json.loads(l) for l in (ROOT / "frozen" / "STORIES.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def cells_for(stories: list[dict]) -> list[dict]:
    out: list[dict] = []
    for s in stories:
        name = s["name"]
        if s["group"] == "outcome":
            out.append({"case": s["id"], "variant": "no_harm", "body": s["base"] + " " + s["no_harm"], "name": name})
            out.append({"case": s["id"], "variant": "harm", "body": s["base"] + " " + s["harm"], "name": name})
        elif s["group"] == "action_severity":
            out.append({"case": s["id"], "variant": "mild", "body": s["mild"] + " " + s["shared_outcome"], "name": name})
            out.append({"case": s["id"], "variant": "severe", "body": s["severe"] + " " + s["shared_outcome"], "name": name})
        elif s["group"] == "cosmetic":
            out.append({"case": s["id"], "variant": "a", "body": s["variant_a"], "name": name})
            out.append({"case": s["id"], "variant": "b", "body": s["variant_b"], "name": name})
    return out


def local_expected(httpx, cell: dict) -> dict:
    body = {
        "model": LOCAL_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt(9)},
            {"role": "user", "content": cell["body"] + question_tail(cell["name"], 9)},
        ],
        "temperature": 0,
        "max_tokens": 4,
        "logprobs": True,
        "top_logprobs": 10,
    }
    last = ""
    for attempt, topn in enumerate((10, 5, 5)):
        body["top_logprobs"] = topn
        try:
            r = httpx.post(LOCAL_URL, json=body, timeout=300)
            if r.status_code >= 400:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                time.sleep(1)
                continue
            data = r.json()
            ch = (data.get("choices") or [{}])[0]
            lp = ch.get("logprobs") or {}
            content = lp.get("content") or []
            top = (content[0] or {}).get("top_logprobs") if content else None
            if not top:
                return {"ok": False, "error": "no logprobs in response"}
            probs = readout.digit_probs_from_logprobs(top)
            if probs is None:
                return {"ok": False, "error": "no digit token in top_logprobs"}
            blame, mass = readout.expected_blame(probs)
            return {"ok": True, "blame": blame, "mass": mass, "probs": [round(p, 6) for p in probs],
                    "content": (ch.get("message") or {}).get("content")}
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(1)
    return {"ok": False, "error": last}


def hosted_binary(httpx, key: str, cell: dict, trial: int) -> dict:
    body = {
        "model": HOSTED_MODEL,
        "messages": [
            {"role": "system", "content": binary_system_prompt()},
            {"role": "user", "content": cell["body"] + binary_prompt(cell["name"])},
        ],
        "temperature": 0,
        "seed": 42,
        "max_tokens": 4,
        "reasoning": {"enabled": False},
    }
    try:
        r = httpx.post(HOSTED_URL, headers={"Authorization": f"Bearer {key}",
                                            "HTTP-Referer": "https://github.com/mscodebase",
                                            "X-Title": "MSCodeBase E-OUTCOME-5"}, json=body, timeout=120)
        if r.status_code >= 400:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        ch = (r.json().get("choices") or [{}])[0]
        content = (ch.get("message") or {}).get("content", "") or ""
        return {"ok": True, "yes": readout.parse_yes_no(content), "content": content}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def main() -> int:
    import httpx

    stories = load_stories()
    cells = cells_for(stories)
    if not cells:
        print("T10: no cells", file=sys.stderr)
        return 2
    key = load_env().get("OPENROUTER_API_KEY", "")
    if not key:
        print("ERROR: no OPENROUTER_API_KEY", file=sys.stderr)
        return 2

    # local exact
    local_raw = []
    print("=== local exact readout (logprobs) ===")
    for cell in cells:
        res = local_expected(httpx, cell)
        row = {"model": LOCAL_MODEL, "case": cell["case"], "variant": cell["variant"], **res}
        local_raw.append(row)
        print(f"  {cell['case']}/{cell['variant']}: ok={row.get('ok')} blame={row.get('blame')} mass={row.get('mass')}")
    (ROOT / "results" / "raw_e5_local.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in local_raw) + "\n", encoding="utf-8")

    # hosted binary
    hosted_raw = []
    print("\n=== hosted binary liability (YES/NO) ===")
    for cell in cells:
        for trial in range(TRIALS):
            res = hosted_binary(httpx, key, cell, trial)
            row = {"model": HOSTED_MODEL, "case": cell["case"], "variant": cell["variant"], "trial": trial, **res}
            hosted_raw.append(row)
            print(f"  {cell['case']}/{cell['variant']} t{trial}: ok={row.get('ok')} yes={row.get('yes')}")
    (ROOT / "results" / "raw_e5_hosted.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in hosted_raw) + "\n", encoding="utf-8")

    parsed_local = [r for r in local_raw if r.get("ok") and r.get("blame") is not None]
    parsed_hosted = [r for r in hosted_raw if r.get("ok") and r.get("yes") is not None]
    if not parsed_local or not parsed_hosted:
        print(f"T10: zero parsed reads (local={len(parsed_local)}, hosted={len(parsed_hosted)})", file=sys.stderr)
        return 2

    print("\n=== metrics ===")
    lmap = {(r["case"], r["variant"]): r for r in parsed_local}
    for s in stories:
        if s["group"] != "outcome":
            continue
        nh, hm = lmap.get((s["id"], "no_harm")), lmap.get((s["id"], "harm"))
        if nh and hm:
            print(f"  local leak {s['id']}: {round(hm['blame'] - nh['blame'], 3)} "
                  f"(mass {nh['mass']:.3f}/{hm['mass']:.3f})")
    nh, hm = lmap.get(("pos_control", "mild")), lmap.get(("pos_control", "severe"))
    if nh and hm:
        print(f"  local pos_gap: {round(hm['blame'] - nh['blame'], 3)}")
    a, b = lmap.get(("neg_control", "a")), lmap.get(("neg_control", "b"))
    if a and b:
        print(f"  local neg_delta: {round(a['blame'] - b['blame'], 3)}")

    agg: dict[tuple[str, str], list[bool]] = {}
    for r in parsed_hosted:
        agg.setdefault((r["case"], r["variant"]), []).append(bool(r["yes"]))
    for s in stories:
        if s["group"] != "outcome":
            continue
        nh, hm = agg.get((s["id"], "no_harm")), agg.get((s["id"], "harm"))
        if nh and hm:
            print(f"  hosted YES rate {s['id']}: no_harm={statistics.fmean(nh):.2f} harm={statistics.fmean(hm):.2f} "
                  f"delta={statistics.fmean(hm) - statistics.fmean(nh):+.2f}")
    nh, hm = agg.get(("pos_control", "mild")), agg.get(("pos_control", "severe"))
    if nh and hm:
        print(f"  hosted pos_gap: {statistics.fmean(hm) - statistics.fmean(nh):+.2f}")
    a, b = agg.get(("neg_control", "a")), agg.get(("neg_control", "b"))
    if a and b:
        print(f"  hosted neg_delta: {statistics.fmean(a) - statistics.fmean(b):+.2f}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
