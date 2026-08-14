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
OC_MODEL = os.environ.get("OPENCODE_MODEL", "opencode/big-pickle")
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
    if arm == "memory_first":
        return (
            "Do NOT use any tools. Answer only with JSON.\n"
            f"Memory contains this claim (no code context shown):\n\"{claim}\"\n"
            "Is it true? Reply {\"verdict\": \"true\"|\"false\"|\"unknown\"}."
        )
    return (
        "Do NOT use any tools. Answer only with JSON.\n"
        f"Claim: \"{claim}\"\n"
        f"Supporting anchors (from memory): {json.dumps(fact.get('support_patterns', []), ensure_ascii=False)}\n"
        f"Project section: {fact.get('section', '?')}\n"
        "Does the claim appear supported by these anchors? Reply {\"verdict\": ...}."
    )


def _normalize_verdict(resp: dict) -> str:
    v = resp.get("verdict") if isinstance(resp, dict) else None
    return v if v in ("true", "false", "unknown") else "unknown"


# ─── Driver: opencode CLI ────────────────────────────────────────────────
def _extract_verdict_text(stdout: str) -> str:
    """Из JSON-событий opencode run --format json берём последний текст ассистента.

    Формат событий opencode: JSON-объект на строку (type/message). Парсинг
    дефензивный: собираем весь ассистентский текст, берём последний фрагмент
    (среда opencode не установлена в этой сессии — парсер требует проверки
    на реальном выводе после установки; fallback — regex по "verdict").
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
        msg = ev.get("message") if isinstance(ev, dict) else None
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            texts.append(
                "".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
            )
    return texts[-1] if texts else ""


def _opencode_verdict(prompt: str, project: Path) -> dict:
    cmd = [
        "opencode", "run", "--model", OC_MODEL, "--format", "json",
        "--dir", str(project), "--auto", prompt,
    ]
    try:
        p = subprocess.run(
            cmd, capture_output=True, timeout=RUN_TIMEOUT,
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
        "max_tokens": 200,
    }
    try:
        r = httpx.post(
            f"{ZEN_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=body,
            timeout=60,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except httpx.HTTPStatusError as e:
        return {"verdict": "unknown", "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:  # noqa: BLE001 — диагностика: вердикт = unknown, не краш
        return {"verdict": "unknown", "error": str(e)}


def _verdict(prompt: str, driver: str, key: str) -> dict:
    if driver == "opencode":
        return _opencode_verdict(prompt, ROOT)
    return _api_verdict(prompt, key)


def _run_arm(facts: list, arm: str, driver: str, key: str) -> dict:
    results = []
    for fact in facts:
        resp = _verdict(_prompt(fact, arm), driver, key)
        verdict = _normalize_verdict(resp)
        results.append({
            "id": fact["id"], "truth": fact["truth"], "verdict": verdict,
            "error": resp.get("error", ""),
        })
    n = len(results)
    accepted = [r for r in results if r["verdict"] == "true"]
    false_accept = [r for r in accepted if r["truth"] is False]
    true_accept = [r for r in accepted if r["truth"] is True]
    correct = [r for r in results if (r["verdict"] == "true") == bool(r["truth"])]
    return {
        "arm": arm, "n": n, "driver": driver,
        "model": OC_MODEL if driver == "opencode" else ZEN_MODEL,
        "adoption": len(accepted) / n if n else 0.0,
        "false_accept": len(false_accept) / n if n else 0.0,
        "false_accept_ids": [r["id"] for r in false_accept],
        "true_accept": len(true_accept) / n if n else 0.0,
        "accuracy": len(correct) / n if n else 0.0,
        "errors": [r for r in results if r["error"]],
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="1-L live arm: вердикты живой модели (OpenCode Big Pickle) по 50 фактам 1-V")
    parser.add_argument("--arm", choices=["memory_first", "code_first", "both"], default="both")
    parser.add_argument("--driver", choices=["opencode", "api"], default="opencode")
    parser.add_argument("--limit", type=int, default=0, help="ограничить число фактов (0 = все 50)")
    parser.add_argument("--dry-run", action="store_true", help="без вызова модели: валидация")
    args = parser.parse_args()

    data = json.loads(FACTS.read_text(encoding="utf-8"))
    facts = data["facts"]
    if args.limit:
        facts = facts[: args.limit]

    if args.dry_run:
        print(f"DRY-RUN: {len(facts)} фактов, arms={args.arm}, driver={args.driver}, "
              f"model={OC_MODEL if args.driver == 'opencode' else ZEN_MODEL}")
        for f in facts[:2]:
            print(f"  [{f['id']}] truth={f['truth']} | {_prompt(f, 'code_first')[:110]}...")
        print("DRY-RUN OK (модель не вызывалась).")
        return 0

    if args.driver == "opencode":
        if shutil.which("opencode") is None:
            print("LIVE-ARM: opencode не установлен. Установите: npm install -g opencode-ai")
            print("  Затем ключ: opencode auth login → OpenCode Zen → вставить API key")
            print("  (ключ хранится в ~/.local/share/opencode/auth.json; для Big Pickle ключ обязателен, модель бесплатна)")
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
    report = {
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "driver": args.driver,
        "model": OC_MODEL if args.driver == "opencode" else ZEN_MODEL,
        "facts_source": str(FACTS.name),
        "arms": {},
    }
    for arm in arms:
        print(f"--- arm={arm} ({len(facts)} facts) ---")
        arm_report = _run_arm(facts, arm, args.driver, _api_key())
        report["arms"][arm] = {k: v for k, v in arm_report.items() if k != "results"}
        print(f"  adoption={arm_report['adoption']:.3f} false_accept={arm_report['false_accept']:.3f} "
              f"true_accept={arm_report['true_accept']:.3f} accuracy={arm_report['accuracy']:.3f}")
        if arm_report["false_accept_ids"]:
            print(f"  FALSE-ACCEPT ids: {arm_report['false_accept_ids']}")
        if arm_report["errors"]:
            print(f"  ERRORS: {len(arm_report['errors'])} (первый: {arm_report['errors'][0]['error'][:120]})")

    from src.core.artifact_paths import get_project_dir

    out = get_project_dir(ROOT) / "experiments" / f"live_arm_{datetime.now(timezone.utc):%Y%m%d}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SAVED: {out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — краш = exit 1
        import traceback

        traceback.print_exc()
        sys.exit(1)
