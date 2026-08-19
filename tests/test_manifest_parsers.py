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
    from src.sources.manifest.extract import _extract_cargo_toml

    text = (FIXT / "ripgrep" / "Cargo.toml").read_text(encoding="utf-8", errors="replace")
    names = {e.name for e in _extract_cargo_toml(text, "Cargo.toml")}
    assert {"anyhow", "bstr", "serde_json", "serde", "walkdir", "tikv-jemallocator"} <= names
    # path-dep (локальная workspace-крейта) в МАНИФЕСТЕ исключён;
    # Cargo.lock же легитимно содержит все пакеты (в т.ч. workspace-крейты)
    assert "grep" not in names


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


# ── фаза 2: lockfile'ы (stdlib batch; yarn/pnpm follow-up) ──────────────────

def test_uv_lock_entries():
    from src.sources.manifest.extract import _extract_uv_lock

    text = (FIXT / "uv" / "uv.lock").read_text(encoding="utf-8", errors="replace")
    names = {e.name for e in _extract_uv_lock(text, "uv.lock")}
    assert "annotated-types" in names
    assert "annotated-doc" in names


def test_cargo_lock_transitive():
    entries = extract_manifest_entries(FIXT / "ripgrep")
    names = {e.name for e in entries}
    assert "aho-corasick" in names  # Cargo.lock (транзитивная)


def test_package_lock_v3():
    from src.sources.manifest.extract import _extract_package_lock

    text = (FIXT / "pkg-lock" / "package-lock-v3.json").read_text(encoding="utf-8", errors="replace")
    names = {e.name for e in _extract_package_lock(text, "package-lock.json")}
    assert "@pnpm.e2e/dep-of-pkg-with-1-dep" in names
    assert "@pnpm.e2e/pkg-with-1-dep" in names


def test_gemfile_lock_skips_path_project_gem():
    from src.sources.manifest.extract import _extract_gemfile_lock

    text = (FIXT / "fastlane" / "Gemfile.lock").read_text(encoding="utf-8", errors="replace")
    names = {e.name for e in _extract_gemfile_lock(text, "Gemfile.lock")}
    assert "faraday" in names  # GEM-секция резолвов


def test_gemfile_lock_synthetic_path_excluded():
    from src.sources.manifest.extract import _extract_gemfile_lock

    txt = ("PATH\n  remote: .\n  specs:\n    myproj (0.1.0)\n"
           "GEM\n  remote: https://x\n  specs:\n    rack (2.2.0)\n")
    names = {e.name for e in _extract_gemfile_lock(txt, "Gemfile.lock")}
    assert "rack" in names
    assert "myproj" not in names  # PATH remote: . — локальный проект-гем, не реестр


def test_manifest_packages_wiring_pyproject_plus_lock():
    # uv dir: dependency-groups (pyproject) + [[package]] (uv.lock) — оба источника
    pk = manifest_packages(FIXT / "uv")
    assert "black" in pk            # dependency-groups
    assert "annotated-types" in pk  # uv.lock


# ── фаза 2: синтетика lockfile ──────────────────────────────────────────────
def test_bun_lock_synthetic():
    from src.sources.manifest.extract import _extract_bun_lock

    txt = '{"packages":{"esbuild":["esbuild@0.21.5","",{},"s"],"@types/bun":["@types/bun@6.0.2","",{},"s"]}}'
    names = {e.name for e in _extract_bun_lock(txt, "bun.lock")}
    assert "esbuild" in names
    assert "@types/bun" in names


def test_pipfile_lock_synthetic():
    from src.sources.manifest.extract import _extract_pipfile_lock

    txt = '{"default":{"pytz":{"version":"==2024.1"}},"develop":{"pytest":{"version":"==8.0.0"}}}'
    names = {e.name for e in _extract_pipfile_lock(txt, "Pipfile.lock")}
    assert names == {"pytz", "pytest"}


def test_nuget_lock_synthetic():
    from src.sources.manifest.extract import _extract_nuget_lock

    txt = '{"version":1,"dependencies":{"net8.0":{"xunit":{"type":"Direct","resolved":"2.7.0"}}}}'
    names = {e.name for e in _extract_nuget_lock(txt, "packages.lock.json")}
    assert "xunit" in names


def test_composer_lock_synthetic():
    from src.sources.manifest.extract import _extract_composer_lock

    txt = ('{"packages":[{"name":"composer/ca-bundle","version":"1.5.0"}],'
           '"packages-dev":[{"name":"phpstan/phpstan","version":"1.11"}]}')
    names = {e.name for e in _extract_composer_lock(txt, "composer.lock")}
    assert {"composer/ca-bundle", "phpstan/phpstan"} <= names
