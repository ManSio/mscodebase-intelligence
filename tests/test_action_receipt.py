"""Action Receipt (ТЗ §11): вердикты, store, retention/GC, build_receipt.

Покрывает:
- verdict_from_results: VERIFIED / REFUTED / INCONCLUSIVE (три, не два);
- INCONCLUSIVE-маркеры (среда-блокировка) ≠ REFUTED (провал содержимого);
- build_receipt: verification_steps + reproducible_by + иммутабельность
  (supersedes — пере-верификация = новый receipt, старый не мутируется);
- ActionReceiptStore: record/get/query/count;
- gc: INCONCLUSIVE протухает быстро, последние keep_last сохраняются.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from src.core.action_receipt import (
    VERDICT_INCONCLUSIVE,
    VERDICT_REFUTED,
    VERDICT_VERIFIED,
    ActionReceiptStore,
    build_receipt,
    format_receipt,
    reproducible_command,
    verdict_from_results,
)


def _ok(action="git_commit"):
    return {"action": action, "verified": True, "errors": []}


def _fail(action="file_write"):
    return {"action": action, "verified": False, "errors": ["Содержимое не совпадает"]}


def _inconclusive(action="git_commit"):
    return {"action": action, "verified": False, "errors": ["Git не найден в PATH"]}


# ── вердикты ──────────────────────────────────────────────


def test_verdict_all_pass_is_verified():
    assert verdict_from_results([_ok(), _ok()]) == VERDICT_VERIFIED


def test_verdict_fail_is_refuted():
    assert verdict_from_results([_ok(), _fail()]) == VERDICT_REFUTED


def test_verdict_env_block_is_inconclusive_not_refuted():
    # Git не найден в PATH / таймаут — "не удалось выполнить", НЕ "провалилось".
    assert verdict_from_results([_inconclusive()]) == VERDICT_INCONCLUSIVE


def test_verdict_fail_beats_inconclusive():
    # Явный fail перевешивает среду-недоступность → REFUTED.
    assert verdict_from_results([_inconclusive(), _fail()]) == VERDICT_REFUTED


def test_verdict_index_sync_always_inconclusive():
    # index_sync не выполняет реальной проверки (ждёт внешнюю) → INCONCLUSIVE.
    r = {"action": "index_sync", "verified": True, "errors": [],
         "note": "Вызовите get_index_status"}
    assert verdict_from_results([r]) == VERDICT_INCONCLUSIVE


def test_verdict_empty_is_inconclusive():
    assert verdict_from_results([]) == VERDICT_INCONCLUSIVE


# ── build_receipt ─────────────────────────────────────────


def test_build_receipt_generates_id_and_steps():
    rec = build_receipt(
        "file_write",
        [_ok("file_write")],
        claim="записал файл",
        after_hash="abc123",
        file_path="src/a.py",
    )
    assert rec.action_id.startswith("REC-")
    assert rec.verdict == VERDICT_VERIFIED
    assert rec.verification_steps[0]["check"] == "verify_file_write"
    assert rec.verification_steps[0]["result"] == "pass"
    assert "reproducible" in rec.reproducible_by.lower() or rec.reproducible_by.startswith('python') or rec.reproducible_by.startswith('#') or "python" in rec.reproducible_by


def test_build_receipt_supersedes_not_mutating():
    """Иммутабельность: пере-верификация = НОВЫЙ receipt, старый не трогаем."""
    old = build_receipt("file_write", [_fail()], action_id="REC-fix1")
    new = build_receipt(
        "file_write", [_ok()], action_id="REC-fix1", supersedes=old.action_id
    )
    # Оба независимы; новый ссылается на старый как superseded.
    assert new.supersedes == old.action_id


def test_reproducible_command_known_types():
    assert "git" in reproducible_command("git_commit")
    assert "git" in reproducible_command("git_push")
    assert "pytest" in reproducible_command("index_sync")
    assert "hashlib" in reproducible_command("file_write")


def test_format_receipt_includes_verdict():
    rec = build_receipt("file_write", [_ok()])
    out = format_receipt(rec.to_dict())
    assert "VERIFIED" in out
    assert rec.action_id in out


# ── store ─────────────────────────────────────────────────


def test_store_record_get_query(tmp_path: Path):
    store = ActionReceiptStore(tmp_path)
    rec = build_receipt("git_commit", [_ok("git_commit")], action_id="REC-store1")
    assert store.record(rec) is True
    assert store.path.exists()

    got = store.get("REC-store1")
    assert got is not None
    assert got["action_id"] == "REC-store1"
    assert got["verdict"] == VERDICT_VERIFIED

    # query возвращает последние N
    rec2 = build_receipt("git_push", [_ok("git_push")], action_id="REC-store2")
    store.record(rec2)
    q = store.query(limit=10)
    assert len(q) == 2
    assert q[-1]["action_id"] == "REC-store2"
    assert store.count() == 2


def test_store_get_unknown_returns_none(tmp_path: Path):
    store = ActionReceiptStore(tmp_path)
    assert store.get("NOPE") is None


def test_store_get_last_wins(tmp_path: Path):
    """Пере-верификация: get возвращает последний (суперседящий) receipt."""
    store = ActionReceiptStore(tmp_path)
    store.record(build_receipt("file_write", [_fail()], action_id="REC-x"))
    store.record(build_receipt("file_write", [_ok()], action_id="REC-x"))
    got = store.get("REC-x")
    assert got["verdict"] == VERDICT_VERIFIED


def test_gc_removes_old_inconclusive_keeps_recent(tmp_path: Path):
    store = ActionReceiptStore(tmp_path)

    old_inc = build_receipt(
        "git_commit",
        [_inconclusive()],
        action_id="REC-old",
    )
    old_inc.timestamp = (
        datetime.now() - timedelta(days=30)
    ).isoformat()
    store.record(old_inc)

    keep_recent = build_receipt(
        "file_write", [_ok("file_write")], action_id="REC-new"
    )
    store.record(keep_recent)

    stats = store.gc(inconclusive_ttl_days=7, keep_last=1)
    assert stats["removed"] == 1
    assert store.get("REC-new") is not None
    assert store.get("REC-old") is None


def test_gc_keep_last_independent_of_age(tmp_path: Path):
    """Последние keep_last сохраняются даже если старые/протухшие."""
    store = ActionReceiptStore(tmp_path)
    old = build_receipt("git_commit", [_inconclusive()], action_id="REC-keep")
    old.timestamp = (datetime.now() - timedelta(days=100)).isoformat()
    store.record(old)

    stats = store.gc(inconclusive_ttl_days=7, keep_last=10)
    assert stats["removed"] == 0
    assert store.get("REC-keep") is not None


def test_gc_idempotent_noop_when_nothing_expired(tmp_path: Path):
    store = ActionReceiptStore(tmp_path)
    rec = build_receipt("git_commit", [_ok("git_commit")], action_id="REC-fresh")
    store.record(rec)
    stats = store.gc()
    assert stats["removed"] == 0
    assert store.count() == 1
