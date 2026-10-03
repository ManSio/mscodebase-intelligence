"""Тесты гейта third_party_data.

Контроль обязан уметь падать: здесь это проверяется дважды — на реальном
инциденте (посаженное нарушение обязано ловиться) и на чистом входе
(ложное срабатывание запрещено).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_third_party_data as gate  # noqa: E402


def _write(tmp_path: Path, name: str, content: str) -> str:
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return str(target)


@pytest.fixture(autouse=True)
def _point_root(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "PROJECT_ROOT", tmp_path)
    return tmp_path


def test_catches_personal_email_of_third_party(tmp_path):
    """R1 обязан сработать на фикстуре.

    Домен фикстуры зарезервирован RFC 2606 и передаётся явно: зарегистрировать
    его невозможно, поэтому адрес не может принадлежать живому человеку, но
    проверка R1 всё равно обязана на нём срабатывать.
    """
    rel = _write(tmp_path, "dump.md", "author contact: some.person@personal.invalid\n")
    findings = gate.check_file(rel, set(gate.PERSONAL_DOMAINS) | {gate.RESERVED_TEST_DOMAIN})
    assert any(f.startswith("R1") for f in findings), findings


def test_owner_email_is_allowed(tmp_path):
    rel = _write(tmp_path, "note.md", f"contact: {sorted(gate.OWNER_ALLOWLIST)[0]}\n")
    findings = gate.check_file(rel)
    assert not any(f.startswith("R1") for f in findings), findings


def test_vendored_metadata_is_not_flagged(tmp_path):
    rel = _write(
        tmp_path,
        "fixtures/composer.lock",
        "maintainer: upstream.dev@personal.invalid\n",
    )
    findings = gate.check_file(rel)
    assert not any(f.startswith("R1") for f in findings), findings


def test_module_at_symbol_notation_is_not_an_email(tmp_path):
    """Реальный класс FP: трейсы пишут вызовы как `модуль@символ.py`."""
    rel = _write(tmp_path, "trace.json", "inc@monitoring.py\nsnapshot@observability.py\n")
    findings = gate.check_file(rel)
    assert not any(f.startswith("R1") for f in findings), findings


def test_catches_scraped_profile_signature(tmp_path):
    rel = _write(
        tmp_path,
        "page.md",
        "- Location: France\nJoined\n- Education: X\nProfile image\n",
    )
    findings = gate.check_file(rel)
    assert any(f.startswith("R2") for f in findings), findings


def test_own_report_with_quotes_is_not_flagged(tmp_path):
    """Наш вывод со ссылками и цитатами — не дамп, должен проходить."""
    rel = _write(
        tmp_path,
        "HANDOFF.md",
        "Источник: https://dev.to/a/b\nЦитата автора: 'You don't add bananas "
        "and monkeys.'\nСсылка на профиль: https://dev.to/c\n",
    )
    findings = gate.check_file(rel)
    assert findings == [], findings


def test_large_dump_is_advisory_not_blocking(tmp_path, capsys):
    """R3 не должен блокировать коммит — иначе гейт умрёт от FP-усталости."""
    body = "text line\n" * 6000
    body += "\n".join(f"https://site{i}.example/page" for i in range(8))
    _write(tmp_path, "big.md", body)
    rc = gate._report(["big.md"], "staged")
    out = capsys.readouterr().out
    assert any(line.strip().startswith("⚠️") for line in out.splitlines()), out
    assert "advisory=1" in out, out
    assert rc == 0, out


def test_empty_population_is_not_reported_as_clean(tmp_path, monkeypatch, capsys):
    """§19.6: пустая популяция обязана быть видна, а не выглядеть «0 нарушений»."""
    monkeypatch.setattr(gate, "_staged_files", lambda: [])
    rc = gate._report([], "staged")
    out = capsys.readouterr().out
    assert rc == 0
    assert "SKIP" in out
    assert "популяция не измерена" in out


def test_missing_file_is_skipped_not_crashed(tmp_path):
    assert gate.check_file("does/not/exist.md") == []


def test_non_text_file_is_skipped(tmp_path):
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"\x00\x01\x02")
    assert gate.check_file(str(binary)) == []
