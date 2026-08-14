"""
ADR-0003 Verify-On-Read — Lazy Validation Layer для Project Memory.

Ленивая проверка узлов при ИЗВЛЕЧЕНИИ (retrieval), до формирования системного
промпта. Вектор проверки смещён с момента отклика/записи на момент чтения:
`intel_get_project_memory` (хук в layer.py) пропускает узлы через этот слой.

Правила (ADR-0003, решения владельца 2026-08-11):
- Узлы с checkable-якорями (`file:`/`import:`/`env:`/`pkg:`) сверяются с кодовой базой:
  * все якоря найдены -> VERIFIED (persist);
  * прямое отрицательное тестирование якоря (указан, но не существует)
    -> REFUTED с причиной SILENT_ABSENCE_ON_READ (persist, retract_source);
  * якорей нет (внешнее окружение/предпочтения) -> INCONCLUSIVE, статус
    сохраняется (ACTIVE/VERIFIED) — предохранитель от ложных отзывов
    истинных фактов, не оставляющих следов в рабочей директории.
- Кэш вердиктов: ключ = hash(node_id + commit_sha) (git rev-parse HEAD;
  fallback — максимальный mtime src-дерева). Неизменившийся репозиторий
  не перепроверяется (cache hit ~0ms); смена HEAD естественно инвалидирует
  ТОЛЬКО свои записи (per-node keying, без TTL) -> повторная проверка узла
  при следующем чтении (исключает stale-VERIFIED).
- Бюджет латентности: <= budget_ms на весь проход; при превышении
  необработанные узлы остаются как есть (INCONCLUSIVE-семантика) и передаются
  в контекст без отзыва (graceful degradation).
- Отпечаток кодовой базы (импорты/файлы/env-ключи) строится один раз на HEAD
  и переиспользуется между процессами через verify_cache.json. Первое чтение
  после смены кода платит rebuild (~<=500ms); steady-state — cache hit ~0ms.

Аудит: авто-отзывы пишутся тем же путём, что ручные (retract_reason,
retracted_at) + маркер retract_source="verify_on_read" и имя проваленного
якоря в причине.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

if os.name == "nt":
    import subprocess as _sp

    _CREATE_NO_WINDOW = getattr(_sp, "CREATE_NO_WINDOW", 0)
else:
    _CREATE_NO_WINDOW = 0

logger = logging.getLogger("MSCodeBase.Intelligence.VerifyOnRead")

REASON_SILENT_ABSENCE = "SILENT_ABSENCE_ON_READ"
RETRACT_SOURCE = "verify_on_read"

VERDICT_FOUND = "FOUND"
VERDICT_NOT_FOUND = "NOT_FOUND"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"

STATUS_ACTIVE = "ACTIVE"
STATUS_VERIFIED = "VERIFIED"
STATUS_REFUTED = "REFUTED"
STATUS_SUPERSEDED = "SUPERSEDED"

DEFAULT_BUDGET_MS = 50.0
CACHE_FILENAME = "verify_cache.json"
HEAD_TTL_SEC = 30.0  # пере-резолв HEAD не чаще раза в 30с на инстанс (git ~50-100ms)

# ── Лёгкие regex-якоря (без LLM) ──
# Для сканирования исходников: импорты на строке (реальный код).
_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE)
# Для текста claim: "import X" в любой позиции, "from X import Y" целиком.
_TEXT_IMPORT_RE = re.compile(r"\bimport\s+([a-zA-Z_][a-zA-Z0-9_.]*)")
_TEXT_FROM_RE = re.compile(r"\bfrom\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+import\b")
_ENV_PREFIX_RE = re.compile(r"(?:env:|\$)([A-Z][A-Z0-9_]{2,})")
_FILE_PREFIX_RE = re.compile(r"file:([^\s`'\";,]+)")
_PATH_RE = re.compile(r"\b(?:src/)?([\w.-]+[/\\\\][\w./\\\\-]+)\.(?:py|toml|json|md|yaml|yml|ini|cfg|env|db)\b")
# ADR-0005: явный синтаксис pkg:name и прозa-слово-кандидат (write-path capture).
_PKG_PREFIX_RE = re.compile(r"\bpkg:([A-Za-z0-9_.-]+)")
_PKG_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")

# tomllib (3.11+) / tomli (3.10, dev-deps проекта). None — строковый fallback.
try:
    import tomllib  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - Python 3.10
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


def _norm_pkg(name: str) -> str:
    """PEP 503 нормализация имени пакета: lowercase, `-_.` -> `-`, срез extras."""
    name = name.split("[", 1)[0].strip()
    return re.sub(r"[-_.]+", "-", name.lower())


def _req_name(req: Any) -> str:
    """Имя из PEP 508 requirement-строки (до specifier/extra/marker)."""
    if not isinstance(req, str):
        return ""
    name = re.split(r"[\s<>=!~;\[\]]", req.strip(), maxsplit=1)[0]
    return _norm_pkg(name) if name else ""


def _pyproject_packages(text: str) -> Set[str]:
    """Имена пакетов из pyproject.toml (закрытый мир для pkg:-якорей)."""
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except Exception as exc:  # noqa: BLE001 - любой сбой парсинга — пустое множество
            logger.debug("verify_on_read: pyproject parse failed: %s", exc)
            return set()
        names: Set[str] = set()
        project = data.get("project") or {}
        for key in ("dependencies", "dev-dependencies"):
            for req in project.get(key) or []:
                name = _req_name(req)
                if name:
                    names.add(name)
        for reqs in (project.get("optional-dependencies") or {}).values():
            for req in reqs or []:
                name = _req_name(req)
                if name:
                    names.add(name)
        for reqs in (data.get("dependency-groups") or {}).values():
            for req in reqs or []:
                name = _req_name(req)
                if name:
                    names.add(name)
        return names
    # Fallback без tomllib/tomli: строки внутри dependencies-блоков.
    names_fallback: Set[str] = set()
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if (
            line.startswith("dependencies")
            or line.startswith("dev-dependencies")
            or (line.startswith("[project.") and "dependencies" in line)
            or line.startswith("dependency-groups")
        ):
            in_block = "[" in line
            continue
        if in_block:
            if line.startswith("]") or line.startswith("}"):
                in_block = False
                continue
            m = re.search(r'"([^"]+)"', line)
            if m:
                name = _req_name(m.group(1))
                if name:
                    names_fallback.add(name)
    return names_fallback


def _requirements_packages(text: str) -> Set[str]:
    """Имена пакетов из requirements[-lock].txt (по строке, `name==x` и т.п.)."""
    names: Set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-", "--")):
            continue
        name = _req_name(line)
        if name and not name.startswith(("http:", "https:", "git+")):
            names.add(name)
    return names


def _load_manifest_packages(root: Path) -> Set[str]:
    """Множество зависимостей проекта из манифестов (ADR-0005, closed world)."""
    packages: Set[str] = set()
    for fname in ("pyproject.toml", "requirements.txt", "requirements-lock.txt"):
        p = root / fname
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if fname == "pyproject.toml":
            packages |= _pyproject_packages(text)
        else:
            packages |= _requirements_packages(text)
    return packages


class Anchor:
    """Checkable-якорь узла: что именно проверяется в кодовой базе."""

    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str):
        self.kind = kind  # "file" | "import" | "env" | "pkg"
        self.value = value

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Anchor({self.kind}:{self.value})"

    def to_dict(self) -> Dict[str, str]:
        return {"kind": self.kind, "value": self.value}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Anchor":
        return cls(str(d.get("kind", "")), str(d.get("value", "")))


def extract_anchors(
    node: Dict[str, Any], project_root: Optional[Path] = None
) -> List[Anchor]:
    """Извлекает checkable-якоря из data/claim узла (лёгкий regex, без LLM).

    Приоритет: явные `data.anchors` (пишутся при записи узла), затем синтаксис
    в тексте claim/data: `file:path`, `import X` / `from X import y`,
    `env:KEY` / `$KEY`, `pkg:name` (ADR-0005, закрытый мир манифеста),
    пути с разделителями и расширением.

    Write-path (project_root задан): file-якоря фильтруются по существованию;
    слова прозы, совпадающие с зависимостями манифеста, становятся pkg:-якорями
    (fail-closed — слова вне манифеста якорем не становятся).

    project_root (write-path, P2-фикс): при передаче file-якоря, которых нет
    относительно корня, отбрасываются — вольный текст коммитов даёт мусор
    (слепленные пути «pyproject/extension.toml/__init__.py», относительные
    «queries/__init__.py», завершающая пунктуация «__init__.py.»), а fail-closed
    _classify превращает его в ЛОЖНЫЙ REFUTED. Read-path (None) — все якоря
    классифицируются честно: удалённый файл = дрейф → REFUTED (фильтр не
    отключает детекцию дрейфа).
    """
    anchors: List[Anchor] = []
    seen: Set[Tuple[str, str]] = set()

    def _add(kind: str, value: str) -> None:
        value = value.strip().strip("`'\"")
        # Обрезка завершающей пунктуации: "src/.../__init__.py." -> ".../__init__.py"
        value = value.rstrip(".,;:!?)]}")
        if not value:
            return
        # P2: write-path хранит только существующие файлы (мусор из текста — мимо)
        if kind == "file" and project_root is not None:
            if not (project_root / value).is_file():
                return
        key = (kind, value)
        if key not in seen:
            seen.add(key)
            anchors.append(Anchor(kind, value))

    # ADR-0005: write-path читает манифест для pkg:-capture (fail-closed).
    pkg_pool: Optional[Set[str]] = None
    if project_root is not None:
        pkg_pool = _load_manifest_packages(project_root)

    data = node.get("data") or {}
    if isinstance(data, dict):
        raw_anchors = data.get("anchors")
        if isinstance(raw_anchors, list):
            for a in raw_anchors:
                if isinstance(a, dict) and a.get("kind") in ("file", "import", "env", "pkg"):
                    _add(str(a["kind"]), str(a.get("value", "")))
        parts: List[str] = []
        claim = data.get("claim") or ""
        if claim:
            parts.append(str(claim))
        for v in data.values():
            if isinstance(v, str) and v != claim:
                parts.append(v)
        text = "\n".join(parts)
    elif isinstance(data, str):
        text = data
    else:
        text = ""

    for m in _FILE_PREFIX_RE.finditer(text):
        _add("file", m.group(1))
    for m in _PATH_RE.finditer(text):
        value = m.group(0)
        # Абсолютные/вложенные пути (drive-буква C:\, сегменты a\b\c, URL-схемы)
        # — не проектные якоря: проверка идёт относительно корня проекта (ADR-0003).
        if "://" in value or (m.start() > 0 and text[m.start() - 1] in (":", "\\", "/")):
            continue
        _add("file", value)
    for m in _TEXT_IMPORT_RE.finditer(text):
        _add("import", m.group(1))
    for m in _TEXT_FROM_RE.finditer(text):
        _add("import", m.group(1))
    for m in _PKG_PREFIX_RE.finditer(text):
        _add("pkg", m.group(1))
    for m in _ENV_PREFIX_RE.finditer(text):
        _add("env", m.group(1))
    # Write-path (ADR-0005): слово прозы, чьё нормализованное имя есть в манифесте,
    # становится pkg:-якорем. Fail-closed: слова НЕ в манифесте якорем не становятся
    # (нет ложного REFUTED для исторических «мы перешли с X»). Read-path — только
    # явный `pkg:` синтаксис (без present-trap).
    if pkg_pool:
        for m in _PKG_WORD_RE.finditer(text):
            word = m.group(0)
            if len(word) >= 2 and _norm_pkg(word) in pkg_pool:
                _add("pkg", word)
    return anchors


class _Fingerprint:
    """Отпечаток кодовой базы: root-импорты, файлы, env-ключи (один раз на HEAD)."""

    def __init__(self, root: Optional[Path] = None, data: Optional[Dict[str, Any]] = None):
        if data is not None:
            self.imports: Set[str] = set(data.get("imports", []))
            self.files: Set[str] = set(data.get("files", []))
            self.env_keys: Set[str] = set(data.get("env_keys", []))
            # ADR-0005: старый кэш без "packages" пересобирается (schema guard в
            # _ensure_fingerprint) — пустой набор здесь привёл бы к ложным REFUTED.
            self.packages: Set[str] = set(data.get("packages", []))
            self.build_ms: float = 0.0
            return
        if root is None:
            root = Path()
        t0 = time.perf_counter()
        imports: Set[str] = set()
        files: Set[str] = set()
        src = root / "src"
        if src.is_dir():
            for p in src.rglob("*"):
                if not p.is_file() or "__pycache__" in p.parts:
                    continue
                rel = p.relative_to(root).as_posix()
                files.add(rel)
                if p.suffix == ".py":
                    try:
                        text = p.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    for m in _IMPORT_RE.finditer(text):
                        imports.add(m.group(1).split(".")[0])
        env_keys: Set[str] = set()
        if root is not None:
            for name in (".env", ".env.example"):
                ep = root / name
                if ep.is_file():
                    try:
                        for line in ep.read_text(encoding="utf-8", errors="replace").splitlines():
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                env_keys.add(line.split("=", 1)[0].strip())
                    except OSError:
                        continue
        self.imports = imports
        self.files = files
        self.env_keys = env_keys
        # ADR-0005: закрытый мир зависимостей (pyproject/requirements[-lock]).
        self.packages = _load_manifest_packages(root) if root is not None else set()
        self.build_ms = (time.perf_counter() - t0) * 1000.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "imports": sorted(self.imports),
            "files": sorted(self.files),
            "env_keys": sorted(self.env_keys),
            "packages": sorted(self.packages),
            "build_ms": round(self.build_ms, 1),
        }


class VerifyOnRead:
    """Lazy Validation Layer (ADR-0003): фильтрация + переходы статусов при чтении.

    Один экземпляр на проект (см. `get_verifier`) — разделяет HEAD/отпечаток/кэш
    между вызовами; переходы пишутся под тем же `write_lock`, что и ручные
    операции памяти.
    """

    def __init__(
        self,
        project_root: Path,
        store: Any,
        write_lock: Any,
        cache_file: Optional[Path] = None,
    ):
        self.root = project_root
        self.store = store
        self.lock = write_lock
        if cache_file is None:
            from src.core.artifact_paths import get_intelligence_dir

            cache_file = get_intelligence_dir(project_root) / CACHE_FILENAME
        self.cache_file = cache_file
        self._head: Optional[str] = None
        self._fingerprint: Optional[_Fingerprint] = None
        self._cache: Dict[str, Any] = {"head": None, "fingerprint": None, "verdicts": {}}
        self._head_cache: Dict[str, Any] = {"head": None, "ts": 0.0}
        self._load_cache()

    # ── HEAD и отпечаток ──

    def _resolve_head(self) -> str:
        """HEAD с TTL-кэшем: git-подпроцесс не вызывается на каждом чтении.

        steady-state чтение (~0ms) — ключ не пересоздаётся; смена кода
        детектится в пределах HEAD_TTL_SEC (пере-резолв), затем per-node
        инвалидация по новому ключу.
        """
        now = time.monotonic()
        cached_head = self._head_cache.get("head")
        if cached_head and now - self._head_cache.get("ts", 0.0) < HEAD_TTL_SEC:
            return str(cached_head)
        head = self._resolve_head_impl()
        self._head_cache = {"head": head, "ts": now}
        return head

    def _resolve_head_impl(self) -> str:
        """git rev-parse HEAD (Popen+communicate, timeout); fallback — mtime src."""
        try:
            proc = subprocess.Popen(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.root),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW,
            )
            out, _ = proc.communicate(timeout=5)
            if proc.returncode == 0:
                return out.decode("utf-8", "replace").strip()[:40]
        except Exception as exc:  # noqa: BLE001 - любой сбой git — fallback
            logger.debug("verify_on_read: git rev-parse failed: %s", exc)
        max_m = 0
        src = self.root / "src"
        if src.is_dir():
            for p in src.rglob("*"):
                try:
                    max_m = max(max_m, p.stat().st_mtime_ns)
                except OSError:
                    continue
        return f"mtime:{max_m}"

    def _ensure_fingerprint(self, head: str) -> _Fingerprint:
        if self._fingerprint is not None and self._head == head:
            return self._fingerprint
        cached_fp = self._cache.get("fingerprint")
        # ADR-0005 schema guard: кэш без "packages" (докэшовая версия) пересобирается,
        # иначе пустой packages ложно REFUTED'ил бы все pkg:-якоря.
        if self._cache.get("head") == head and isinstance(cached_fp, dict) and "packages" in cached_fp:
            self._fingerprint = _Fingerprint(data=cached_fp)
        else:
            self._fingerprint = _Fingerprint(root=self.root)
        self._head = head
        self._cache["head"] = head
        return self._fingerprint

    # ── Кэш вердиктов ──

    @staticmethod
    def _cache_key(node_id: str, head: str) -> str:
        return hashlib.sha256(f"{node_id}|{head}".encode("utf-8")).hexdigest()[:16]

    def _load_cache(self) -> None:
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._cache = data
                self._cache.setdefault("verdicts", {})
        except (OSError, json.JSONDecodeError):
            self._cache = {"head": None, "fingerprint": None, "verdicts": {}}

    def _persist_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            head = self._cache.get("head")
            verdicts = {
                k: v for k, v in self._cache.get("verdicts", {}).items()
                if v.get("head") == head  # per-node инвалидация по HEAD
            }
            payload = {
                "head": head,
                "fingerprint": self._fingerprint.to_dict() if self._fingerprint else None,
                "verdicts": verdicts,
            }
            self.cache_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("verify_on_read: cache persist failed: %s", exc)

    # ── Проверка якорей ──

    def _check_anchor(self, anchor: Anchor, fp: _Fingerprint) -> bool:
        if anchor.kind == "file":
            target = self.root / anchor.value
            return target.is_file() or anchor.value in fp.files
        if anchor.kind == "import":
            return anchor.value.split(".")[0] in fp.imports
        if anchor.kind == "env":
            return anchor.value in fp.env_keys
        if anchor.kind == "pkg":
            # ADR-0005: closed-world — манифест это источник правды для зависимостей.
            return _norm_pkg(anchor.value) in fp.packages
        return False

    def _classify(self, anchors: List[Anchor], fp: _Fingerprint) -> Tuple[str, Optional[str]]:
        """Вердикт: FOUND / NOT_FOUND(+проваленный якорь) / INCONCLUSIVE."""
        if not anchors:
            return VERDICT_INCONCLUSIVE, None
        for a in anchors:
            if not self._check_anchor(a, fp):
                return VERDICT_NOT_FOUND, f"{a.kind}:{a.value}"
        return VERDICT_FOUND, None

    # ── Применение переходов (общий write-путь, тот же lock) ──

    def _persist_transitions(self, transitions: List[Dict[str, Any]]) -> None:
        if not transitions:
            return
        with self.lock:
            nodes = self.store._load_json("project_memory.json")
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            by_id = {n.get("node_id"): n for n in nodes if isinstance(n, dict)}
            changed = False
            for tr in transitions:
                n = by_id.get(tr["node_id"])
                if n is None:
                    continue
                # Терминальные статусы (REFUTED/SUPERSEDED) verify-on-read'ом не
                # переписываются: отозванное/заменённое остаётся в истории.
                # Без этого guard'а SUPERSEDED-узел с живыми якорями был бы
                # молча откачен в VERIFIED (откат терминального статуса).
                if n.get("status") in (STATUS_REFUTED, STATUS_SUPERSEDED):
                    continue
                if tr["status"] == STATUS_REFUTED:
                    n["status"] = STATUS_REFUTED
                    n["retract_reason"] = tr["reason"]
                    n["retracted_at"] = now
                    n["retract_source"] = RETRACT_SOURCE
                    logger.info(
                        "verify_on_read: REFUTED %s (%s)", tr["node_id"], tr["reason"]
                    )
                elif n.get("status") in (None, STATUS_ACTIVE):
                    # VERIFIED-переход только для ACTIVE/без статуса — legacy-узлы
                    # интерпретируются как ACTIVE (ADR-0002); прочие статусы не трогаем.
                    n["status"] = STATUS_VERIFIED
                    n["verified_at"] = now
                changed = True
            if changed:
                self.store._save_json("project_memory.json", nodes)

    # ── Основной проход ──

    def run(
        self,
        memory: Dict[str, List[Dict]],
        budget_ms: float = DEFAULT_BUDGET_MS,
    ) -> Tuple[Dict[str, List[Dict]], Dict[str, Any]]:
        """Проверяет ACTIVE/VERIFIED узлы, применяет переходы, возвращает фильтры.

        Returns:
            (memory с исключёнными новыми REFUTED, stats).
        stats: nodes_seen/checked/verified/refuted/inconclusive/latency_ms +
            budget_exceeded (флаг) и budget_exceeded_nodes (id непроверенных из-за
            бюджета) — потребитель видит checked/total, а не скрытый «пол».
        """
        t_start = time.perf_counter()
        head = self._resolve_head()
        fp = self._ensure_fingerprint(head)
        # Бюджет применяется к per-node циклу проверок, НЕ к одноразовой
        # постройке отпечатка (HEAD change платит rebuild один раз, амортизируется).
        t_check = time.perf_counter()
        transitions: List[Dict[str, Any]] = []
        newly_refuted: Set[str] = set()
        stats: Dict[str, Any] = {
            "head": head,
            "fingerprint_build_ms": round(fp.build_ms, 1),
            "nodes_seen": 0,
            "cache_hits": 0,
            "checked": 0,
            "inconclusive": 0,
            "refuted": 0,
            "verified": 0,
            "budget_exceeded": False,
            "latency_ms": 0.0,
        }

        for section, nodes in memory.items():
            for node in nodes:
                if not isinstance(node, dict) or not node.get("node_id"):
                    continue
                node_id = str(node["node_id"])
                stats["nodes_seen"] += 1
                if stats["nodes_seen"] > 1 and (time.perf_counter() - t_check) * 1000.0 > budget_ms:
                    # Бюджет исчерпан: необработанные узлы — INCONCLUSIVE-семантика,
                    # остаются в контексте как есть (graceful degradation).
                    # budget_exceeded_nodes даёт потребителю точный список непроверенных
                    # узлов («пол»: checked/total виден, а не скрыт) для пометки
                    # verification="budget_exceeded" на стороне слоя.
                    stats["budget_exceeded"] = True
                    stats["inconclusive"] += 1
                    stats.setdefault("budget_exceeded_nodes", []).append(node_id)
                    continue

                key = self._cache_key(node_id, head)
                cached = self._cache.get("verdicts", {}).get(key)
                if cached and cached.get("verdict"):
                    stats["cache_hits"] += 1
                    if cached["verdict"] == VERDICT_NOT_FOUND:
                        newly_refuted.add(node_id)
                    continue

                stats["checked"] += 1
                anchors = extract_anchors(node)
                verdict, failed = self._classify(anchors, fp)
                self._cache.setdefault("verdicts", {})[key] = {
                    "node_id": node_id,
                    "head": head,
                    "verdict": verdict,
                    "failed": failed,
                }
                if verdict == VERDICT_FOUND:
                    stats["verified"] += 1
                    transitions.append({"node_id": node_id, "status": STATUS_VERIFIED})
                elif verdict == VERDICT_NOT_FOUND:
                    stats["refuted"] += 1
                    newly_refuted.add(node_id)
                    transitions.append(
                        {
                            "node_id": node_id,
                            "status": STATUS_REFUTED,
                            "reason": f"{REASON_SILENT_ABSENCE}: {failed}",
                        }
                    )
                else:
                    stats["inconclusive"] += 1
                    stats.setdefault("inconclusive_nodes", []).append(node_id)

        self._persist_transitions(transitions)
        self._persist_cache()

        if newly_refuted:
            memory = {
                section: [n for n in nodes if n.get("node_id") not in newly_refuted]
                for section, nodes in memory.items()
            }
        stats["latency_ms"] = round((time.perf_counter() - t_start) * 1000.0, 1)
        return memory, stats


# ── Реестр: один вердифайер на проект (разделяет HEAD/кэш между вызовами) ──

_VERIFIERS: Dict[str, VerifyOnRead] = {}


def get_verifier(project_root: Path, store: Any, write_lock: Any) -> VerifyOnRead:
    """Возвращает (и кэширует) VerifyOnRead для проекта.

    Store/lock берутся от первого создателя; в процессе слой интеллекта —
    синглтон, поэтому lock един для всех вызовов.
    """
    key = str(Path(project_root).resolve())
    if key not in _VERIFIERS:
        _VERIFIERS[key] = VerifyOnRead(project_root, store, write_lock)
    return _VERIFIERS[key]
