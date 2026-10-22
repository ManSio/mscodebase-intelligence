#!/usr/bin/env python3
"""Tests for scripts/check_duplicate_runs.py — the inflated-denominator gate.

The gate's own contract is that it can FAIL: every test below asserts a specific
exit code, and the empty-population test (§19.6) asserts the script refuses to
report a clean result on an empty set rather than printing "0 duplicates".
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_duplicate_runs.py"


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _manifest(path: Path, body: dict) -> Path:
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the gate as a real subprocess: exit code is the deliverable."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def test_duplicate_detection_blocks(tmp_path: Path) -> None:
    _write(tmp_path / "run_m_1.txt", "identical body\n")
    _write(tmp_path / "run_m_2.txt", "identical body\n")
    manifest = _manifest(tmp_path / "manifest.json", {"runs": 2})

    proc = _run(str(tmp_path), "--manifest", str(manifest))

    assert proc.returncode == 1, proc.stdout + proc.stderr
    report = json.loads(_run(str(tmp_path), "--json").stdout)
    assert report["duplicate_groups"], "expected a duplicate group"
    group = report["duplicate_groups"][0]
    assert group["file_count"] == 2
    assert group["distinct_runs"] == 1
    assert report["run_files"] == 2 and report["distinct_runs"] == 1


def test_clean_dir_exits_zero(tmp_path: Path) -> None:
    for i, body in enumerate(["one\n", "two\n", "three\n"], start=1):
        _write(tmp_path / f"run_m_{i}.txt", body)
    manifest = _manifest(tmp_path / "manifest.json", {"runs": 3})

    proc = _run(str(tmp_path), "--manifest", str(manifest))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "VERDICT: PASS" in proc.stdout


def test_empty_dir_exits_two_and_never_reports_clean(tmp_path: Path) -> None:
    """§19.6: a rate on an empty set is not a result."""
    empty = tmp_path / "empty"
    empty.mkdir()

    proc = _run(str(empty))

    assert proc.returncode == 2, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert "ERROR" in combined and "no run files found" in combined
    assert "0 duplicates" not in combined
    assert "DUPLICATES: none" not in combined
    assert "VERDICT: PASS" not in combined


def test_missing_target_exits_two(tmp_path: Path) -> None:
    proc = _run(str(tmp_path / "does_not_exist"))

    assert proc.returncode == 2
    assert "not found" in (proc.stdout + proc.stderr)


def test_manifest_overcount_is_a_mismatch(tmp_path: Path) -> None:
    """A manifest claiming more runs than distinct files inflate the denominator."""
    _write(tmp_path / "run_m_1.txt", "a\n")
    _write(tmp_path / "run_m_2.txt", "b\n")
    manifest = _manifest(tmp_path / "manifest.json", {"total_runs": 7})

    proc = _run(str(tmp_path), "--manifest", str(manifest))

    assert proc.returncode == 1, proc.stdout + proc.stderr
    report = json.loads(_run(str(tmp_path), "--manifest", str(manifest), "--json").stdout)
    bad = [m for m in report["mismatches"] if m["json_path"] == "$.total_runs"]
    assert bad and bad[0]["declared"] == 7


def test_manifest_undercount_is_a_mismatch(tmp_path: Path) -> None:
    _write(tmp_path / "run_m_1.txt", "a\n")
    _write(tmp_path / "run_m_2.txt", "b\n")
    _write(tmp_path / "run_m_3.txt", "c\n")
    manifest = _manifest(tmp_path / "manifest.json", {"n_runs": 2})

    proc = _run(str(tmp_path), "--manifest", str(manifest))

    assert proc.returncode == 1, proc.stdout + proc.stderr
    report = json.loads(_run(str(tmp_path), "--manifest", str(manifest), "--json").stdout)
    assert any(m["json_path"] == "$.n_runs" for m in report["mismatches"])


def test_dup_files_with_honest_count_still_blocks(tmp_path: Path) -> None:
    """Manifest count matches the DISTINCT count, but the files are duplicated."""
    _write(tmp_path / "run_m_1.txt", "same\n")
    _write(tmp_path / "run_m_2.txt", "same\n")
    _write(tmp_path / "run_m_3.txt", "other\n")
    manifest = _manifest(tmp_path / "manifest.json", {"total_runs": 2})

    proc = _run(str(tmp_path), "--manifest", str(manifest))

    assert proc.returncode == 1, proc.stdout + proc.stderr
    report = json.loads(_run(str(tmp_path), "--manifest", str(manifest), "--json").stdout)
    assert report["mismatches"] == []          # the count itself is truthful
    assert report["duplicate_groups"]          # but the files are not


def test_per_model_dict_counts_are_walked(tmp_path: Path) -> None:
    for i in range(1, 6):
        _write(tmp_path / f"run_alpha_{i}.txt", f"alpha {i}\n")
    manifest = _manifest(tmp_path / "manifest.json", {"runs_per_model": {"alpha": 9}})

    report = json.loads(_run(str(tmp_path), "--manifest", str(manifest), "--json").stdout)

    paths = {d["json_path"]: d for d in report["declared_counts"]}
    assert "$.runs_per_model.alpha" in paths
    assert paths["$.runs_per_model.alpha"]["declared"] == 9
    assert paths["$.runs_per_model.alpha"]["status"] == "MISMATCH"


def test_ans_files_included_and_zero_byte_files_excluded(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    _write(work / "ans_t_1.txt", "same answer\n")
    _write(work / "ans_t_2.txt", "same answer\n")
    _write(work / "ans_t_3.txt", "")            # zero-byte: NOT a duplicate pair
    _write(work / "ans_t_4.txt", "")

    report = json.loads(_run(str(tmp_path), "--json").stdout)

    assert report["run_files"] == 4             # ans_ files are included by design
    assert sorted(p.split("\\")[-1] for p in report["empty_files"]) == ["ans_t_3.txt", "ans_t_4.txt"]
    # The two identical non-empty answers ARE reported; the two empties are not.
    assert len(report["duplicate_groups"]) == 1
    assert sorted(f.split("\\")[-1] for f in report["duplicate_groups"][0]["files"]) == [
        "ans_t_1.txt", "ans_t_2.txt",
    ]
    assert report["distinct_runs"] == 1         # empties contribute no distinct run


def test_unrelated_files_are_ignored(tmp_path: Path) -> None:
    _write(tmp_path / "run_m_1.txt", "a\n")
    _write(tmp_path / "notes.txt", "a\n")          # same bytes, not a run file
    _write(tmp_path / "manifest.json.bak", "not a manifest")

    report = json.loads(_run(str(tmp_path), "--json").stdout)

    assert report["run_files"] == 1
    assert report["duplicate_groups"] == []


@pytest.mark.parametrize("code", [0, 1, 2])
def test_exit_codes_are_exactly_the_contract(tmp_path: Path, code: int) -> None:
    """No other exit code may leak out of the documented contract."""
    if code == 0:
        _write(tmp_path / "run_m_1.txt", "a\n")
    elif code == 1:
        _write(tmp_path / "run_m_1.txt", "a\n")
        _write(tmp_path / "run_m_2.txt", "a\n")
    assert _run(str(tmp_path)).returncode == code


def test_missing_manifest_path_exits_two(tmp_path: Path) -> None:
    _write(tmp_path / "run_m_1.txt", "a\n")
    proc = _run(str(tmp_path), "--manifest", str(tmp_path / "nope.json"))
    assert proc.returncode == 2
    assert "manifest not found" in (proc.stdout + proc.stderr)


def test_selftest_exits_zero() -> None:
    proc = _run("--selftest")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SELFTEST OK" in proc.stdout
    for line in proc.stdout.splitlines():
        if "expected exit" in line:
            assert "[ok]" in line, line


def test_real_f4b_defect_is_detected() -> None:
    """Held-out: the actual on-disk F4b duplicate, not a synthetic fixture."""
    target = REPO / "experiments" / "4A_unit_of_return" / "results" / "f4b"
    if not target.is_dir():
        pytest.skip("f4b results not present")

    proc = _run(str(target))

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "run_longcat-2.0_2.txt" in proc.stdout
    assert "run_longcat-2.0_5.txt" in proc.stdout
