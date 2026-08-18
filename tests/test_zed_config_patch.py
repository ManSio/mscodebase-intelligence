"""Тесты patch_zed_settings — путь ВСТАВКИ (ключ отсутствует).

Инцидент 2026-08-14: `_insert_before_final_brace` имел инвертированную логику
запятой — при вставке `context_servers` ПОСЛЕ вложенного объекта
(`"agent": {...}`) запятая не ставилась → settings.json становился битым JSON.
Раньше баг не проявлялся: ключ уже существовал → работал путь ЗАМЕНЫ
(_find_value_span), вставка не вызывалась.
"""

import json

import pytest

from adapters.zed import zed_config

SERVER = "mscodebase-intelligence"


@pytest.fixture
def settings_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(zed_config, "get_zed_config_dir", lambda: tmp_path)
    return tmp_path


def _patch(settings_dir, command):
    return zed_config.patch_zed_settings(
        command,
        mode="global",
        install_path=r"C:\ext",
    )


def test_insert_after_nested_object_is_valid_json(settings_dir):
    """Регрессия: вставка после вложенного объекта должна давать валидный JSON."""
    before = (
        '{\n'
        '  "theme": "dark",\n'
        '  "agent": {\n'
        '    "enabled": true\n'
        '  }\n'
        '}\n'
    )
    (settings_dir / "settings.json").write_text(before, encoding="utf-8")

    assert _patch(settings_dir, r"C:\ext\venv\Scripts\pythonw.exe -u -m src.main") is True

    text = (settings_dir / "settings.json").read_text(encoding="utf-8")
    # строгий json.loads ловит битую запятую
    data = json.loads(text)
    assert SERVER in data["context_servers"]
    assert data["context_servers_to_query"] == [SERVER]
    assert data["theme"] == "dark"
    assert data["agent"] == {"enabled": True}
    entry = data["context_servers"][SERVER]
    assert entry["command"] == r"C:\ext\venv\Scripts\pythonw.exe"
    assert entry["args"] == ["-u", "-m", "src.main"]
    # env: только authoritative-ключи, без DEPRECATED EMBEDDING_*
    assert entry["env"] == {
        "PYTHONPATH": r"C:\ext",
        "PROJECT_PATH": "$ZED_WORKTREE_ROOT",
        "PYTHONUTF8": "1",
    }


def test_insert_into_empty_object(settings_dir):
    (settings_dir / "settings.json").write_text("{}\n", encoding="utf-8")
    assert _patch(settings_dir, r"C:\ext\venv\Scripts\pythonw.exe -u -m src.main") is True
    data = json.loads((settings_dir / "settings.json").read_text(encoding="utf-8"))
    assert SERVER in data["context_servers"]
    assert data["context_servers_to_query"] == [SERVER]


def test_replace_existing_entry(settings_dir):
    before = json.dumps({
        "context_servers": {SERVER: {"enabled": False, "command": "old"}},
        "context_servers_to_query": [],
    })
    (settings_dir / "settings.json").write_text(before, encoding="utf-8")
    assert _patch(settings_dir, r"C:\ext\venv\Scripts\pythonw.exe -u -m src.main") is True
    data = json.loads((settings_dir / "settings.json").read_text(encoding="utf-8"))
    entry = data["context_servers"][SERVER]
    assert entry["enabled"] is True
    assert entry["command"] == r"C:\ext\venv\Scripts\pythonw.exe"
    assert entry["env"]["PYTHONPATH"] == r"C:\ext"
