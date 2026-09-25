"""Тесты redact — вырезание credential-подобных строк на доставке.

Покрытие: каждая семья ключей вырезается; легитимные артефакты (хеш коммита, дайджест,
путь, версия, слово «key» в прозе) НЕ трогаются; assignment-эвристика; JSON остаётся валидным.
"""
import json

from src.core.redact import redact, redacted_count

# ── вырезание по семьям ──

def test_each_family_redacted():
    cases = {
        "aws-key": "AKIAIOSFODNN7EXAMPLE",
        "anthropic": "sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
        "openai": "sk-proj-" + "a" * 40,
        "github-token": "ghp_" + "A" * 40,
        "github-pat": "github_pat_" + "A" * 55,
        "slack": "xoxb-1234567890-abcdefghij",
        "google-key": "AIza" + "A" * 35,
        "stripe": "sk_live_" + "a" * 24,
        "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5NXg",
        "url-cred": "postgres://user:sup3rsecret@db.internal:5432/app",
        "bearer": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
    }
    for kind, sample in cases.items():
        out = redact(sample)
        assert sample not in out, f"{kind} not redacted"
        assert "[REDACTED:" in out, f"{kind} placeholder missing"


def test_private_key_block_redacted():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
    out = redact(pem)
    assert "MIIEow" not in out
    assert "[REDACTED:private-key]" in out


# ── сохранение легитимного ──

def test_legit_artifacts_survive():
    note = (
        "docs/readme.md:3 vs pyproject.toml:3\n"
        "commit 292d7945a1b2c3d4e5f60718293a4b5c6d7e8f90\n"
        "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08\n"
        "version 1.9.0 -> 2.0.0\n"
        "the key thing is the graph node is isolated\n"
        "path C:\\Users\\misha\\AppData\\Local\\Temp\\opencode\\e8\n"
    )
    out = redact(note)
    assert out == note


def test_assignment_heuristics():
    assert "abcdef1234567890abcd" not in redact('api_key = "abcdef1234567890abcd"')
    assert redact('api_key = "${MY_ENV_VAR}"') == 'api_key = "${MY_ENV_VAR}"'
    assert redact("password = /usr/local/secret/path") == "password = /usr/local/secret/path"
    assert redact("token = 1234567890") == "token = 1234567890"
    assert redact("token = your_token_here") == "token = your_token_here"


def test_counter_reports_kinds():
    out, counts = redacted_count("AKIAIOSFODNN7EXAMPLE and ghp_" + "A" * 40)
    assert counts.get("aws-key") == 1
    assert counts.get("github-token") == 1
    assert "AKIA" not in out


# ── безопасность интеграции ──

def test_redacted_json_stays_valid():
    payload = json.dumps({"ok": True, "result": "token sk-ant-api03-" + "b" * 30})
    red, counts = redacted_count(payload)
    assert counts
    parsed = json.loads(red)  # не должно упасть
    assert parsed["ok"] is True
    assert "sk-ant" not in red


def test_non_string_passthrough():
    assert redact(None) is None
    assert redact(123) == 123
    assert redact("") == ""


def test_cli_redacts_tool_output(monkeypatch, capsys):
    import src.cli as cli_mod

    secret = "sk-ant-api03-" + "c" * 30

    class _FakeTool:
        def __init__(self, services):
            self.services = services

        def execute(self, **kwargs):
            return f"note carrying a key {secret} and path src/core/redact.py"

    monkeypatch.setattr(cli_mod, "core_tool_allowlist", lambda: {"fake": _FakeTool})
    monkeypatch.setattr(cli_mod, "create_service_collection", lambda root: None)

    rc = cli_mod.main(["fake", "{}"])
    captured = capsys.readouterr()
    assert rc == 0
    assert secret not in captured.out
    assert "[REDACTED:anthropic]" in captured.out
    assert "src/core/redact.py" in captured.out  # путь сохранён
    assert "redacted" in captured.err

