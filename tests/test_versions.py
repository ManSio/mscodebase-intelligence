"""TEST-01 (audit): единый источник правды для версии проекта (§6.3).

pyproject.toml, extension.toml и src/__init__.py обязаны совпадать.
Рассинхрон ломает Zed extension lifecycle, диагностику и upgrade-сценарии
(аудит 2026-08: было 3 разные версии — 3.3.11 / 3.3.9 / 3.2.3).
"""

import re

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # Python 3.10 (CI matrix includes 3.10)
    import tomli as tomllib  # type: ignore[no-redef]
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_pyproject_version() -> str:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def _load_extension_toml_version() -> str:
    data = tomllib.loads((REPO / "extension.toml").read_text(encoding="utf-8"))
    return data["version"]


def _load_init_version() -> str:
    src = (REPO / "src" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', src)
    assert m, "src/__init__.py: __version__ not found"
    return m.group(1)


def test_pyproject_matches_extension_toml():
    assert _load_pyproject_version() == _load_extension_toml_version(), (
        "pyproject.toml и extension.toml рассинхронизированы"
    )


def test_pyproject_matches_init_version():
    assert _load_pyproject_version() == _load_init_version(), (
        "pyproject.toml и src/__init__.py рассинхронизированы"
    )
