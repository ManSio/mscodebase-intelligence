"""Тесты restraint — сдержанность advisory-доставки (anti-numbing).

Покрытие: сигнатура чувствительна к kind/symbol/file; первая доставка; подавление немедленного
повтора; доставка после cooldown; сброс на новой сигнатуре; рост backoff по страйкам.
"""
from src.core.restraint import should_deliver, signature


def test_signature_changes_with_content():
    a = [{"kind": "new_orphan", "symbol": "x", "file": "a.py"}]
    b = [{"kind": "new_orphan", "symbol": "y", "file": "a.py"}]
    assert signature(a) == signature(a)
    assert signature(a) != signature(b)


def test_first_delivers_then_suppresses_then_cooldown(tmp_path):
    sig = "sigA"
    ok, _ = should_deliver(tmp_path, sig, cooldown_sec=100, now=1000)
    assert ok is True

    ok, reason = should_deliver(tmp_path, sig, cooldown_sec=100, now=1050)
    assert ok is False
    assert "cooldown" in reason

    ok, _ = should_deliver(tmp_path, sig, cooldown_sec=100, now=1101)
    assert ok is True


def test_new_signature_resets(tmp_path):
    should_deliver(tmp_path, "sigA", cooldown_sec=100, now=1000)
    ok, _ = should_deliver(tmp_path, "sigB", cooldown_sec=100, now=1010)
    assert ok is True  # другая сигнатура — доставляем


def test_backoff_grows(tmp_path):
    sig = "sigA"
    should_deliver(tmp_path, sig, cooldown_sec=100, now=1000)   # deliver, strikes 0
    should_deliver(tmp_path, sig, cooldown_sec=100, now=1101)   # deliver, strikes 1 -> window 200
    ok, _ = should_deliver(tmp_path, sig, cooldown_sec=100, now=1250)  # elapsed 149 < 200
    assert ok is False
