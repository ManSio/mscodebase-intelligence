"""Экономия CI: фильтр «менялся ли код» и структура workflow.

Замер 2026-11-15: один прогон CI = 12.6 runner-минут (7 job'ов), из них 4.7 —
тяжёлые job'ы, которые docs-only PR не требует; 28 из 46 PR-прогонов были
перезапусками одного дерева (не было `cancel-in-progress`).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import ci_changed_code as classifier  # noqa: E402

WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
HEAVY_JOBS = ("clean-state", "manifest-parity", "transport-equiv-e2e", "docker-build")


def test_docs_and_registries_are_not_code():
    assert classifier.has_code(
        ["docs/en/INSTALL.md", "README.md", "AGENT_DIARY.md", "KNOWN_ISSUES.md"]
    ) is False


def test_source_and_config_are_code():
    assert classifier.has_code(["src/core/config.py"]) is True
    assert classifier.has_code(["install.py"]) is True
    assert classifier.has_code(["pyproject.toml"]) is True


def test_one_source_file_among_docs_still_counts_as_code():
    assert classifier.has_code(["docs/en/INSTALL.md", "src/main.py"]) is True


def test_experiments_and_images_are_not_code():
    assert classifier.has_code(["experiments/e1/REPORT.md", "experiments/e1/run.json"]) is False
    assert classifier.has_code(["logo/logo.png", "docs/blog/assets/cover.png"]) is False


def test_empty_change_is_not_code():
    assert classifier.has_code([]) is False


def test_unknown_base_fails_open():
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ci_changed_code.py"), "does-not-exist"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "true", proc.stderr


def test_head_against_itself_is_not_code():
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ci_changed_code.py"), "HEAD"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "false", proc.stderr


def test_superseded_pr_runs_are_cancelled():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    concurrency = doc.get("concurrency") or {}
    assert "github.ref" in json_dump(concurrency), concurrency
    assert "pull_request" in json_dump(concurrency), "cancel must be scoped to PRs"
    assert "github.event_name == 'pull_request'" in (concurrency.get("cancel-in-progress") or "")


def test_heavy_jobs_wait_for_the_change_filter():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "changes" in doc["jobs"]
    for job in HEAVY_JOBS:
        spec = doc["jobs"][job]
        assert spec.get("needs") == "changes", job
        assert "needs.changes.outputs.code" in (spec.get("if") or ""), job


def json_dump(value) -> str:
    import json

    return json.dumps(value)
