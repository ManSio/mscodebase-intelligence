"""change_preview.py (core) — «внести изменение и точно знать, что будет».

Фаза 2: незакоммиченный diff рабочего дерева применяется в изолированный
git worktree, гоняются ровно affected-тесты (src/core/test_impact.py) +
затронутые гейты, возвращается вердикт ДО коммита.

Трёхзначная модель вердиктов — как в action_receipt.py (ТЗ §11.4):
  VERIFIED       — CHANGE WOULD PASS (всё зелёное в изоляторе)
  REFUTED        — CHANGE WOULD FAIL (список упавших тестов/гейтов)
  INCONCLUSIVE   — не удалось выполнить (нет git/сети/таймаут/изменений нет)

Использование (тонкие обёртки):
  scripts/change_preview.py   — CLI
  src/mcp/tools/predict_tools.py — MCP-инструмент predict_change
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

__all__ = ["ChangePreview", "changed_files", "static_predict", "DEFAULT_TIMEOUT"]

DEFAULT_TIMEOUT = 300
_MAX_REPORT_LINES = 15


def _run(cmd: List[str], cwd: Path, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    """Popen + communicate (§5.16: не capture_output — pipe-deadlock на Windows).

    FileNotFoundError (бинарник не установлен, напр. ruff в clean-state без
    dev-экстр) → CompletedProcess(returncode=127) — вызывающий решает: skip.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, f"command not found: {cmd[0]}")
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    # stderr не теряем (git apply и др. пишут ОШИБКУ в stderr): на провале
    # добавляем её к сообщению — иначе диагностика пустая (2026-08-25).
    out = stdout or ""
    if proc.returncode != 0 and stderr and stderr.strip():
        out = out.rstrip() + "\n[stderr] " + (stderr or "").strip()
    return subprocess.CompletedProcess(cmd, proc.returncode, out)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return _run(["git", "--no-pager", *args], cwd)


def changed_files(repo: Path, base: str = "HEAD") -> List[str]:
    """Изменённые отслеживаемые файлы относительно base (пуст, если нет git)."""
    res = _git(repo, "diff", "--name-only", base)
    if res.returncode != 0:
        return []
    return [ln for ln in (res.stdout or "").splitlines() if ln.strip()]


def static_predict(repo: Path, base: str = "HEAD") -> Dict:
    """Фаза 1 (без прогона): изменённые файлы → affected-тесты + гейты + риск."""
    from src.core.test_impact import affected_gates, predict_affected_tests

    changed = changed_files(repo, base)
    if not changed:
        return {
            "changed": [],
            "targets": [],
            "affected_tests": [],
            "gates": [],
            "risk": "low",
            "note": "нет изменений отслеживаемых файлов (untracked не учитываются)",
        }
    pred = predict_affected_tests(changed, str(repo))
    return {
        "changed": changed,
        "targets": pred["targets"],
        "affected_tests": pred["affected_tests"],
        "gates": affected_gates(changed, str(repo)),
        "risk": pred["risk_level"],
    }


class ChangePreview:
    """Изолированный превью-прогон незакоммиченного изменения."""

    def __init__(self, repo: Path, base: str, timeout: int = DEFAULT_TIMEOUT):
        self.repo = repo
        self.base = base
        self.timeout = timeout
        self._worktree: Optional[Path] = None

    # ─── Main flow ──────────────────────────────────────────
    def run(self) -> tuple[str, str]:
        changed = changed_files(self.repo, self.base)
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

        patch = _git(self.repo, "diff", self.base)
        if patch.returncode != 0:
            return ["patch creation failed"]
        patch_text = patch.stdout or ""
        if not patch_text.strip():
            return []  # diff пуст по факту (например, только untracked)

        # Применяем через файл (надёжнее пайпов на Windows, §5.16)
        patch_file = wt / ".preview.patch"
        try:
            patch_file.write_text(patch_text, encoding="utf-8", newline="\n")
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
                    if res.returncode == 127:
                        print(f"  ⏭️ {gate}: интерпретатор недоступен (skip)")
                        continue
                    if res.returncode != 0:
                        failures.append(f"[{gate}] Failed (exit {res.returncode})")
                    print(f"  🔒 {gate}: {'PASSED' if res.returncode == 0 else 'FAILED'}")
                elif gate == "ruff":
                    res = _run(["ruff", "check", "src/", "tests/"], wt, timeout=120)
                    if res.returncode == 127:
                        # clean-state ставит только .[base] без dev-экстр — ruff может
                        # отсутствовать; это окружение, а не провал изменения
                        print("  ⏭️ ruff: не установлен (skip — окружение без dev-экстр)")
                        continue
                    if res.returncode != 0:
                        failures.append("[ruff] Failed")
                    print(f"  🔒 ruff: {'PASSED' if res.returncode == 0 else 'FAILED'}")
        finally:
            pass
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
        try:
            for p in self.repo.glob("*.preview.patch"):
                p.unlink()
        except OSError:
            pass
