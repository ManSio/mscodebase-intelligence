"""Probe a model and refuse to call it usable without an answer in time.

"No expected duration means no silence looks wrong" (Tīrtha catalogue): a
provider that errors does not always exit — the CLI can hang for minutes. A
model is usable only if it answered within the budget.

    python probe_model.py --model opencode-go/minimax-m3.1-flash-free
    python probe_model.py --model tirtha/auto --timeout 60
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

WORK = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Temp" / "opencode" / "model-probe"
PROMPT = "Reply with the single word OK."


def find_binary() -> str | None:
    appdata = os.environ.get("APPDATA")
    candidates = []
    if appdata:
        candidates.append(Path(appdata) / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe")
    candidates.append(Path.home() / ".opencode" / "bin" / "opencode.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    from shutil import which

    return which("opencode")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    binary = find_binary()
    if not binary:
        print(json.dumps({"model": args.model, "verdict": "NO_BINARY"}))
        return 2

    WORK.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    verdict = "UNKNOWN"
    output = ""
    try:
        proc = subprocess.run(
            [binary, "run", PROMPT, "--model", args.model],
            cwd=str(WORK),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
        )
        elapsed = round(time.monotonic() - started, 1)
        output = (proc.stdout or "")[-800:]
        if "OK" in output:
            verdict = "USABLE"
        else:
            verdict = "NO_ANSWER"
    except subprocess.TimeoutExpired:
        elapsed = round(time.monotonic() - started, 1)
        verdict = "TIMEOUT"
    except Exception as exc:  # noqa: BLE001
        elapsed = round(time.monotonic() - started, 1)
        verdict = f"ERROR:{type(exc).__name__}"

    record = {
        "model": args.model,
        "verdict": verdict,
        "elapsed_s": elapsed,
        "budget_s": args.timeout,
        "output_tail": output.strip()[-200:],
    }
    if args.json:
        print(json.dumps(record, ensure_ascii=False))
    else:
        print(f"{args.model}: {verdict} in {elapsed}s (budget {args.timeout}s)")
        if output.strip():
            print("  tail:", output.strip()[-120:].replace("\n", " "))
    return 0 if verdict == "USABLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
