"""Guard Inventory runner — negative controls (протокол Тома / OWP §5.2, P3 2026-08-11).

Тесты доказывают, что runner:
  1. умеет падать (--self-test: guard без negative control → классифицируется BROKEN);
  2. в default-режиме выходит 1 на BROKEN-записи (может упасть на реальном сбое);
  3. digest-pinning: правка фикстуры сбрасывает proven → unproven (exit 1);
  4. реальный manifest.json: все guard-ы PROVEN.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts" / "negative_controls_runner.py"
MANIFEST = ROOT / "scripts" / "negative_controls" / "manifest.json"


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        cwd=str(ROOT),
        capture_output=True,
        timeout=180,
        text=True,
        encoding="utf-8",  # runner печатает utf-8 (§5.9); Windows-locale иначе даёт mojibake
        errors="replace",
    )


def _load_runner():
    spec = importlib.util.spec_from_file_location("nc_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bash_available() -> bool:
    """GitBash есть? (System32\\bash.exe — WSL-шим, не считается.)"""
    w = shutil.which("bash")
    if not w:
        return False
    win_dir = os.environ.get("WINDIR")
    if win_dir and Path(w).resolve().is_relative_to(Path(win_dir).resolve()):
        return False
    return True


def _tmp_manifest(tmp_path, fixture=ROOT / "scripts" / "negative_controls" / "fixtures" / "dead_guard.py"):
    """Валидный tmp-manifest с одной python-записью (для pin-тестов)."""
    manifest = {
        "version": 1,
        "guards": [
            {
                "id": "tmp_guard",
                "desc": "tmp",
                "provocation_type": "test-class",
                "command": ["python", "-c", "import sys; sys.exit(0)"],
                "fixtures": [str(fixture)],
                "expected_exit": 0,
                "output_contains": [],
                "fixture_digest": "",
            }
        ],
    }
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps(manifest), encoding="utf-8")
    return mf


def test_runner_self_test_classification_works():
    """Negative control самого runner-а: guard, неспособный упасть → BROKEN.
    Exit 0 = классификатор исправен (если бы он «не умел падать» — exit 1, тест красный)."""
    p = _run("--self-test")
    assert p.returncode == 0, f"{p.stdout}\n{p.stderr}"
    assert "SELF-TEST: PASSED" in p.stdout
    assert "[BROKEN]" in p.stdout


def test_runner_default_exits_1_on_broken_guard(tmp_path):
    """Default-режим обязан выйти 1, когда negative control не падает (BROKEN)."""
    mod = _load_runner()
    fixture = ROOT / "scripts" / "negative_controls" / "fixtures" / "dead_guard.py"
    manifest = {
        "version": 1,
        "guards": [
            {
                "id": "fake_broken",
                "desc": "guard, который не умеет падать (rc=0 при ожидании 1)",
                "provocation_type": "test-class",
                "command": ["python", "-c", "import sys; sys.exit(0)"],
                "fixtures": [str(fixture)],
                "expected_exit": 1,
                "output_contains": [],
                "fixture_digest": mod._digest_files([fixture]),
            }
        ],
    }
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps(manifest), encoding="utf-8")
    p = _run("--manifest", str(mf))
    assert p.returncode == 1, f"{p.stdout}\n{p.stderr}"
    assert "[BROKEN]" in p.stdout


def _repo_tmp_dir(prefix: str) -> Path:
    """A scratch directory INSIDE the repo.

    tmp_path is outside the repo, and negative_controls_runner._resolve_fixtures
    refuses any fixture that is not under scripts/ or the repo root — by design
    (path safety). So the copy has to live inside the tree. The caller removes it
    in `finally`, and it is never committed.
    """
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(ROOT)))


def test_runner_detects_digest_change():
    """digest-pinning: правка фикстуры → UNPROVEN → exit 1.

    The mutation is applied to a COPY under a scratch dir, never to
    scripts/negative_controls/fixtures/.

    An earlier version edited the real fixture and restored it in `finally`. Under
    `pytest -n auto` another worker could read that fixture's digest inside the
    window between the write and the restore, compute a different digest, and
    classify a healthy guard as UNPROVEN. That is a race BETWEEN TESTS, not a
    property of the digest guard. It showed up as a CI-only flake: green locally,
    red on runners that have more workers.

    The manifest here holds ONE entry on purpose. Asserting a clean whole-inventory
    run would drag in drift_gate, which is legitimately BROKEN wherever GitBash is
    missing — a property of the machine, not of this test.
    """
    mod = _load_runner()
    scratch = _repo_tmp_dir("nc-digest-")
    try:
        src = ROOT / "scripts" / "negative_controls" / "fixtures" / "dead_guard.py"
        copy = scratch / src.name
        shutil.copyfile(src, copy)

        manifest = {
            "version": 1,
            "guards": [{
                "id": "digest_probe",
                "desc": "guard whose fixture digest is pinned",
                "provocation_type": "test-class",
                "command": [sys.executable, str(scratch / "dead_guard_negative_control.py")],
                "fixtures": [str(copy)],
                "expected_exit": 1,
                "output_contains": ["DEAD GUARD DETECTED"],
                "fixture_digest": mod._digest_files([copy]),
            }],
        }
        # the probe script it invokes, unmodified, next to the fixture
        shutil.copyfile(
            ROOT / "scripts" / "negative_controls" / "fixtures" / "dead_guard_negative_control.py",
            scratch / "dead_guard_negative_control.py")

        mf = scratch / "manifest.json"
        mf.write_text(json.dumps(manifest), encoding="utf-8")

        # Control: with intact bytes the guard is PROVEN and the runner exits 0.
        p = _run("--manifest", str(mf))
        assert p.returncode == 0, f"{p.stdout}\n{p.stderr}"
        assert "[PROVEN]" in p.stdout

        # Break ONE fixture byte-for-byte; the digest pin must notice.
        copy.write_bytes(copy.read_bytes() + b"\n# digest-mutant\n")
        p = _run("--manifest", str(mf))
        assert p.returncode == 1, f"{p.stdout}\n{p.stderr}"
        assert "[UNPROVEN]" in p.stdout
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_runner_pin_requires_reason(tmp_path):
    """TC-10: --pin без --reason обязан отказать (ревью-момент не фиксируется)."""
    mf = _tmp_manifest(tmp_path)
    p = _run("--manifest", str(mf), "--pin")
    assert p.returncode == 1, f"{p.stdout}\n{p.stderr}"
    assert "--reason обязателен" in p.stdout


def test_runner_pin_writes_log(tmp_path):
    """TC-10: --pin --reason пишет ревью-запись в pin_log.json рядом с manifest."""
    mf = _tmp_manifest(tmp_path)
    p = _run("--manifest", str(mf), "--pin", "--reason", "test: re-prove")
    assert p.returncode == 0, f"{p.stdout}\n{p.stderr}"
    log = tmp_path / "pin_log.json"
    assert log.exists()
    entries = json.loads(log.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["reason"] == "test: re-prove"
    assert "tmp_guard" in entries[0]["digests"]
    assert entries[0]["digests"]["tmp_guard"]


def test_runner_schema_rejects_missing_provocation_type(tmp_path):
    """TC-1: запись без provocation_type обязана быть отвергнута на уровне схемы."""
    mf = _tmp_manifest(tmp_path)
    data = json.loads(mf.read_text(encoding="utf-8"))
    del data["guards"][0]["provocation_type"]
    mf.write_text(json.dumps(data), encoding="utf-8")
    p = _run("--manifest", str(mf))
    assert p.returncode == 1, f"{p.stdout}\n{p.stderr}"
    assert "provocation_type обязателен" in p.stdout


@pytest.mark.skipif(not _bash_available(), reason="нет GitBash bash (Windows CI без Git)")
def test_runner_inventory_all_proven():
    """Реальный manifest: все guard-ы обязаны быть PROVEN (exit 0)."""
    p = _run()
    assert p.returncode == 0, f"{p.stdout}\n{p.stderr}"
    assert "NEGATIVE CONTROLS: ALL PROVEN" in p.stdout
    assert "[BROKEN]" not in p.stdout
    assert "[UNPROVEN]" not in p.stdout


def test_runner_digest_is_line_ending_agnostic(tmp_path):
    """Портability-гвард (инцидент 199dbe6b): digest(CRLF) == digest(LF)
    при одинаковом имени файла (имя — часть digest by design).
    Иначе Windows working-tree (CRLF) и CI-checkout (LF) дают разные пины."""
    mod = _load_runner()
    d1 = tmp_path / "x"
    d2 = tmp_path / "y"
    d1.mkdir()
    d2.mkdir()
    a = d1 / "f.txt"
    b = d2 / "f.txt"
    a.write_bytes(b"line1\r\nline2\r\n")
    b.write_bytes(b"line1\nline2\n")
    assert mod._digest_files([a]) == mod._digest_files([b])
    # имя файла — часть digest: то же содержимое под другим именем ≠ тот же digest
    c = d1 / "g.txt"
    c.write_bytes(b"line1\nline2\n")
    assert mod._digest_files([a]) != mod._digest_files([c])


def test_runner_manifest_schema():
    """Каждая запись: >=1 фикстура, expected_exit, command, provocation_type, pinned digest."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["version"] == 1
    for entry in manifest["guards"]:
        assert entry["fixtures"], f"{entry['id']}: fixtures пуст"
        assert "expected_exit" in entry, entry["id"]
        assert entry["command"], entry["id"]
        assert entry.get("provocation_type"), f"{entry['id']}: provocation_type пуст (TC-1)"
        assert entry["fixture_digest"], f"{entry['id']}: digest не запинен (нужен --pin)"
