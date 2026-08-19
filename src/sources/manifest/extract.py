"""Экстракторы манифестов (Backlog B-1, ADR-0005 scaling).

Фаза 1 (первый батч): python (pyproject.toml с dependency-groups/Pipfile/
requirements*.txt) + npm (package.json). Диспетчер — по имени файла; расширяемо
на go/cargo/maven/nuget/composer/gem и lockfile'ы (фаза 2).

Контракт ADR-0005: manifest_packages(root) -> Set[str] норм. имён (closed-world);
спека версий НЕ парсится в фазе 1 (spec строкой). Ловушки (09-selfcheck):
uv pyproject БЕЗ project.dependencies (только dependency-groups); `-e ` в
requirements; PEP 503-нормализация python-имён.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Set

from src.sources.manifest.model import (
    ManifestEntry,
    normalize_dotted,
    normalize_npm,
    normalize_python,
)

try:  # Python >= 3.11
    import tomllib
except ImportError:  # 3.10 — tomli fallback (если есть)
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

_PEP508_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
_EDITS = ("-e ", "--editable ", "-r ", "-c ")


def _req_name(spec: str):
    s = spec.strip()
    for prefix in _EDITS:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    if s.startswith(("http:", "https:", "git+", "git@", "file:")):
        return None
    m = _PEP508_RE.match(s)
    if not m:
        return None
    return m.group(0).split("[", 1)[0]  # отбросить extras [..]


def _toml(text: str):
    if tomllib is None:
        return None
    try:
        return tomllib.loads(text)
    except Exception:  # noqa: BLE001 — любой сбой парсинга = не манифест
        return None


# ── python ──────────────────────────────────────────────────────────────────

def _extract_pyproject(text: str, source: str) -> List[ManifestEntry]:
    data = _toml(text)
    if data is None:
        return []
    entries: List[ManifestEntry] = []

    def add(spec: str) -> None:
        n = _req_name(spec)
        if n:
            entries.append(
                ManifestEntry("python", normalize_python(n), spec.strip(), "manifest", source)
            )

    proj = data.get("project", {}) or {}
    for spec in proj.get("dependencies", []) or []:
        add(spec)
    for specs in (proj.get("optional-dependencies", {}) or {}).values():
        for spec in specs or []:
            add(spec)
    # PEP 735 dependency-groups (uv может БЫТЬ единственным источником — без project.dependencies)
    for specs in (data.get("dependency-groups", {}) or {}).values():
        if isinstance(specs, list):
            for spec in specs:
                add(spec)
        elif isinstance(specs, dict) and "packages" in specs:
            for spec in specs["packages"] or []:
                add(spec)
    return entries


def _extract_requirements(text: str, source: str) -> List[ManifestEntry]:
    entries: List[ManifestEntry] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(("#", "-", "--")):
            continue
        n = _req_name(line)
        if n:
            entries.append(ManifestEntry("python", normalize_python(n), line, "manifest", source, i))
    return entries


def _extract_pipfile(text: str, source: str) -> List[ManifestEntry]:
    data = _toml(text)
    if data is None:
        return []
    entries: List[ManifestEntry] = []
    for key in ("packages", "dev-packages"):
        sec = data.get(key, {}) or {}
        if not isinstance(sec, dict):
            continue
        for name, spec in sec.items():
            if isinstance(spec, dict):
                spec_str = ", ".join(f"{k}={v}" for k, v in spec.items())
            else:
                spec_str = str(spec)
            entries.append(ManifestEntry("python", normalize_python(str(name)),
                                         spec_str, "manifest", source))
    return entries


# ── npm ─────────────────────────────────────────────────────────────────────

def _extract_package_json(text: str, source: str) -> List[ManifestEntry]:
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, dict):
        return []
    entries: List[ManifestEntry] = []
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps = data.get(key, {}) or {}
        if not isinstance(deps, dict):
            continue
        for name, spec in deps.items():
            entries.append(
                ManifestEntry("npm", normalize_npm(str(name)), str(spec), "manifest", source)
            )
    return entries


# ── go ──────────────────────────────────────────────────────────────────────

_GO_REQ = re.compile(r"^([\w./-]+)\s+(v?[\w.+\-]+)")


def _extract_go_mod(text: str, source: str) -> List[ManifestEntry]:
    """go.mod: require-блоки (несколько) + одиночные require.

    replace/инструменты НЕ зависимости; имя=модуль-путь; версия может быть
    псевдоверсией. Комментарии `// indirect` отсекаются (split по // перед парсом).
    """
    entries: List[ManifestEntry] = []
    in_require = False
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        if line == "require (":
            in_require = True
            continue
        if line == ")":
            in_require = False
            continue
        if in_require:
            m = _GO_REQ.match(line)
            if m:
                entries.append(ManifestEntry("go", m.group(1), f"{m.group(1)} {m.group(2)}",
                                             "manifest", source, i))
        elif line.startswith("require "):
            m = _GO_REQ.match(line[len("require "):].strip())
            if m:
                entries.append(ManifestEntry("go", m.group(1), f"{m.group(1)} {m.group(2)}",
                                             "manifest", source, i))
    return entries


def _extract_go_sum(text: str, source: str) -> List[ManifestEntry]:
    """go.sum: строки `<mod> <v> h1:…` (name=первый токен, v=второй, без /go.mod)."""
    entries: List[ManifestEntry] = []
    seen = set()
    for i, raw in enumerate(text.splitlines(), start=1):
        parts = raw.split()
        if len(parts) < 2:
            continue
        name, ver = parts[0], parts[1]
        if ver.endswith("/go.mod"):
            ver = ver[:-len("/go.mod")]
        if (name, ver) in seen:
            continue
        seen.add((name, ver))
        entries.append(ManifestEntry("go", name, ver, "lockfile", source, i))
    return entries


# ── cargo ────────────────────────────────────────────────────────────────────

def _extract_cargo_toml(text: str, source: str) -> List[ManifestEntry]:
    data = _toml(text)
    if data is None:
        return []
    entries: List[ManifestEntry] = []

    def collect(table) -> None:
        if not isinstance(table, dict):
            return
        for name, spec in table.items():
            if isinstance(spec, dict):
                if "path" in spec:
                    continue  # локальная крейта workspace, не реестр
                entries.append(ManifestEntry(
                    "cargo", normalize_dotted(str(name)),
                    str(spec.get("version") or spec.get("git") or ""),
                    "manifest", source))
            elif isinstance(spec, str):
                entries.append(ManifestEntry("cargo", normalize_dotted(str(name)),
                                             spec, "manifest", source))

    for key in ("dependencies", "dev-dependencies", "build-dependencies"):
        collect(data.get(key, {}))
    targets = data.get("target", {})
    if isinstance(targets, dict):
        for tbl in targets.values():
            if isinstance(tbl, dict):
                collect(tbl.get("dependencies", {}))
    return entries


# ── maven / nuget (XML) ─────────────────────────────────────────────────────

def _text(el, tag):
    for child in (el.find(tag) or []):
        return child.text
    return ""


def _ltag(el):
    return el.tag.split("}", 1)[-1]


def _find_local(el, tag):
    for child in el:
        if _ltag(child) == tag:
            return child
    return None


def _findall_local(el, tag):
    return [c for c in el if _ltag(c) == tag]


def _extract_pom_xml(text: str, source: str) -> List[ManifestEntry]:
    """maven: только project/dependencies и dependencyManagement→dependency.

    Local-tag (namespaced XML); обход не заходит в plugin.additionalDependencies
    (идет под project/build/plugins/plugin, не прямой child dependencies).
    scope=test-зависимости включаем (все равно зависимости проекта).
    """
    try:
        root = ET.fromstring(text)
    except Exception:  # noqa: BLE001
        return []
    entries: List[ManifestEntry] = []
    containers = _findall_local(root, "dependencies")
    dm = _find_local(root, "dependencyManagement")
    if dm is not None:
        containers += _findall_local(dm, "dependencies")
    for container in containers:
        for dep in _findall_local(container, "dependency"):
            g = _find_local(dep, "groupId")
            a = _find_local(dep, "artifactId")
            if g is None or not (g.text or "").strip() or a is None or not (a.text or "").strip():
                continue
            v = _find_local(dep, "version")
            name = f"{g.text.strip()}:{a.text.strip()}"
            entries.append(ManifestEntry(
                "maven", normalize_dotted(name),
                (v.text or "").strip() if v is not None else "", "manifest", source))
    return entries


def _extract_csproj(text: str, source: str) -> List[ManifestEntry]:
    """nuget: <PackageReference Include=... Version=.../> (exclude ProjectReference)."""
    try:
        root = ET.fromstring(text)
    except Exception:  # noqa: BLE001
        return []
    entries: List[ManifestEntry] = []
    for ref in root.iter("PackageReference"):
        inc = ref.get("Include")
        if inc:
            entries.append(ManifestEntry("nuget", inc.strip(),
                                         (ref.get("Version") or ""), "manifest", source))
    return entries


def _extract_nuget_central(text: str, source: str) -> List[ManifestEntry]:
    """nuget централизованного управления версиями: <PackageVersion Include=.../>."""
    try:
        root = ET.fromstring(text)
    except Exception:  # noqa: BLE001
        return []
    entries: List[ManifestEntry] = []
    for pv in root.iter("PackageVersion"):
        inc = pv.get("Include")
        if inc:
            entries.append(ManifestEntry("nuget", inc.strip(),
                                         (pv.get("Version") or ""), "manifest", source))
    return entries


# ── composer / gem ───────────────────────────────────────────────────────────

def _extract_composer_json(text: str, source: str) -> List[ManifestEntry]:
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, dict):
        return []
    entries: List[ManifestEntry] = []
    for key in ("require", "require-dev"):
        sec = data.get(key, {}) or {}
        if not isinstance(sec, dict):
            continue
        for name, spec in sec.items():
            if name == "php" or name.startswith("ext-") or name.startswith("lib-"):
                continue  # не пакеты (спека 09 п.10)
            entries.append(ManifestEntry("composer", normalize_dotted(name), str(spec),
                                         "manifest", source))
    return entries


_GEM_RE = re.compile(r"gem\s+['\"]([^'\"]+)['\"]")


def _extract_gemfile(text: str, source: str) -> List[ManifestEntry]:
    """Gemfile — Ruby-код: ловим литеральные `gem 'name'`, отбрасываем :git/:path."""
    entries: List[ManifestEntry] = []
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":git" in line or ":path" in line:
            continue  # git/path-локальные — не реестр
        m = _GEM_RE.search(line)
        if not m:
            continue
        name = m.group(1)
        after = line[m.end():]
        m2 = re.search(r"['\"]([^'\"]+)['\"]", after)
        spec = m2.group(1) if m2 else ""
        entries.append(ManifestEntry("gem", normalize_dotted(name), spec, "manifest", source, i))
    return entries


# ── диспетчер ───────────────────────────────────────────────────────────────┐

_EXTRACTORS = [
    ("pyproject.toml", _extract_pyproject),
    ("Pipfile", _extract_pipfile),
    ("requirements*.txt", _extract_requirements),
    ("package.json", _extract_package_json),
    ("go.mod", _extract_go_mod),
    ("go.sum", _extract_go_sum),
    ("Cargo.toml", _extract_cargo_toml),
    ("pom.xml", _extract_pom_xml),
    ("*.csproj", _extract_csproj),
    ("Directory.Packages.props", _extract_nuget_central),
    ("composer.json", _extract_composer_json),
    ("Gemfile", _extract_gemfile),
]


def extract_manifest_entries(root: Path) -> List[ManifestEntry]:
    """Собирает ManifestEntry из всех известных манифестов в root (без рекурсии)."""
    entries: List[ManifestEntry] = []
    for pattern, fn in _EXTRACTORS:
        for f in sorted(root.glob(pattern)):
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            entries.extend(fn(text, f.name))
    return entries


def manifest_packages(root: Path) -> Set[str]:
    """Множество норм. имён зависимостей (контракт ADR-0005, closed-world)."""
    return {e.name for e in extract_manifest_entries(root) if e.name}
