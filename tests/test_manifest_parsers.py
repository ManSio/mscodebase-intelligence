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


# ── фаза 1 (batch 2): go / cargo / maven / nuget / composer / gem ──────────

def test_go_mod_mux_no_require():
    entries = extract_manifest_entries(FIXT / "mux")
    assert not [e for e in entries if e.ecosystem == "go"]


def test_go_mod_migrate_require_and_indirect():
    pk = manifest_packages(FIXT / "migrate")
    assert "github.com/go-sql-driver/mysql" in pk  # прямой require
    assert "github.com/gorilla/mux" in pk           # indirect require-блок
    assert "gopkg.in/yaml.v3" in pk                # go.sum (транзитив)


def test_cargo_ripgrep_skips_path_deps():
    pk = manifest_packages(FIXT / "ripgrep")
    assert {"anyhow", "bstr", "serde_json", "serde", "walkdir", "tikv-jemallocator"} <= pk
    assert "grep" not in pk  # локальная workspace-крейта (path dep)


def test_maven_commons_lang():
    # commons-lang часто без прямых deps (берёт из parent) — валидно пустое;
    # главное: namespaced-pom парсится без урожая, и все maven-имена в groupId:artifactId
    entries = [e for e in extract_manifest_entries(FIXT / "commons-lang") if e.ecosystem == "maven"]
    assert all(":" in e.name for e in entries)


def test_nuget_csproj_package_reference():
    pk = manifest_packages(FIXT / "newtonsoft")
    assert "Microsoft.SourceLink.GitHub" in pk


def test_nuget_central_versions():
    pk = manifest_packages(FIXT / "eshoponweb")
    assert "Ardalis.ApiEndpoints" in pk
    assert "xunit" in pk


def test_composer_filters_php_and_ext():
    pk = manifest_packages(FIXT / "composer")
    assert "composer/ca-bundle" in pk
    assert "symfony/console" in pk
    assert "php" not in pk
    assert not any(k.startswith("ext-") for k in pk)


def test_gemfile_skips_gitpath():
    pk = manifest_packages(FIXT / "rspec-core")
    assert {"rake", "diff-lcs", "ffi", "rubocop", "simplecov"} <= pk
    assert "rspec" not in pk  # :git-локальный


# ── синтетика batch 2 ───────────────────────────────────────────────────────
def test_go_mod_synthetic_replace_excluded():
    from src.sources.manifest.extract import _extract_go_mod

    txt = (
        "module example.com/x\n\n"
        "go 1.21\n\n"
        "require (\n\tgithub.com/a/b v1.0.0\n\tgithub.com/c/d v0.0.0-2024-hash // indirect\n)\n\n"
        "replace github.com/a/b => github.com/other/b v1.9.9\n"
    )
    names = {e.name for e in _extract_go_mod(txt, "go.mod")}
    assert {"github.com/a/b", "github.com/c/d"} <= names
    assert not any(n == "github.com/other" for n in names)  # replace не зависимость


def test_pom_synthetic_scope_and_plugin_nested():
    from src.sources.manifest.extract import _extract_pom_xml

    txt = """<project>
      <dependencies>
        <dependency><groupId>org.foo</groupId><artifactId>bar</artifactId><version>1</version></dependency>
        <dependency><groupId>org.foo</groupId><artifactId>test-dep</artifactId><version>2</version><scope>test</scope></dependency>
      </dependencies>
      <plugin><artifactId>maven-x</artifactId><additionalDependencies>
        <dependency><groupId>skip</groupId><artifactId>me</artifactId></dependency>
      </additionalDependencies></plugin>
    </project>"""
    names = {e.name for e in _extract_pom_xml(txt, "pom.xml")}
    assert "org.foo:bar" in names
    assert "org.foo:test-dep" in names
    assert "skip:me" not in names


def test_cargo_synthetic_path_excluded():
    from src.sources.manifest.extract import _extract_cargo_toml

    txt = """[dependencies]
serde = "1.0"
local = { path = "crates/local" }
[target.'cfg(windows)'.dependencies]
winapi = "0.3"
"""
    names = {e.name for e in _extract_cargo_toml(txt, "Cargo.toml")}
    assert {"serde", "winapi"} <= names
    assert "local" not in names


def test_gemfile_synthetic_gitpath_skipped():
    from src.sources.manifest.extract import _extract_gemfile

    txt = (
        "source 'https://rubygems.org'\n"
        "gem 'rack', '~> 2.2'\n"
        "gem 'rails', :git => 'https://github.com/rails/rails.git'\n"
        "gem 'localdep', :path => '../localdep'\n"
    )
    names = {e.name for e in _extract_gemfile(txt, "Gemfile")}
    assert "rack" in names
    assert "rails" not in names
    assert "localdep" not in names
