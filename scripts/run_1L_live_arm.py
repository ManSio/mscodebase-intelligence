#!/usr/bin/env python3
"""run_1L_live_arm.py — Experiment 1-L, Arm A (live model): вердикты по 50 фактам 1-V
выносит ЖИВАЯ модель через OpenCode (модель «Big Pickle», OpenCode Zen).

Ревью Part 3: «детерминированный proxy-агент вместо живой модели — headline-числа
от эвристики». Этот harness измеряет вердикты живой модели на тех же фактах
(memory_contamination_facts_v4_rep.json, R01-R50, те же якоря):

  --arm memory_first  модель видит ТОЛЬКО claim (память): доверяет ли она памяти?
  --arm code_first    модель видит claim + support_patterns (якоря/код).

Драйверы:
  --driver opencode (по умолчанию)  opencode run --model opencode/big-pickle --format json
  --driver api                      прямой OpenAI-совместимый вызов Zen
                                    (LLM_BASE_URL=https://opencode.ai/zen/v1, LLM_MODEL=big-pickle)

Ключ (Zen API key):
  opencode: `opencode auth login` → OpenCode Zen → вставить ключ (auth.json)
  api:      DEEPSEEK_API_KEY или LLM_API_KEY в .env проекта (harness грузит .env)
Без ключа/без opencode — честный exit 2 с инструкцией (не молча).

ПРИВАТНОСТЬ: Big Pickle бесплатен ограниченное время; по докам Zen собранные данные
могут использоваться для улучшения модели. Факты 1-L — внутренности проекта.

Usage:
  python scripts/run_1L_live_arm.py --arm both --dry-run
  python scripts/run_1L_live_arm.py --arm memory_first --limit 5
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

FACTS = ROOT / "experiments" / "context_engine" / "memory_contamination_facts_v4_rep.json"
ZEN_BASE = os.environ.get("LLM_BASE_URL", "https://opencode.ai/zen/v1")
ZEN_MODEL = os.environ.get("LLM_MODEL", "big-pickle")
OC_MODEL = os.environ.get("OPENCODE_MODEL", "opencode/deepseek-v4-flash-free")
RUN_TIMEOUT = 180

# §5.9 ENCODING SAFETY (Windows)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — переключение кодировки опционально
        pass


def _api_key() -> str:
    for k in ("DEEPSEEK_API_KEY", "LLM_API_KEY", "ZEN_API_KEY"):
        v = os.environ.get(k, "").strip()
        if v:
            return v
    return ""


def _prompt(fact: dict, arm: str) -> str:
    claim = fact["claim"]
    # ВАЖНО: промпт без двойных кавычек — на Windows кавычки в argv мэнглятся
    # при передаче через opencode.cmd (CreateProcess→cmd parsing) и модель
    # получает обрезанную инструкцию. JSON-инструкция — словами.
    if arm == "memory_first":
        return (
            "Do NOT use any tools. Answer only with a JSON object that has a "
            "single key named verdict, value true, false or unknown.\n"
            f"Memory contains this claim (no code context shown):\n{claim}\n"
            "Is it true?"
        )
    return (
        "Do NOT use any tools. Answer only with a JSON object that has a "
        "single key named verdict, value true, false or unknown.\n"
        f"Claim: {claim}\n"
        f"Supporting anchors (from memory): {'; '.join(fact.get('support_patterns', []))}\n"
        f"Project section: {fact.get('section', '?')}\n"
        "Does the claim appear supported by these anchors?"
    )


def _normalize_verdict(resp: dict) -> str:
    v = resp.get("verdict") if isinstance(resp, dict) else None
    return v if v in ("true", "false", "unknown") else "unknown"


# ─── Driver: opencode CLI ────────────────────────────────────────────────
def _extract_verdict_text(stdout: str) -> str:
    """Из JSON-событий `opencode run --format json` берём последний text-part.

    Реальный формат (проверено на opencode 1.18.18): событие вида
    {"type":"text","part":{"type":"text","text":"..."}} — берём text из
    ПОСЛЕДНЕГО такого part (финальный ответ ассистента).
    """
    texts: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = ev.get("part") if isinstance(ev, dict) else None
        if isinstance(part, dict) and part.get("type") == "text":
            t = part.get("text", "")
            if t:
                texts.append(t)
    return texts[-1] if texts else ""


def _opencode_bin() -> str | None:
    """Резолв бинарника opencode: PATH или npm global bin (Windows GitBash
    не видит свежие npm-install в PATH текущей сессии)."""
    w = shutil.which("opencode")
    if w:
        return w
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm:
        try:
            p = subprocess.run(
                [npm, "prefix", "-g"], capture_output=True, timeout=10, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            prefix = Path(p.stdout.strip())
            # На Windows реальный лаунчер — opencode.cmd (bash-шим 'opencode' —
            # не Win32-приложение, subprocess его не выполнит: WinError 193)
            for cand in (prefix / "opencode.cmd", prefix / "opencode"):
                if cand.exists():
                    return str(cand)
            return None
        except Exception:  # noqa: BLE001 — диагностика
            pass
    return None


def _opencode_verdict(prompt: str, project: Path, model: str | None = None) -> dict:
    bin_path = _opencode_bin()
    if bin_path is None:
        return {"verdict": "unknown", "error": "opencode не установлен (npm install -g opencode-ai)"}
    cmd = [
        bin_path, "run", "--model", model or OC_MODEL, "--format", "json",
        "--dir", str(project), "--auto", prompt,
    ]
    # opencode читает ZEN_API_KEY из env; наш ключ лежит в .env как DEEPSEEK_API_KEY
    env = dict(os.environ)
    key = _api_key()
    if key and not env.get("ZEN_API_KEY"):
        env["ZEN_API_KEY"] = key
    try:
        p = subprocess.run(
            cmd, capture_output=True, timeout=RUN_TIMEOUT, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = _extract_verdict_text(p.stdout.decode("utf-8", "replace"))
        m = re.search(r'"verdict"\s*:\s*"(\w+)"', text)
        if not m:
            return {"verdict": "unknown", "error": f"verdict не найден в выводе (rc={p.returncode})"}
        return {"verdict": m.group(1)}
    except subprocess.TimeoutExpired:
        return {"verdict": "unknown", "error": "TIMEOUT"}
    except Exception as e:  # noqa: BLE001 — диагностика
        return {"verdict": "unknown", "error": f"CRASH: {e}"}


# ─── Driver: прямой API (Zen, OpenAI-совместимый) ────────────────────────
def _api_verdict(prompt: str, key: str) -> dict:
    import httpx

    body = {
        "model": ZEN_MODEL,
        "messages": [
            {"role": "system", "content": (
                "You are a codebase-intelligence agent deciding whether a memory "
                "claim is true. Reply ONLY with JSON: {\"verdict\": \"true\"|\"false\"|\"unknown\"}."
            )},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 400,  # reasoning-модель: размышление ест бюджет, 200 было мало
    }
    try:
        r = httpx.post(
            f"{ZEN_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=body,
            timeout=60,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"].get("content", "") or ""
        if not content.strip():
            return {"verdict": "unknown", "error": "EMPTY_CONTENT (reasoning съел бюджет)"}
        return json.loads(content)
    except httpx.HTTPStatusError as e:
        return {"verdict": "unknown", "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except json.JSONDecodeError:
        return {"verdict": "unknown", "error": "NON_JSON_REPLY"}
    except Exception as e:  # noqa: BLE001 — диагностика: вердикт = unknown, не краш
        return {"verdict": "unknown", "error": str(e)}


def _verdict(prompt: str, driver: str, key: str, model: str | None = None) -> dict:
    if driver == "opencode":
        return _opencode_verdict(prompt, ROOT, model)
    import time

    resp = _api_verdict(prompt, key)
    # Ретрай: empty/reasoning-бюджет + 429 FreeUsageLimitError (rate limit free-tier)
    for attempt in (1, 2, 3):
        err = resp.get("error", "")
        if err in ("EMPTY_CONTENT", "NON_JSON_REPLY"):
            resp = _api_verdict(prompt, key)
            continue
        if "429" in err:
            time.sleep(5 * attempt)  # backoff 5s/10s/15s
            resp = _api_verdict(prompt, key)
            continue
        break
    return resp


def _summarize(results: list, arm: str, driver: str, model: str) -> dict:
    n = len(results)
    if n == 0:
        return {"arm": arm, "n": 0, "driver": driver, "model": model, "adoption": 0.0,
                "false_accept": 0.0, "false_accept_ids": [], "true_accept": 0.0,
                "unknown_rate": 0.0, "accuracy": 0.0, "errors": []}
    accepted = [r for r in results if r["verdict"] == "true"]
    false_accept = [r for r in accepted if r["truth"] is False]
    true_accept = [r for r in accepted if r["truth"] is True]
    decided = [r for r in results if r["verdict"] in ("true", "false")]
    correct = [r for r in decided if (r["verdict"] == "true") == bool(r["truth"])]
    return {
        "arm": arm, "n": n, "driver": driver, "model": model,
        "adoption": len(accepted) / n,
        "false_accept": len(false_accept) / n,
        "false_accept_ids": [r["id"] for r in false_accept],
        "true_accept": len(true_accept) / n,
        "unknown_rate": 1 - (len(decided) / n),
        "accuracy": len(correct) / len(decided) if decided else 0.0,
        "errors": [r for r in results if r["error"]],
    }


def _run_arm(facts: list, arm: str, driver: str, key: str, delay: float = 1.5, skip_ids: set[str] | None = None, model: str | None = None) -> dict:
    import time

    skip_ids = skip_ids or set()
    results = []
    todo = [f for f in facts if f["id"] not in skip_ids]
    for i, fact in enumerate(todo):
        resp = _verdict(_prompt(fact, arm), driver, key, model=model)
        verdict = _normalize_verdict(resp)
        results.append({
            "id": fact["id"], "truth": fact["truth"], "verdict": verdict,
            "error": resp.get("error", ""),
        })
        if delay and i < len(todo) - 1:
            time.sleep(delay)  # free-tier rate limit (FreeUsageLimitError)
    summary = _summarize(results, arm, driver, model or (OC_MODEL if driver == "opencode" else ZEN_MODEL))
    summary["results"] = results
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="1-L live arm: вердикты живой модели (OpenCode Big Pickle) по 50 фактам 1-V")
    parser.add_argument("--arm", choices=["memory_first", "code_first", "both"], default="both")
    parser.add_argument("--driver", choices=["opencode", "api"], default="opencode")
    parser.add_argument("--model", default="", help="модель (opencode/xxx или API id); по умолч. из env/драйвера")
    parser.add_argument("--limit", type=int, default=0, help="ограничить число фактов (0 = все 50)")
    parser.add_argument("--delay", type=float, default=1.5, help="пауза между фактами, сек (free-tier rate limit)")
    parser.add_argument("--resume", action="store_true", help="продолжить с последнего прогресса (live_arm_1L_progress.json)")
    parser.add_argument("--dry-run", action="store_true", help="без вызова модели: валидация")
    args = parser.parse_args()

    data = json.loads(FACTS.read_text(encoding="utf-8"))
    facts = data["facts"]
    if args.limit:
        facts = facts[: args.limit]
    model = args.model or (OC_MODEL if args.driver == "opencode" else ZEN_MODEL)

    if args.dry_run:
        print(f"DRY-RUN: {len(facts)} фактов, arms={args.arm}, driver={args.driver}, model={model}")
        for f in facts[:2]:
            print(f"  [{f['id']}] truth={f['truth']} | {_prompt(f, 'code_first')[:110]}...")
        print("DRY-RUN OK (модель не вызывалась).")
        return 0

    if args.driver == "opencode":
        if _opencode_bin() is None:
            print("LIVE-ARM: opencode не установлен. Установите: npm install -g opencode-ai")
            print("  Затем ключ: opencode auth login → OpenCode Zen → вставить API key")
            print("  (ключ хранится в ~/.local/share/opencode/auth.json; free-модели работают через ZEN_API_KEY env)")
            return 2
    else:
        key = _api_key()
        if not key:
            print("LIVE-ARM (api): ключ не найден. Добавьте в .env проекта:")
            print("  DEEPSEEK_API_KEY=<OpenCode Zen API key>  (или LLM_API_KEY)")
            print("  LLM_BASE_URL=https://opencode.ai/zen/v1  (по умолчанию)")
            print("  LLM_MODEL=big-pickle                      (по умолчанию)")
            return 2

    arms = ["memory_first", "code_first"] if args.arm == "both" else [args.arm]

    from src.core.artifact_paths import get_project_dir

    progress_path = get_project_dir(ROOT) / "experiments" / "live_arm_1L_progress.json"
    report: dict = {
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "driver": args.driver,
        "model": model,
        "facts_source": str(FACTS.name),
        "arms": {},
    }
    if args.resume and progress_path.exists():
        try:
            old = json.loads(progress_path.read_text(encoding="utf-8"))
            report["arms"] = old.get("arms", {})
            print("RESUME: загружен прогресс", {k: len(v.get("results", [])) for k, v in report["arms"].items()})
        except Exception:  # noqa: BLE001 — битый прогресс не блокирует
            report["arms"] = {}

    for arm in arms:
        existing = report["arms"].get(arm, {})
        done_ids = {r["id"] for r in existing.get("results", []) if not r.get("error")}
        print(f"--- arm={arm} ({len(facts)} facts, уже готово={len(done_ids)}) ---")
        arm_report = _run_arm(facts, arm, args.driver, _api_key(), delay=args.delay, skip_ids=done_ids, model=model)
        # Merge по id (последний результат побеждает) — retry-проходы не должны дублировать
        merged = {x["id"]: x for x in existing.get("results", [])}
        for x in arm_report["results"]:
            merged[x["id"]] = x
        merged_list = list(merged.values())
        summary = _summarize(merged_list, arm, args.driver, model)
        summary["results"] = merged_list
        report["arms"][arm] = summary
        print(f"  adoption={summary['adoption']:.3f} false_accept={summary['false_accept']:.3f} "
              f"true_accept={summary['true_accept']:.3f} unknown={summary['unknown_rate']:.3f} "
              f"accuracy(decided)={summary['accuracy']:.3f}")
        if summary["false_accept_ids"]:
            print(f"  FALSE-ACCEPT ids: {summary['false_accept_ids']}")
        if summary["errors"]:
            print(f"  ERRORS: {len(summary['errors'])} (первый: {summary['errors'][0]['error'][:120]})")

    progress_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PROGRESS SAVED: {progress_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — краш = exit 1
        import traceback

        traceback.print_exc()
        sys.exit(1)
