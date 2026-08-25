#!/usr/bin/env python
"""
lock_guard.py — git-based файловые лока для параллельных агентов.

Протокол (multi-agent-coordination §10): каждый лок — отдельный ЗАКОММИЧЕННЫЙ
файл .locks/<resource_id>.lock; атомарность гарантирует git (два параллельных
push на один путь невозможны без предварительного pull — гонка видима).

Команды:
  status                       — активные лока (возраст, stale-предупреждение)
  acquire <resource> <purpose> — создать + закоммитить + запушить лок
  release <resource>           — снять лок (git rm + commit + push)

Примеры:
  python scripts/lock_guard.py acquire src/core/search/engine.py "FTS5 rework"
  python scripts/lock_guard.py status
  python scripts/lock_guard.py release src/core/search/engine.py

Exit: 0 — ok (status всегда 0 — advisory); 1 — ошибка/чужой лок.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ENCODING SAFETY (Windows §5.9)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

LOCKS_DIR = Path(__file__).resolve().parent.parent / ".locks"
STALE_HOURS = 2


def _run(cmd: List[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout or "")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return _run(["git", "--no-pager", *args], cwd)


def _repo() -> Optional[Path]:
    res = _run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    if res.returncode != 0:
        return None
    return Path(res.stdout.strip()).resolve()


def _resource_id(resource: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", resource).strip("_") + ".lock"


def _whoami(repo: Path) -> str:
    res = _git(repo, "config", "user.name")
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip()
    return "unknown-agent"


def cmd_status(repo: Path) -> int:
    LOCKS_DIR.mkdir(exist_ok=True)
    locks = sorted(LOCKS_DIR.glob("*.lock"))
    if not locks:
        print("🔓 Активных локов нет.")
        return 0
    now = datetime.now(timezone.utc)
    for lp in locks:
        data = _read_lock(lp)
        if not data:
            print(f"⚠️ {lp.name}: не JSON — проверить вручную")
            continue
        acquired = _parse_ts(data.get("acquired_at", ""))
        age_h = (now - acquired).total_seconds() / 3600 if acquired else None
        stale = age_h is not None and age_h > STALE_HOURS
        stamp = f"{age_h:.1f}ч" if age_h is not None else "?"
        line = (f"🔒 {lp.name} — {data.get('agent')} · {stamp} · "
                f"{data.get('purpose', '')[:60]} ({data.get('resource')})")
        if stale and not _has_activity(repo, data.get("resource", "")):
            line += "  ⚠️ STALE (>2ч без коммитов) — можно снять с причиной"
        print(line)
    return 0


def cmd_acquire(repo: Path, resource: str, purpose: str) -> int:
    if not resource:
        print("❌ resource обязателен")
        return 1
    LOCKS_DIR.mkdir(exist_ok=True)
    lock_path = LOCKS_DIR / _resource_id(resource)
    if lock_path.exists():
        data = _read_lock(lock_path) or {}
        print(f"❌ Лок уже существует: {data.get('agent')} — "
              f"«{data.get('purpose')}». Подождать или взять другой файл (§10.2).")
        return 1
    agent = _whoami(repo)
    payload = {
        "resource": resource,
        "agent": agent,
        "acquired_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": purpose,
        "estimated_duration_min": 30,
    }
    lock_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    add = _git(repo, "add", str(lock_path))
    if add.returncode != 0:
        print(f"❌ git add failed: {add.stdout.strip()[:200]}")
        return 1
    commit = _git(
        repo,
        "commit",
        "-m",
        f"lock: {resource} by {agent} ({purpose})",
    )
    if commit.returncode != 0:
        print(f"❌ commit failed (hook?): {commit.stdout.strip()[:300]}")
        return 1
    push = _git(repo, "push")
    if push.returncode != 0:
        print("⚠️ push отклонён — возможно, лока конкурируют. См. §10.2 "
              "(`git pull`, прочитать чужие .locks/*.lock, подождать).")
        return 1
    print(f"✅ Лок захвачен и запушен: {lock_path.name}")
    return 0


def cmd_release(repo: Path, resource: str) -> int:
    lock_path = LOCKS_DIR / _resource_id(resource)
    if not lock_path.exists():
        print(f"ℹ️ Лока нет: {lock_path.name}")
        return 0
    data = _read_lock(lock_path) or {}
    agent = _whoami(repo)
    owner = data.get("agent")
    if owner and owner != agent:
        print(f"❌ Лок чужой ({owner}) — снимать только по §10.4 (stale) с причиной.")
        return 1
    rm = _git(repo, "rm", str(lock_path))
    if rm.returncode != 0:
        print(f"❌ git rm failed: {rm.stdout.strip()[:200]}")
        return 1
    commit = _git(repo, "commit", "-m", f"unlock: {resource} ({purpose_short(data)})")
    if commit.returncode != 0:
        print(f"❌ commit failed: {commit.stdout.strip()[:300]}")
        return 1
    push = _git(repo, "push")
    if push.returncode != 0:
        print("⚠️ push отклонён — лок снят локально, запушить позже.")
        return 0
    print(f"✅ Лок снят: {lock_path.name}")
    return 0


def _read_lock(path: Path) -> Optional[Dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _parse_ts(iso: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(iso)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _has_activity(repo: Path, resource: str) -> bool:
    if not resource:
        return False
    res = _git(repo, "log", "--all", "--oneline", "-5", "--", resource)
    return bool(res.stdout.strip())


def purpose_short(data: Dict) -> str:
    return str(data.get("purpose", ""))[:60] or "done"


def main() -> int:
    parser = argparse.ArgumentParser(prog="lock_guard", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    p_acquire = sub.add_parser("acquire")
    p_acquire.add_argument("resource")
    p_acquire.add_argument("purpose", nargs="?", default="")
    p_release = sub.add_parser("release")
    p_release.add_argument("resource")
    args = parser.parse_args()

    repo = _repo()
    if repo is None:
        print("❌ Не git-репозиторий")
        return 1

    if args.command == "acquire":
        return cmd_acquire(repo, args.resource, args.purpose)
    if args.command == "release":
        return cmd_release(repo, args.resource)
    return cmd_status(repo)


if __name__ == "__main__":
    sys.exit(main())
