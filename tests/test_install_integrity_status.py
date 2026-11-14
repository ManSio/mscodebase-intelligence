"""Проверка целостности архива и честный статус шага установщика.

Два дефекта 2026-11-14, найденные живьём:
1. Пин `LLAMA_BIN_SHA256` для Windows был неверен с первого коммита: установщик
   скачивал ПРАВИЛЬНЫЙ архив (GitHub API `digest` совпадал с фактическим хэшем),
   отбивал его по своему же пину и рапортовал успех.
2. `step_llama` на провале скачивания добавлял жёлтую строку и возвращался
   нормально: `_step` считал шаг ok, итог — `0 failed`, exit code 0.
"""

from __future__ import annotations

import hashlib
import sys

import pytest

import install as installer
from src.providers.reranker import llama_install

DIGEST = hashlib.sha256(b"archive-bytes").hexdigest()


@pytest.fixture()
def archive(tmp_path):
    path = tmp_path / "llama-b11476-bin-win-cpu-x64.zip"
    path.write_bytes(b"archive-bytes")
    return path


def test_matching_pin_is_accepted_without_the_network(archive, monkeypatch):
    monkeypatch.setitem(llama_install.LLAMA_BIN_SHA256, "win-cpu-x64", DIGEST)

    def no_network(_name):
        raise AssertionError("network must not be used when the pin matches")

    monkeypatch.setattr(llama_install, "_github_asset_digest", no_network)
    assert llama_install._verify_archive_sha256(archive, "win-cpu-x64") is True


def test_stale_pin_is_corrected_by_the_github_digest(archive, monkeypatch):
    """Ровно наш случай: пин устарел, GitHub подтверждает фактический хэш."""
    monkeypatch.setitem(llama_install.LLAMA_BIN_SHA256, "win-cpu-x64", "0" * 64)
    monkeypatch.setattr(llama_install, "_github_asset_digest", lambda _name: DIGEST)
    assert llama_install._verify_archive_sha256(archive, "win-cpu-x64") is True
    assert archive.exists()


def test_a_real_mismatch_is_rejected_and_the_archive_removed(archive, monkeypatch):
    monkeypatch.setitem(llama_install.LLAMA_BIN_SHA256, "win-cpu-x64", "0" * 64)
    monkeypatch.setattr(llama_install, "_github_asset_digest", lambda _name: "1" * 64)
    assert llama_install._verify_archive_sha256(archive, "win-cpu-x64") is False
    assert not archive.exists()


def test_no_pin_is_verified_against_the_github_digest(archive, monkeypatch):
    monkeypatch.setitem(llama_install.LLAMA_BIN_SHA256, "ubuntu-x64", None)
    monkeypatch.setattr(llama_install, "_github_asset_digest", lambda _name: DIGEST)
    assert llama_install._verify_archive_sha256(archive, "ubuntu-x64") is True


def test_no_pin_and_no_network_fails_closed(archive, monkeypatch):
    monkeypatch.setitem(llama_install.LLAMA_BIN_SHA256, "ubuntu-x64", None)
    monkeypatch.setattr(llama_install, "_github_asset_digest", lambda _name: None)
    assert llama_install._verify_archive_sha256(archive, "ubuntu-x64") is False
    assert not archive.exists(), "неподтверждённый архив нельзя оставлять на диске"


def test_the_pinned_hashes_are_well_formed():
    for tag, value in llama_install.LLAMA_BIN_SHA256.items():
        if value is None:
            continue
        assert len(value) == 64 and value == value.lower(), tag


@pytest.mark.skipif(sys.platform != "win32", reason="WinError 32 — примитив Windows")
def test_locked_file_is_discarded_without_raising(tmp_path):
    """Ревью: уборка .part падала PermissionError и нарушала bool-контракт."""
    path = tmp_path / "busy.part"
    path.write_bytes(b"x")
    handle = open(path, "rb")
    try:
        llama_install._discard(path)  # не должен бросить
    finally:
        handle.close()
    llama_install._discard(path)
    assert not path.exists()


def test_step_llama_reports_failure_instead_of_a_green_step(tmp_path, monkeypatch):
    from src.providers.reranker import llama_runner

    monkeypatch.setattr(installer, "ZED_EXT_DIR", tmp_path / "ext")
    monkeypatch.setattr(llama_runner, "is_installed", lambda: False)
    monkeypatch.setattr(llama_runner, "download_llama_binary", lambda progress_cb=None: False)
    monkeypatch.setattr(llama_runner, "_get_llama_dir", lambda: tmp_path / "src")
    lines: list[tuple[str, str]] = []
    with pytest.raises(RuntimeError):
        installer.step_llama(lines, "en")


def test_a_failed_step_makes_the_installer_exit_non_zero(monkeypatch, capsys):
    """Итог `0 failed` при провале шага стоил пользователю движка."""

    def boom(_lines, _lang):
        raise RuntimeError("engine missing")

    monkeypatch.setattr(installer, "STEPS", [(0, "step_boom", boom)])
    monkeypatch.setattr(installer, "_record_install_meta", lambda: None)
    monkeypatch.setattr(installer, "_box", lambda *_a, **_k: None)
    monkeypatch.setattr(installer, "_line", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "argv", ["install.py", "--yes"])

    assert installer.main() == 1
