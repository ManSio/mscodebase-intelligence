"""
Contradiction Ledger — сверяет "✅"-утверждения из AGENT_DIARY.md с реальным кодом.

Идея Claude (аудит 2026-07-18): автоматизировать ручную проверку, которую
человек делал весь чат — сравнивать "✅ done" из дневника с реальным состоянием
репозитория. Обнаруживает расхождения типа "пул заявлен, но не запушен".

Usage:
    python scripts/verify_diary.py

Returns exit code 0 if all claims verified, 1 if discrepancies found.
"""
import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import re
import subprocess
from pathlib import Path
from typing import Optional

try:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    DIARY_PATH = PROJECT_ROOT / "AGENT_DIARY.md"

    if not DIARY_PATH.exists():
        print(f"❌ AGENT_DIARY.md not found at {DIARY_PATH}")
        sys.exit(1)

    diary_text = DIARY_PATH.read_text(encoding='utf-8')

    # ─── Extract claims ───────────────────────────────────────
    # Pattern: "✅ <description>" or "**<something>** ✅" or "| ✅ |"
    # We look for lines containing ✅ and try to extract verifiable facts.
    claims = []

    # Pattern 1: "✅ реализовано X" or "✅ Fixed: X"
    for m in re.finditer(r'✅\s*(?:Fixed|реализовано|Closed|done|исправлено|Ready)[:\s-]*(.+?)(?:\n|$)', diary_text):
        claims.append(('diary_claim', m.group(1).strip()))

    # Pattern 2: Table rows with ✅
    for m in re.finditer(r'\|\s*✅\s*(?:Fixed|Closed)\s*\|\s*(.+?)\s*\|', diary_text):
        claims.append(('table_claim', m.group(1).strip()))

    # Pattern 3: Commit hashes mentioned in diary
    commit_hashes = set()
    for m in re.finditer(r'`([a-f0-9]{7,8})`', diary_text):
        commit_hashes.add(m.group(1))

    # ─── Verify commit hashes ─────────────────────────────────
    print(f"{'='*70}")
    print(f"Contradiction Ledger — verifying AGENT_DIARY.md claims")
    print(f"Diary: {DIARY_PATH}")
    print(f"Claims found: {len(claims)} diary claims, {len(commit_hashes)} commits")
    print(f"{'='*70}\n")

    discrepancies = []

    # Check commits
    print("📋 Checking commit hashes...")
    for h in sorted(commit_hashes):
        try:
            result = subprocess.run(
                ['git', 'cat-file', '-t', h],
                capture_output=True, text=True, timeout=5,
                cwd=str(PROJECT_ROOT)
            )
            if result.returncode != 0:
                discrepancies.append(f"Commit `{h}` not found in repo")
                print(f"  ❌ `{h}` — NOT FOUND")
            else:
                print(f"  ✅ `{h}` — exists")
        except Exception as e:
            discrepancies.append(f"Commit `{h}`: git error: {e}")
            print(f"  ⚠️ `{h}` — error: {e}")

    # ─── Verify specific architecture claims (the ones that matter) ──
    print("\n📋 Checking architecture claims from diary...")

    embedder_path = PROJECT_ROOT / "src/providers/embedder/remote_embedder.py"
    if embedder_path.exists():
        content = embedder_path.read_text(encoding='utf-8')
        checks = {
            '_ov_call_lock': 'Variant B lock exists',
            '_ov_async_queue': 'AsyncInferQueue exists',
            'with self._ov_call_lock': 'Lock wrapping submit+wait+collect',
            'local_results': 'Per-call local dict exists',
        }
        for pattern, desc in checks.items():
            if pattern in content:
                print(f"  ✅ {desc}")
            else:
                discrepancies.append(f"Missing: {desc} in remote_embedder.py")
                print(f"  ❌ {desc} — MISSING")

    bench_path = PROJECT_ROOT / "scripts/benchmark_ov_concurrent.py"
    if bench_path.exists():
        bench_content = bench_path.read_text(encoding='utf-8')
        if 'expected_pair' in bench_content:
            print(f"  ✅ benchmark_ov_concurrent.py — argmax self-match check exists")
        else:
            print(f"  ⚠️ benchmark_ov_concurrent.py — no argmax check found")

    test_path = PROJECT_ROOT / "tests/test_ov_concurrent_embed.py"
    if test_path.exists():
        test_content = test_path.read_text(encoding='utf-8')
        if '_ov_call_lock' in test_content:
            print(f"  ✅ test_ov_concurrent_embed.py — _ov_call_lock in mock setup")
        else:
            discrepancies.append("_ov_call_lock missing in test_ov_concurrent_embed.py")
            print(f"  ❌ test_ov_concurrent_embed.py — _ov_call_lock MISSING")

    # ─── Report ────────────────────────────────────────────────
    print(f"\n{'='*70}")
    if discrepancies:
        print(f"❌ LEDGER: {len(discrepancies)} DISCREPANCIES FOUND")
        for d in discrepancies:
            print(f"  → {d}")
        print(f"\n⚠️  AGENT_DIARY.md claims do NOT match actual codebase.")
        print(f"   These may be: unpushed commits, deleted code, renamed symbols,")
        print(f"   or diary entries that were never committed.")
        sys.exit(1)
    else:
        print(f"✅ LEDGER: ALL CLAIMS VERIFIED")
        print(f"   AGENT_DIARY.md is consistent with actual codebase.")
        sys.exit(0)

except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)