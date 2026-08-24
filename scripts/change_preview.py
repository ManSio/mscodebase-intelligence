#!/usr/bin/env python
"""
change_preview.py — «внести изменение и точно знать, что будет» (Фаза 2).

Берёт незакоммиченный diff рабочего дерева, применяет его в изолированный
git worktree, прогоняет ровно affected-тесты (Фаза 1: src/core/test_impact.py)
+ затронутые гейты (architecture_linter / check_layer_boundaries / ruff) и
возвращает вердикт ДО коммита в рабочую ветку.

Вердикты — та же трёхзначная модель, что в action_receipt.py (ТЗ §11.4):
  VERIFIED       — CHANGE WOULD PASS (всё зелёное в изоляторе)
  REFUTED        — CHANGE WOULD FAIL (список упавших тестов/гейтов)
  INCONCLUSIVE   — не удалось выполнить (нет git/сети/таймаут/нет изменений
                   в отслеживаемых файлах — untracked не применяются)

Использование:
    python scripts/change_preview.py              # diff HEAD..рабочее дерево
    python scripts/change_preview.py --base main   # diff main..рабочее дерево

Exit code: 0 = VERIFIED, 1 = REFUTED, 2 = INCONCLUSIVE.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import List, Optional

# ENCODING SAFETY (Windows §5.9): cp1251-консоль падает на юникод-выводе
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# Дефолтный кап на прогон тестов/гейтов в изоляторе (сек)
DEFAULT_TIMEOUT = 300
_MAX_REPORT_LINES = 15


def _run(cmd: List[str], cwd: Path, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    """Popen + communicate (§5.16: не capture_output — pipe-deadlock на Windows)."""
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


class ChangePreview:
    """Изолированный превью-прогон незакоммиченного изменения."""

    def __init__(self, repo: Path, base: str, timeout: int = DEFAULT_TIMEOUT):
        self.repo = repo
        self.base = base
        self.timeout = timeout
        self._worktree: Optional[Path] = None

    # ─── Main flow ──────────────────────────────────────────
    def run(self) -> tuple[str, str]:
        changed = self._changed_files()
        if not changed:
            return "INCONCLUSIVE", "нет изменений отслеживаемых файлов (untracked не применяются)"
        if not self._make_worktree():
            return "INCONCLUSIVE", "не удалось создать изолированный worktree"
        try:
            failures = self._apply_and_verify(changed)
        finally:
            self._cleanup()
        if not failures:
            return "VERIFIED", f"CHANGE WOULD PASS ({len(changed)} файлов, изолятор зелёный)"
        return "REFUTED", "CHANGE WOULD FAIL:\n" + "\n".join(failures)

    # ─── Steps ─────────────────────────────────────────────
    def _changed_files(self) -> List[str]:
        res = _git(self.repo, "diff", "--name-only", self.base)
        if res.returncode != 0:
            return []
        return [ln for ln in (res.stdout or "").splitlines() if ln.strip()]

    def _make_worktree(self) -> bool:
        tmp = Path(tempfile.mkdtemp(prefix="mscodebase_preview_")).resolve()
        res = _git(self.repo, "worktree", "add", "--detach", str(tmp), self.base)
        if res.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            print(f"  ⚠️ worktree add failed: {res.stdout.strip()[:300]}")
            return False
        self._worktree = tmp
        return True

    def _apply_and_verify(self, changed: List[str]) -> List[str]:
        wt = self._worktree
        assert wt is not None

        # diff HEAD..worktree в рабочем дереве → применяем в изолятор
        patch = _git(self.repo, "diff", self.base)
        if patch.returncode != 0:
            return ["patch creation failed"]
        patch_text = patch.stdout or ""
        if not patch_text.strip():
            return []  # diff пуст по факту (например, только untracked)

        # Применяем через файл (надёжнее пайпов на Windows, §5.16)
        patch_file = wt / ".preview.patch"
        try:
            patch_file.write_text(patch_text, encoding="utf-8")
            check = _run(["git", "apply", "--check", str(patch_file)], wt, timeout=60)
            if check.returncode != 0:
                return [f"patch --check failed: {(check.stdout or '').strip()[:300]}"]
            apply = _run(["git", "apply", str(patch_file)], wt, timeout=60)
            if apply.returncode != 0:
                return [f"patch apply failed: {(apply.stdout or '').strip()[:300]}"]
        finally:
            try:
                patch_file.unlink()
            except OSError:
                pass

        failures: List[str] = []
        sys.path.insert(0, str(wt))
        try:
            # — тесты —
            from src.core.test_impact import affected_gates, predict_affected_tests

            pred = predict_affected_tests(changed, str(wt))
            affected = pred["affected_tests"]
            if affected:
                print(f"  🧪 affected tests ({len(affected)}): {', '.join(affected)}")
                res = _run(
                    [sys.executable, "-m", "pytest", *affected, "-q", "--no-header"],
                    wt,
                    timeout=self.timeout,
                )
                if res.returncode != 0:
                    failures.append(self._summarize_pytest(res.stdout or "", affected))
                else:
                    print("  🧪 affected tests: PASSED")
            else:
                print("  🧪 affected tests: не найдено (проверьте связку symbol→tests)")

            # — гейты —
            for gate in affected_gates(changed, str(wt)):
                script = {
                    "architecture_linter": "scripts/architecture_linter.py",
                    "check_layer_boundaries": "scripts/check_layer_boundaries.py",
                }.get(gate)
                if script and (wt / script).exists():
                    res = _run([sys.executable, script], wt, timeout=120)
                    status = "PASSED" if res.returncode == 0 else "FAILED"
                    if res.returncode != 0:
                        failures.append(f"[{gate}] Failed (exit {res.returncode})")
                    print(f"  🔒 {gate}: {status}")
                elif gate == "ruff":
                    res = _run(
                        [sys.executable, "-m", "ruff", "check", "src/", "tests/"],
                        wt,
                        timeout=120,
                    )
                    status = "PASSED" if res.returncode == 0 else "FAILED"
                    if res.returncode != 0:
                        failures.append("[ruff] Failed")
                    print(f"  🔒 ruff: {status}")
        finally:
            sys.path.pop(0)
        return failures

    def _summarize_pytest(self, out: str, affected: List[str]) -> str:
        lines = [ln for ln in (out or "").splitlines() if ln.strip()]
        failed = [ln for ln in lines if "FAILED" in ln or "failed" in ln]
        tail = failed or lines[-_MAX_REPORT_LINES:]
        body = "\n".join(f"    {ln}" for ln in tail[-_MAX_REPORT_LINES:])
        return f"[pytest] FAILED ({len(affected)} affected):\n{body}"

    def _cleanup(self) -> None:
        if self._worktree is not None:
            _git(self.repo, "worktree", "remove", "--force", str(self._worktree))
            shutil.rmtree(self._worktree, ignore_errors=True)
        # удаляем осиротевшие .preview.patch, если остались
        try:
            for p in self.repo.glob("*.preview.patch"):
                p.unlink()
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="HEAD", help="база диффа (по умолчанию HEAD)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--repo", default=None, help="корень репозитория (авто-детект по умолчанию)")
    args = parser.parse_args()

    try:
        repo = Path(args.repo).resolve() if args.repo else Path.cwd().resolve()
        toplevel = _git(repo, "rev-parse", "--show-toplevel")
        if toplevel.returncode != 0:
            print("INCONCLUSIVE: не git-репозиторий")
            return 2
        repo = Path((toplevel.stdout or "").strip()).resolve()

        preview = ChangePreview(repo, args.base, timeout=args.timeout)
        verdict, message = preview.run()
        print(f"\n=== CHANGE PREVIEW VERDICT: {verdict} ===\n{message}" if verdict else message)
        print(f"\nVerdict: {verdict}")
        return {"VERIFIED": 0, "REFUTED": 1, "INCONCLUSIVE": 2}[verdict]
    except Exception:  # noqa: BLE001 — вершина CLI: traceback + INCONCLUSIVE
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())