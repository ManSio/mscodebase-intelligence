"""Backlog B-1 — манифест-парсеры: реальные фикстуры + edge-кейсы (Фаза 1 батча).

Корпус: experiments/universal-engine/e-s1-polygon/fixtures/ (read-only; ломаная
фикстура = править экстрактор, не фикстуру). Контракт: manifest_packages -> Set[str].
"""
from __future__ import annotations

from pathlib import Path

from src.sources.manifest import extract_manifest_entries, manifest_packages
from src.sources.manifest.extract import (
    _extract_package_json,
    _extract_pyproject,
    _extract_requirements,
)

FIXT = Path(__file__).resolve().parent.parent / "experiments" / "universal-engine" / "e-s1-polygon" / "fixtures"


# ── python ───────────────────────────────────────────────────────────────────

def test_uv_pyproject_dependency_groups_only():
    # uv pyproject НЕ имеет project.dependencies — только dependency-groups (PEP 735)
    pk = manifest_packages(FIXT / "uv")
    assert "black" in pk
    assert "mkdocs" in pk
    assert "ruff" in pk
    assert "rooster" in pk
    assert "maturin" not in pk  # build-system НЕ источник зависимостей проекта


def test_requests_pyproject_and_requirements_dev():
    pk = manifest_packages(FIXT / "requests")
    # project.dependencies (PEP 503 нормализация: underscore -> dash)
    assert "charset-normalizer" in pk
    assert "idna" in pk
    assert "urllib3" in pk
    assert "certifi" in pk
    # requirements-dev.txt (не только requirements*.txt glob)
    assert "pytest" in pk
    assert "pytest-httpbin" in pk
    assert "httpbin" in pk
    # editable `-e .[socks]` — локальный путь, НЕ пакет
    assert "charset_normalizer" not in pk  # underscore-форма нормирована в dash
    assert "junk-from-editable" not in pk


def test_pipfile():
    pk = manifest_packages(FIXT / "pipenv")
    assert "pytz" in pk  # [packages]
    assert "urllib3" in pk  # [dev-packages]
    assert "sphinx" in pk
    assert "myst-parser" in pk  # dict-спецификация с extras


# ── npm ──────────────────────────────────────────────────────────────────────

def test_express_package_json():
    pk = manifest_packages(FIXT / "express")
    assert "accepts" in pk
    assert "body-parser" in pk
    assert "after" in pk  # devDependencies
    assert "eslint" in pk


# ── экстракторы (синтетика / edge-кейсы из спеки 09) ────────────────────────

def test_requirements_editable_and_tilde():
    txt = "-e .[socks]\n--index-url https://x\nnumpy~=2.0\nvalidate-pyproject[all,store]>=0.25\n"
    names = {e.name for e in _extract_requirements(txt, "requirements.txt")}
    assert "numpy" in names
    assert "validate-pyproject" in names  # extras отброшены, name извлечён
    assert "requests" not in names  # -e .[socks] не дал пакета (локальный путь)
    assert "junk" not in names


def test_pyproject_optional_and_groups():
    txt = """\
[project]
dependencies = ["chardet>=3"]
optional-dependencies = { socks = ["PySocks>=1.5.6"] }
[dependency-groups]
test = { packages = ["pytest", "pytest-cov"] }
"""
    names = {e.name for e in _extract_pyproject(txt, "pyproject.toml")}
    assert {"chardet", "pysocks", "pytest", "pytest-cov"} <= names


def test_package_json_special_spec_values():
    # workspace/catalog/npm: alias — спец-спецификаторы не «версии», но имя — зависимость
    txt = """{"name":"x","dependencies":{
      "local-a":"workspace:*",
      "cataloged":"catalog:default",
      "aliased":"npm:esbuild-wasm@^0.23.0"
    }}"""
    names = {e.name for e in _extract_package_json(txt, "package.json")}
    assert {"local-a", "cataloged", "aliased"} <= names


def test_manifest_packages_is_set_of_str():
    pk = manifest_packages(FIXT / "express")
    assert all(isinstance(x, str) for x in pk)
    assert len(pk) > 0


def test_extract_entries_have_fields():
    entries = extract_manifest_entries(FIXT / "express")
    assert entries and entries[0].ecosystem == "npm"
    assert entries[0].kind == "manifest"
    assert entries[0].source == "package.json"
