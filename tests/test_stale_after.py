from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.core.intelligence.staleness import (
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_STALE,
    check_note_staleness,
)
from src.core.intelligence.store import IntelligenceStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> IntelligenceStore:
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(tmp_path / "data"))
    return IntelligenceStore(tmp_path / "proj")


def _make_note(node_id: str, **kwargs) -> dict:
    note = {
        "node_id": node_id,
        "section": "adrs",
        "timestamp": "2026-01-01 00:00:00",
        "data": {"text": "test"},
        "status": "ACTIVE",
    }
    note.update(kwargs)
    return note


class TestCheckNoteStaleness:
    def test_positive_future_stale_after_passing_discriminator(self):
        note = _make_note(
            "N1",
            stale_after="2099-12-31",
            discriminator="exit 0",
        )
        result = check_note_staleness(note)
        assert result == STATUS_ACTIVE

    def test_negative_past_stale_after(self):
        note = _make_note("N2", stale_after="2020-01-01")
        result = check_note_staleness(note)
        assert result == STATUS_STALE

    def test_negative_failing_discriminator(self):
        note = _make_note("N3", discriminator="exit 1")
        result = check_note_staleness(note)
        assert result == STATUS_EXPIRED

    def test_none_no_stale_after_no_discriminator(self):
        note = _make_note("N4")
        result = check_note_staleness(note)
        assert result == STATUS_ACTIVE

    def test_stale_after_today_is_not_stale(self):
        today = date.today().strftime("%Y-%m-%d")
        note = _make_note("N5", stale_after=today)
        result = check_note_staleness(note)
        assert result == STATUS_ACTIVE

    def test_invalid_stale_after_format_graceful(self):
        note = _make_note("N6", stale_after="not-a-date")
        result = check_note_staleness(note)
        assert result == STATUS_ACTIVE

    def test_discriminator_timeout_returns_expired(self):
        note = _make_note("N7", discriminator="sleep 30")
        result = check_note_staleness(note)
        assert result == STATUS_EXPIRED

    def test_stale_after_checked_before_discriminator(self):
        note = _make_note(
            "N8",
            stale_after="2020-01-01",
            discriminator="exit 1",
        )
        result = check_note_staleness(note)
        assert result == STATUS_STALE

    def test_injectable_now_date(self):
        note = _make_note("N9", stale_after="2025-06-15")
        result = check_note_staleness(note, now=date(2025, 6, 14))
        assert result == STATUS_ACTIVE
        result = check_note_staleness(note, now=date(2025, 6, 16))
        assert result == STATUS_STALE


class TestStoreCheckStaleness:
    def _save_notes(self, store: IntelligenceStore, notes: list):
        store._save_json("project_memory.json", notes)

    def test_store_positive_control(self, store):
        note = _make_note(
            "POS",
            stale_after="2099-12-31",
            discriminator="exit 0",
        )
        self._save_notes(store, [note])
        result = store.check_staleness("POS")
        assert result["staleness"] == STATUS_ACTIVE
        assert result["node_id"] == "POS"

    def test_store_negative_stale_after(self, store):
        note = _make_note("NEG-S", stale_after="2020-01-01")
        self._save_notes(store, [note])
        result = store.check_staleness("NEG-S")
        assert result["staleness"] == STATUS_STALE

    def test_store_negative_discriminator(self, store):
        note = _make_note("NEG-D", discriminator="exit 1")
        self._save_notes(store, [note])
        result = store.check_staleness("NEG-D")
        assert result["staleness"] == STATUS_EXPIRED

    def test_store_none_backward_compat(self, store):
        note = _make_note("NONE")
        self._save_notes(store, [note])
        result = store.check_staleness("NONE")
        assert result["staleness"] == STATUS_ACTIVE

    def test_store_not_found(self, store):
        result = store.check_staleness("MISSING")
        assert result["staleness"] == "NOT_FOUND"

    def test_store_mixed_notes(self, store):
        notes = [
            _make_note("A", stale_after="2099-01-01", discriminator="exit 0"),
            _make_note("B", stale_after="2020-01-01"),
            _make_note("C", discriminator="exit 1"),
            _make_note("D"),
        ]
        self._save_notes(store, notes)
        assert store.check_staleness("A")["staleness"] == STATUS_ACTIVE
        assert store.check_staleness("B")["staleness"] == STATUS_STALE
        assert store.check_staleness("C")["staleness"] == STATUS_EXPIRED
        assert store.check_staleness("D")["staleness"] == STATUS_ACTIVE


class TestCLI:
    def test_cli_check_staleness(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(tmp_path / "data"))
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir(parents=True, exist_ok=True)

        store = IntelligenceStore(proj_dir)
        note = _make_note("CLI1", stale_after="2020-01-01")
        store._save_json("project_memory.json", [note])

        from src.cli import main

        exit_code = main(["check_staleness", "CLI1", "--project", str(proj_dir)])
        assert exit_code == 0

    def test_cli_requires_note_id(self):
        from src.cli import main

        exit_code = main(["check_staleness"])
        assert exit_code == 2
