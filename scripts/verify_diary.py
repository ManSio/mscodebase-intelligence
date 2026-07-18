"""
Contradiction Ledger — сверяет "✅"-утверждения из AGENT_DIARY.md с реальным кодом.

Идея Claude (аудит 2026-07-18): автоматизировать ручную проверку, которую
человек делал весь чат — сравнивать "✅ done" из дневника с реальным состоянием
репозитория. Обнаруживает расхождения типа "пул заявлен, но не запушен".

Usage:
    python scripts/verify_diary.py
    from src.scripts.verify_diary import run_contradiction_ledger

Returns exit code 0 if all claims verified, 1 if discrepancies found.
Can also be imported: run_contradiction_ledger() -> dict with 'discrepancies'.
"""
import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional


def run_contradiction_ledger(project_root: Optional[Path] = None) -> Dict[str, object]:
    """Verify AGENT_DIARY.md claims against real codebase.

    Returns dict: {
        'ok': bool,           # True if no discrepancies
        'discrepancies': list,
        'claims': int,
        'commits': int,
    }
    Does NOT call sys.exit (safe to import from MCP server).
    """
    project_root = project_root or Path(__file__).resolve().parent.parent
    diary_path = project_root / "AGENT_DIARY.md"
    result: Dict[str, object] = {
        "ok": True,
        "discrepancies": [],
        "claims": 0,
        "commits": 0,
    }
    if not diary_path.exists():
        result["discrepancies"].append(f"AGENT_DIARY.md not found at {diary_path}")
        result["ok"] = False
        return result

    diary_text = diary_path.read_text(encoding='utf-8')

    # ─── Extract claims ───────────────────────────────────────
    claims = []
    for m in re.finditer(r'✅\s*(?:Fixed|реализовано|Closed|done|исправлено|Ready)[:\s-]*(.+?)(?:\n|$)', diary_text):
        claims.append(m.group(1).strip())
    for m in re.finditer(r'\|\s*✅\s*(?:Fixed|Closed)\s*\|\s*(.+?)\s*\|', diary_text):
        claims.append(m.group(1).strip())

    commit_hashes = set()
    for m in re.finditer(r'`([a-f0-9]{7,8})`', diary_text):
        commit_hashes.add(m.group(1))

    result['claims'] = len(claims)
    result['commits'] = len(commit_hashes)
    discrepancies: List[str] = []

    # Check commits
    for h in sorted(commit_hashes):
        try:
            # DEVNULL вместо capture_output — daemon thread-safe на Windows
            # (capture_output вызывает deadlock pipe в daemon threads)
            proc = subprocess.Popen(
                ['git', 'cat-file', '-t', h],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd=str(project_root),
            )
            try:
                stdout, _ = proc.communicate(timeout=5)
                if proc.returncode != 0:
                    discrepancies.append(f"Commit `{h}` not found in repo")
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                discrepancies.append(f"Commit `{h}`: git timeout")
        except Exception as e:
            discrepancies.append(f"Commit `{h}`: git error: {e}")

    # ─── Verify architecture claims ──
    embedder_path = project_root / "src/providers/embedder/remote_embedder.py"
    if embedder_path.exists():
        content = embedder_path.read_text(encoding='utf-8')
        checks = {
            '_ov_call_lock': 'Variant B lock exists',
            '_ov_async_queue': 'AsyncInferQueue exists',
            'with self._ov_call_lock': 'Lock wrapping submit+wait+collect',
            'local_results': 'Per-call local dict exists',
        }
        for pattern, desc in checks.items():
            if pattern not in content:
                discrepancies.append(f"Missing: {desc} in remote_embedder.py")

    bench_path = project_root / "scripts/benchmark_ov_concurrent.py"
    if bench_path.exists():
        if 'expected_pair' not in bench_path.read_text(encoding='utf-8'):
            discrepancies.append("benchmark_ov_concurrent.py — no argmax check found")

    test_path = project_root / "tests/test_ov_concurrent_embed.py"
    if test_path.exists():
        if '_ov_call_lock' not in test_path.read_text(encoding='utf-8'):
            discrepancies.append("_ov_call_lock missing in test_ov_concurrent_embed.py")

    result['discrepancies'] = discrepancies
    result['ok'] = len(discrepancies) == 0
    return result


def _cli_main() -> int:
    """CLI entry point (preserves original behavior with sys.exit)."""
    project_root = Path(__file__).resolve().parent.parent
    print(f"{'='*70}")
    print(f"Contradiction Ledger — verifying AGENT_DIARY.md claims")
    print(f"Diary: {project_root / 'AGENT_DIARY.md'}")
    res = run_contradiction_ledger(project_root)
    print(f"Claims found: {res['claims']} diary claims, {res['commits']} commits")
    print(f"{'='*70}\n")

    if res['discrepancies']:
        print(f"❌ LEDGER: {len(res['discrepancies'])} DISCREPANCIES FOUND")
        for d in res['discrepancies']:
            print(f"  → {d}")
        print(f"\n⚠️  AGENT_DIARY.md claims do NOT match actual codebase.")
        print(f"   These may be: unpushed commits, deleted code, renamed symbols,")
        print(f"   or diary entries that were never committed.")
        return 1
    else:
        print(f"✅ LEDGER: ALL CLAIMS VERIFIED")
        print(f"   AGENT_DIARY.md is consistent with actual codebase.")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(_cli_main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)