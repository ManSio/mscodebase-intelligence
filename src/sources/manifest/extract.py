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
from pathlib import Path
from typing import List, Set

from src.sources.manifest.model import (
    ManifestEntry,
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


# ── диспетчер ───────────────────────────────────────────────────────────────

_EXTRACTORS = [
    ("pyproject.toml", _extract_pyproject),
    ("Pipfile", _extract_pipfile),
    ("requirements*.txt", _extract_requirements),
    ("package.json", _extract_package_json),
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
