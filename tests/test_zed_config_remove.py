"""Тесты remove_zed_settings (JSONC-safe) — легаси-запись в settings.json.

Инцидент 2026-08-14: install.py (step_zedcfg) писал дубль-регистрацию
(python.exe) в settings.json, откатывая фикс «pythonw без окна консоли».
Теперь install вызывает remove_zed_settings(keep_to_query=True). Тесты
фиксируют контракт:
- keep_to_query=True — удаляет только context_servers.mscodebase-intelligence,
  сохраняет context_servers_to_query, других серверов и JSONC-комментарии;
- keep_to_query=False (uninstall-путь) — удаляет и запись, и список.
"""

import pytest

from src.utils import zed_config

SERVER = "mscodebase-intelligence"


@pytest.fixture
def settings_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(zed_config, "get_zed_config_dir", lambda: tmp_path)
    return tmp_path


def _write(settings_dir, text: str):
    p = settings_dir / "settings.json"
    p.write_text(text, encoding="utf-8")
    return p


def _read(settings_dir) -> str:
    return (settings_dir / "settings.json").read_text(encoding="utf-8")


_JSONC = '''{
  // комментарий пользователя — должен сохраниться
  "theme": "dark",
  "context_servers": {
    "mscodebase-intelligence": {
      "enabled": true,
      "command": "C:\\\\venv\\\\Scripts\\\\python.exe",
      "args": ["-u", "-m", "src.main"]
    },
    "other-server": {
      "enabled": true,
      "command": "python -m other"
    }
  },
  "context_servers_to_query": ["mscodebase-intelligence", "other-server"]
}
'''


def test_keep_to_query_removes_entry_keeps_query_and_comments(settings_dir):
    _write(settings_dir, _JSONC)
    assert zed_config.remove_zed_settings(keep_to_query=True) is True

    text = _read(settings_dir)
    data = zed_config.parse_jsonc(text)
    assert SERVER not in data["context_servers"]
    assert "other-server" in data["context_servers"]
    # query-список сохранён целиком (сервер резолвится из extension.toml)
    assert data["context_servers_to_query"] == [SERVER, "other-server"]
    # JSONC-комментарий и прочие настройки не тронуты
    assert "// комментарий пользователя" in text
    assert data["theme"] == "dark"


def test_uninstall_removes_entry_and_query(settings_dir):
    _write(settings_dir, _JSONC)
    assert zed_config.remove_zed_settings() is True

    data = zed_config.parse_jsonc(_read(settings_dir))
    assert SERVER not in data["context_servers"]
    assert data["context_servers_to_query"] == ["other-server"]


def test_noop_when_absent(settings_dir):
    _write(settings_dir, '{\n  "theme": "dark"\n}\n')
    assert zed_config.remove_zed_settings(keep_to_query=True) is True
    data = zed_config.parse_jsonc(_read(settings_dir))
    assert "context_servers" not in data


def test_missing_file_ok(settings_dir):
    assert zed_config.remove_zed_settings() is True


def test_corrupted_file_returns_false(settings_dir):
    _write(settings_dir, "{ this is not json !!")
    assert zed_config.remove_zed_settings() is False
