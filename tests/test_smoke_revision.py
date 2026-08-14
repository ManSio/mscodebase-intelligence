"""get_revision() из scripts/smoke_e2e.py — привязка smoke-отчёта к git HEAD
(policy_binding-аналог, OWP). subprocess мокается — тест не зависит от окружения."""
import importlib.util
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "scripts" / "smoke_e2e.py"


def _load_smoke():
    spec = importlib.util.spec_from_file_location("smoke_e2e_mod", SMOKE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeProc:
    def __init__(self, stdout: bytes = b"", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def test_revision_clean():
    mod = _load_smoke()
    with mock.patch(
        "subprocess.run",
        side_effect=[_FakeProc(b"abc123def\n"), _FakeProc(b"")],
    ):
        assert mod.get_revision() == "abc123def"


def test_revision_dirty():
    mod = _load_smoke()
    with mock.patch(
        "subprocess.run",
        side_effect=[_FakeProc(b"abc123def\n"), _FakeProc(b" M src/main.py\n")],
    ):
        assert mod.get_revision() == "abc123def (dirty)"


def test_revision_unknown_on_error():
    mod = _load_smoke()
    with mock.patch("subprocess.run", side_effect=RuntimeError("git missing")):
        assert mod.get_revision() == "unknown"
