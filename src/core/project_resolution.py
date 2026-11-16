"""
ProjectResolution — резолвер корня проекта (ARCH-03).

Перенесён из src/mcp/server.py (v3.3.11) для исправления направления
зависимостей: core-слой больше не импортирует mcp-слой. См. дедлайн
в scripts/architecture_linter.py ("будут перенесены в core в v2.5" —
просрочен, закрыт в 3.3.11).

Приоритеты резолва (каждый вызов резолвит заново — см. INC-53EC / REFC-02):
    0. Явно переданный provided
    1. CWD (корень окна, для которого запущен MCP-процесс) — per-window
       изоляция (INC-MULTI-WINDOW). Zed запускает ОТДЕЛЬНЫЙ MCP-процесс
       на окно и ставит CWD = корень окна. SQLite active_workspace_id
       глобальный на весь Zed (одна строка на namespace, key = window_id,
       но резолв берёт rowid DESC LIMIT 1 без фильтра по окну) — два окна
       резолвят один проект → PID-lock конфликт → ProjectState.FAILED.
       CWD — единственный per-process сигнал.
    2. PROJECT_PATH из окружения (lazy, с self-indexing guard) — явный
       override пользователя; Zed-литерал "$ZED_WORKTREE_ROOT" → None.
    3. SQLite multi_workspace_state.active_workspace_id (fallback для
       single-window / когда CWD отклонён self-indexing guard'ом)
    4. Zed SQLite DB (workspaces table — fallback, если нет active)
    5. ZED_WORKTREE_ROOT env
    6. ext_root как fallback
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from src.core.platform_utils import get_zed_db_path

logger = logging.getLogger("mscodebase_server.project_resolution")

# ══════════════════════════════════════════════════════════
# ext_root: корень установленного расширения.
# Определяется из PYTHONPATH (надёжнее, чем __file__,
# т.к. PYTHONPATH всегда указывает на установленное расширение,
# а __file__ может указывать на исходники при dev-запуске).
_pythonpath = os.environ.get("PYTHONPATH", "")
if _pythonpath:
    ext_root = Path(_pythonpath.split(os.pathsep)[0]).resolve()
else:
    ext_root = Path(__file__).resolve().parent.parent.parent

# Lazy-кэш для env-резолва. ВАЖНО: PROJECT_PATH резолвится на каждый
# вызов resolve_project_root() (см. INC-53EC / REFC-02) — иначе при
# переключении workspace в Zed без рестарта MCP используется stale-путь.
_env_project_root_cache: Optional[Path] = None
# Сырое значение PROJECT_PATH, для которого построен кэш: env может измениться
# между вызовами (тесты, hot-reload) — кэш обязан это заметить.
_env_cache_raw: Optional[str] = None
_env_cache_lock = threading.Lock()

# SQLite connection cache + schema guard — открываем соединение раз в 2 секунды.
# Zed пишет workspace_id при переключении проекта, 2с TTL — достаточная свежесть.
# ВАЖНО: scoped_kv_store — недокументированный внутренний API Zed.
# При обновлении Zed схема может измениться — мы логируем предупреждение.
_sqlite_conn: Optional[sqlite3.Connection] = None
_sqlite_conn_time: float = 0
_sqlite_conn_lock = threading.RLock()  # RLock, т.к. _check_sqlite_schema_health вызывается изнутри _get_sqlite_connection
_SQLITE_CACHE_TTL = 2.0
# Флаг: проверка схемы выполнена (однократно при старте)
_sqlite_schema_checked: bool = False


def _check_sqlite_schema_health(conn) -> Optional[str]:
    """Проверяет, что таблицы scoped_kv_store и workspaces существуют
    и содержат ключевые колонки.

    Принимает уже открытое соединение — не вызывает _get_sqlite_connection()
    рекурсивно. Вызывается один раз при старте.
    """
    if conn is None:
        return "Zed SQLite DB недоступна — workspace-резолвинг будет degraded"
    try:
        cur = conn.cursor()

        # Проверяем таблицы
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scoped_kv_store'"
        )
        if cur.fetchone() is None:
            return "scoped_kv_store не найдена! workspace-резолвинг будет degraded"
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='workspaces'"
        )
        if cur.fetchone() is None:
            return "workspaces не найдена! workspace-резолвинг будет degraded"

        # Проверяем ключевые колонки scoped_kv_store
        cur.execute("PRAGMA table_info(scoped_kv_store)")
        kv_columns = {row[1] for row in cur.fetchall()}
        # Реальная схема Zed: namespace/key/value (key = window_id).
        # Резолв фильтрует по namespace (см. resolve_project_root).
        required_kv = {"namespace", "key", "value"}
        missing_kv = required_kv - kv_columns
        if missing_kv:
            return f"scoped_kv_store: отсутствуют колонки {missing_kv} — схема устарела"

        # Проверяем ключевые колонки workspaces
        cur.execute("PRAGMA table_info(workspaces)")
        ws_columns = {row[1] for row in cur.fetchall()}
        # Реальная схема Zed: workspace_id/paths/timestamp (не workspace/data).
        required_ws = {"workspace_id", "paths", "timestamp"}
        missing_ws = required_ws - ws_columns
        if missing_ws:
            return f"workspaces: отсутствуют колонки {missing_ws} — схема устарела"

        return None
    except (sqlite3.Error, OSError) as e:
        return f"Ошибка проверки схемы SQLite: {e}"


def _get_sqlite_connection() -> Optional[sqlite3.Connection]:
    """Возвращает кэшированное SQLite-соединение или открывает новое.
    TTL = _SQLITE_CACHE_TTL секунд, потокобезопасно."""
    global _sqlite_conn, _sqlite_conn_time, _sqlite_schema_checked
    now = time.time()
    with _sqlite_conn_lock:
        if _sqlite_conn is not None and now - _sqlite_conn_time < _SQLITE_CACHE_TTL:
            try:
                _sqlite_conn.execute("SELECT 1")  # проверка живости
                return _sqlite_conn
            except sqlite3.Error as _alive_err:
                logger.debug(f"SQLite connection stale: {_alive_err}")
                _sqlite_conn = None  # умерло, создадим новое

        # открываем новое
        _db_path = get_zed_db_path()
        if not _db_path.exists():
            return None
        try:
            _sqlite_conn = sqlite3.connect(str(_db_path), timeout=2.0)
            # Однократная проверка схемы при старте
            if not _sqlite_schema_checked:
                warn = _check_sqlite_schema_health(_sqlite_conn)
                if warn:
                    logger.warning(f"[🛡 SQLite Schema Guard] {warn}")
                _sqlite_schema_checked = True
            _sqlite_conn_time = now
            return _sqlite_conn
        except (sqlite3.Error, OSError) as _conn_err:
            logger.debug(f"SQLite connection failed: {_conn_err}")
            _sqlite_conn = None
            return None


def _close_sqlite_connection():
    """Принудительно закрывает кэшированное SQLite-соединение."""
    global _sqlite_conn
    with _sqlite_conn_lock:
        if _sqlite_conn is not None:
            try:
                _sqlite_conn.close()
            except sqlite3.Error as _e:
                logger.warning(f"SQLite close failed: {_e}")
            _sqlite_conn = None


_SYSTEM_ENV_ROOTS = ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")

# POSIX-корни: та же логика, что для Windows. Проект не может жить в /usr или /etc,
# а `.mscodebase` внутри них — это либо permission error, либо мусор в системе.
_POSIX_SYSTEM_ROOTS = (
    "/usr",
    "/etc",
    "/var",
    "/opt",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/boot",
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/root",
    "/snap",
    "/Applications",
    "/System",
    "/Library",
)

# Маркеры проекта: VCS или система сборки. Нужны, чтобы отличить рабочий
# каталог проекта от случайного cwd (см. `is_project_root`).
_PROJECT_MARKERS = (
    ".git",
    ".hg",
    ".svn",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    "Gemfile",
    "*.sln",
    "*.csproj",
)


def _system_roots() -> list[Path]:
    roots: list[Path] = []
    for name in _SYSTEM_ENV_ROOTS:
        raw = os.environ.get(name)
        if not raw:
            continue
        try:
            resolved = Path(raw).resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _forbidden_exact_roots() -> list[Path]:
    """Каталоги, запрещённые сами по себе, но НЕ их подкаталоги.

    `~` и temp-корень — частый рабочий каталог (проекты внутри `~/projects`
    или под `%TEMP%` легитимны), поэтому режем только сам корень.
    """
    import tempfile

    roots: list[Path] = []
    candidates = [Path.home(), tempfile.gettempdir()]
    candidates += [os.environ.get("TEMP"), os.environ.get("TMP")]
    for raw in candidates:
        if not raw:
            continue
        try:
            resolved = Path(raw).resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _forbidden_prefix_roots() -> list[Path]:
    """Каталоги ОС: запрещены и сами, и всё внутри них.

    POSIX-набор присутствует всегда (его состав проверяется тестом на любой
    платформе), но на Windows он не применяется к путям — см.
    `is_forbidden_root`.
    """
    roots = [Path(p) for p in _POSIX_SYSTEM_ROOTS]
    roots.extend(_system_roots())
    return roots


def _forbidden_roots() -> list[Path]:
    """Полный набор запрещённых корней (exact + prefix) — для тестов и логов."""
    return _forbidden_exact_roots() + _forbidden_prefix_roots()


def is_forbidden_root(p: Path | str) -> bool:
    """True, если каталог — не проект, а системный/служебный корень.

    Зачем: хост может запустить MCP-сервер с произвольным cwd
    (наблюдалось `C:\\Windows`, профиль пользователя, temp). Такой корень
    нельзя ни индексировать (десятки тысяч чужих файлов), ни использовать как
    место для `.mscodebase/chunks.db` — каталог принадлежит ОС.

    Существование пути не требуется: запрет на запись в `C:\\Windows\\System32`
    не должен зависеть от того, видит ли его текущий процесс.
    """
    try:
        root = Path(p).resolve()
    except OSError:
        return False
    if root.parent == root:  # корень диска/ФС: C:\, /
        return True
    if root in _forbidden_exact_roots():
        return True
    posix_roots = {Path(p) for p in _POSIX_SYSTEM_ROOTS}
    for candidate in _forbidden_prefix_roots():
        if os.name == "nt" and candidate in posix_roots:
            continue  # POSIX-пути на Windows не существуют и не применимы
        if root == candidate or root.is_relative_to(candidate):
            return True
    return False


# Расширения, по которым каталог похож на проект кода (проверяем верхний уровень).
_CODE_EXTENSIONS = frozenset(
    {
        ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs",
        ".rb", ".php", ".kt", ".kts", ".swift", ".c", ".h", ".cc", ".cpp", ".hpp", ".m",
        ".scala", ".dart", ".vue", ".svelte", ".html", ".htm", ".css", ".scss", ".sql",
        ".sh", ".bash", ".ps1", ".tf", ".hcl",
    }
)


def _index_has_chunks(db_path: Path) -> bool | None:
    """Есть ли в chunks.db хотя бы один чанк. None — прочитать не удалось.

    Смотреть на размер файла нельзя: SQLite в WAL держит свежие данные в
    `chunks.db-wal`, а основной файл остаётся 4096 b (замер ревью 2026-11-16:
    40 чанков, db 4096 b + wal 119 КБ). Обратная ошибка тоже была: пустая
    закрытая БД занимает 32 КБ и считалась «проиндексированным проектом».
    """
    import sqlite3

    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=0.2)
        try:
            return con.execute("select count(*) from chunks").fetchone()[0] > 0
        finally:
            con.close()
    except sqlite3.Error:
        return None


def _looks_like_sqlite(path: Path) -> bool:
    """Файл начинается с заголовка SQLite (`SQLite format 3\\0`)?

    Нужно, чтобы мусорный файл подходящего размера не считался индексом.
    """
    try:
        with open(path, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def is_project_root(p: Path | str) -> bool:
    """Похож ли каталог на проект (а не на случайный cwd).

    Признаки, любой из:
    - маркер VCS/сборки (`.git`, `pyproject.toml`, `package.json`, …);
    - уже существующий НЕПУСТОЙ индекс (`<root>/.mscodebase/chunks.db` с чанками
      или `graph.db` с узлами) — пользователь индексировал этот каталог раньше,
      его выбор не отменяем;
    - файл кода на верхнем уровне (папка со скриптами без VCS — тоже проект).

    Нужно для автоиндексации: без этих признаков корень может быть домашним
    каталогом или `C:\\Windows`. Явный вызов
    `codebase(action="index", path="project_dir")` этим не блокируется.
    """
    try:
        root = Path(p)
        if not root.is_dir():
            return False
        for marker in _PROJECT_MARKERS:
            if marker.startswith("*"):
                if next(iter(root.glob(marker)), None) is not None:
                    return True
            elif (root / marker).exists():
                return True
        # Уже существующий индекс учитываем только если он НЕПУСТОЙ: `.mscodebase`
        # с пустой chunks.db — след чужого запуска, а не признак проекта (замер
        # 2026-11-16: пустой индекс в temp делал «проектом» любой каталог и ронял
        # индексацию настоящего проекта).
        state_dir = root / ".mscodebase"
        db_path = state_dir / "chunks.db"
        # Стоимость проверки (замер 2026-11-16): 0.6–3.6 мс на индексах
        # 1–13 тыс. чанков; при наличии маркеров VCS/сборки sqlite вообще
        # не открывается. Для вызова на каждый инструмент — приемлемо.
        if db_path.is_file():
            has_chunks = _index_has_chunks(db_path)
            if has_chunks is True:
                return True
            if has_chunks is None:
                # Прочитать не смогли (занята/битая) — решаем по размеру вместе
                # с WAL, но только для настоящего SQLite-файла: мусорный файл на
                # 32 КБ не должен делать каталог «проектом» (ревью 2026-11-16).
                try:
                    if _looks_like_sqlite(db_path):
                        total = db_path.stat().st_size
                        wal = state_dir / "chunks.db-wal"
                        if wal.is_file():
                            total += wal.stat().st_size
                        if total > 8192:
                            return True
                except OSError:
                    pass
        # Граф символов — тоже индекс: проект может иметь только его.
        # Канонический путь — `<data_root>/projects/<hash>/graph.db`
        # (`get_graph_db_path`), а не `<root>/.mscodebase/graph.db`.
        graph_candidates = [state_dir / "graph.db", root / ".codebase" / "graph.db"]
        try:
            from src.core.artifact_paths import _compute_project_dir

            graph_candidates.append(_compute_project_dir(root) / "graph.db")
        except Exception:  # noqa: BLE001 — путь графа не обязателен для решения
            pass
        for graph_db in graph_candidates:
            try:
                if (
                    graph_db.is_file()
                    and graph_db.stat().st_size > 8192
                    and _looks_like_sqlite(graph_db)
                ):
                    return True
            except OSError:
                continue
        for entry in root.iterdir():
            if entry.is_file() and entry.suffix.lower() in _CODE_EXTENSIONS:
                return True
    except OSError:
        return False
    return False


def _reject_self_index_target(p: Path, *, source: str) -> bool:
    """Возвращает True если path — это self-indexing target (отклонить).

    Отклоняем:
    - ext_root (исходники самого расширения в dev-режиме — `python -m src.main`
      из workspace `D:\\Project\\MSCodeBase`). Это может случиться, если
      пользователь открывает исходники расширения как проект в Zed.
    - Zed install dir (см. is_zed_install_dir в lsp_project_bridge).
    - системные каталоги, корни дисков, профиль и temp-корень (см.
      `is_forbidden_root`): индексация `C:\\Windows` — это десятки тысяч
      чужих файлов и запись `.mscodebase` прямо в каталог ОС.

    РАНЬШЕ здесь была проверка `(p / "src/lsp_main.py").exists()` — она
    была ошибочной, потому что исходники расширения РЕАЛЬНО содержали
    `src/lsp_main.py`, и guard блокировал легитимный dev-сценарий
    ("открыть репо расширения как проект в Zed, чтобы индексировать
    свой же код"). Теперь вместо маркера-файла используется явный
    ext_root-equality + is_zed_install_dir (Zed install markers
    специфичны, ложных срабатываний на обычных проектах не дают).

    IMPORTANT: когда source="ACTIVE_WORKSPACE" — это ЯВНО активное
    окно Zed (multi_workspace_state.active_workspace_id). Пользователь
    ЯВНО открыл этот проект в Zed, поэтому доверяем ему даже если это
    ext_root. Блокируем ext_root только для автоматических fallback'ов
    (PROJECT_PATH, CWD, ZED_WORKTREE_ROOT, ZED_DB).
    """
    # Даже явный выбор (ACTIVE_WORKSPACE / trusted override) не делает проект
    # из каталога ОС: индексировать C:\Windows или /usr не хочет никто.
    if is_forbidden_root(p):
        logger.warning(
            f"{source} указывает на системный каталог ({p}), а не на проект. "
            f"Игнорирую: индексация ОС бесполезна, а .mscodebase внутри неё — вредна."
        )
        return True

    # ACTIVE_WORKSPACE — это явный выбор пользователя в Zed, доверяем
    if source == "ACTIVE_WORKSPACE":
        return False

    if p == ext_root:
        return True
    try:
        from src.core.lsp_project_bridge import is_zed_install_dir

        if is_zed_install_dir(p):
            logger.warning(
                f"{source} указывает на директорию установки Zed ({p}). "
                f"Игнорирую — self-indexing guard."
            )
            return True
    except (ImportError, OSError, ValueError) as _bridge_err:
        # Если lsp_project_bridge недоступен — не блокируем (fail-open)
        logger.debug(f"LSP bridge check failed (fail-open): {_bridge_err}")
    return False


def _try_resolve_path_env(raw: str, source: str, *, trust_self_index: bool = False) -> Optional[Path]:
    """Резолвит путь из env-raw (литерал $ZED_WORKTREE_ROOT или прямой путь).

    Общая логика для PROJECT_PATH и MSCODEBASE_PROJECT_PATH. Возвращает Path
    или None (невалид / self-indexing / пусто).

    trust_self_index=True — доверяем явному override даже если это ext_root
    (аналог ACTIVE_WORKSPACE). Используется ТОЛЬКО для MSCODEBASE_PROJECT_PATH
    (клиент осознанно указал проект через --project-path); PROJECT_PATH
    сохраняет блокировку self-indexing для обратной совместимости.
    """
    if not raw:
        return None
    # Случай 0: неразвёрнутый плейсхолдер хоста (`${workspaceRoot}`, `%VAR%`).
    # Наблюдалось на живой машине: PROJECT_PATH=${workspaceRoot} уходил в
    # resolv как относительный путь, проваливался, и сервер брал cwd — вплоть
    # до C:\Windows. Такую конфигурацию надо видеть в логе, а не угадывать.
    if "${" in raw or (raw.startswith("%") and raw.endswith("%")):
        logger.warning(
            f"{source}={raw!r} — неразвёрнутый плейсхолдер хоста, игнорирую. "
            f"Укажите реальный путь или $ZED_WORKTREE_ROOT."
        )
        return None
    # Случай 1: Zed literal "$ZED_WORKTREE_ROOT" без подстановки.
    if raw.startswith("$"):
        zed_root = os.environ.get("ZED_WORKTREE_ROOT")
        if zed_root:
            p = Path(zed_root).resolve()
            if p.exists() and not _reject_self_index_target(p, source="ZED_WORKTREE_ROOT"):
                return p
        return None
    # Случай 2: прямой путь.
    try:
        resolved = Path(raw).resolve()
    except (OSError, ValueError):
        return None
    if not resolved.exists() or not resolved.is_dir():
        return None
    # Self-indexing guard: для автоматических fallback'ов блокируем ext_root;
    # для явного CLI override (trust_self_index=True) — доверяем.
    if (
        not trust_self_index
        and _reject_self_index_target(resolved, source=source)
        and os.environ.get("MSCODEBASE_ALLOW_SELF_INDEX", "").strip().lower() not in ("1", "true", "yes")
    ):
        logger.warning(
            f"{source} указывает на self-indexing target ({resolved}). "
            f"Игнорирую — установите MSCODEBASE_ALLOW_SELF_INDEX=1 или используйте ACTIVE_WORKSPACE."
        )
        return None
    return resolved


def _resolve_env_project_root() -> Optional[Path]:
    """Резолвит PROJECT_PATH из окружения лениво + один раз кэширует результат.

    Возвращает None, если PROJECT_PATH не задан / невалиден / указывает
    на сам ext (тогда bridge/ZED_WORKTREE_ROOT/CWD получают шанс).
    """
    global _env_project_root_cache, _env_cache_raw
    raw = os.environ.get("PROJECT_PATH", "").strip()
    with _env_cache_lock:
        if _env_project_root_cache is not None and _env_cache_raw == raw:
            return _env_project_root_cache
        env_root = _try_resolve_path_env(raw, "PROJECT_PATH")
        _env_project_root_cache = env_root
        _env_cache_raw = raw
        return env_root


def reset_project_root_cache() -> None:
    """Сбрасывает кэш resolve_project_root (для тестов и hot-reload)."""
    global _env_project_root_cache, _env_cache_raw
    with _env_cache_lock:
        _env_project_root_cache = None
        _env_cache_raw = None


def resolve_project_root(provided: str = "") -> Path:
    """Возвращает корень проекта для MCP-инструментов.

    Приоритет (каждый вызов резолвит заново — см. INC-53EC / REFC-02):
    0. Явно переданный provided
    1. MSCODEBASE_PROJECT_PATH env (явный override CLI/владельца, НАД CWD).
       Приоритет над CWD — только для этого явного override; обычный Zed-режим
       CWD-first сохраняет per-window изоляцию (INC-MULTI-WINDOW).
    2. CWD (корень окна, для которого запущен MCP-процесс) — per-window
       изоляция (INC-MULTI-WINDOW): Zed запускает отдельный MCP на окно
       и ставит CWD = корень окна. SQLite active_workspace_id глобальный
       на весь Zed — два окна резолвят один проект → PID-lock конфликт.
       Self-indexing guard: CWD == ext_root отклоняется (dev/test-режим
       добирается через SQLite active_workspace с доверием ACTIVE_WORKSPACE).
    3. PROJECT_PATH из окружения (lazy, с self-indexing guard) — явный
       override пользователя; Zed-литерал "$ZED_WORKTREE_ROOT" → None.
    4. SQLite multi_workspace_state.active_workspace_id (fallback для
       single-window / когда CWD отклонён self-indexing guard'ом)
    5. Zed SQLite DB (workspaces table — fallback, если нет active)
    6. ZED_WORKTREE_ROOT env
    7. ext_root как fallback
    """
    if provided and provided.strip():
        explicit = Path(provided).resolve()
        if is_forbidden_root(explicit):
            # Явный аргумент инструмента — тоже не повод индексировать ОС.
            logger.warning(
                f"resolve_project_root: явный project_root={explicit} — системный каталог, "
                f"игнорирую (см. is_forbidden_root)"
            )
        else:
            return explicit

    # ─── 0.5. MSCODEBASE_PROJECT_PATH: явный override НАД CWD ───
    # Отличается от PROJECT_PATH (см. ниже, позиция 3): имеет приоритет над
    # CWD, т.к. это намеренный override (CLI --project-path устанавливает
    # именно его). В обычном Zed-режиме env не задан → CWD-first сохраняется.
    prio_raw = os.environ.get("MSCODEBASE_PROJECT_PATH", "").strip()
    if prio_raw:
        prio_root = _try_resolve_path_env(
            prio_raw, "MSCODEBASE_PROJECT_PATH", trust_self_index=True
        )
        if prio_root is not None:
            logger.debug(f"resolve_project_root: MSCODEBASE_PROJECT_PATH={prio_root}")
            return prio_root

    # ─── 1. CWD-FIRST: per-window изоляция (INC-MULTI-WINDOW) ───
    # Раньше CWD был предпоследним в цепочке, а SQLite active_workspace_id
    # (один на весь Zed) — первым: оба окна резолвили один проект →
    # PID-lock конфликт и ProjectState.FAILED во втором окне.
    #
    # Оговорка (замер 2026-11-16): хост может запустить сервер с cwd, который
    # НЕ проект (`%TEMP%`, каталог установки), и при этом передать PROJECT_PATH
    # на настоящий проект. Тогда CWD-first индексировал пустоту: в логе
    # `[text-index] done: 0 files`, а все инструменты видели пустой индекс.
    # Поэтому CWD выигрывает только если он сам похож на проект; иначе честно
    # уступаем явному PROJECT_PATH (позиция 2), а CWD остаётся как был — для
    # multi-window, где cwd и есть проект.
    cwd = Path.cwd().resolve()
    if not _reject_self_index_target(cwd, source="CWD"):
        if is_project_root(cwd):
            logger.debug(f"resolve_project_root: CWD={cwd}")
            return cwd
        env_candidate = _resolve_env_project_root()
        if env_candidate is not None and is_project_root(env_candidate):
            if env_candidate == cwd:
                # Тот же путь: подмены нет, предупреждать не о чем.
                logger.debug(f"resolve_project_root: CWD={cwd} (PROJECT_PATH совпадает)")
                return cwd
            logger.warning(
                f"resolve_project_root: CWD={cwd} не похож на проект — "
                f"использую PROJECT_PATH={env_candidate}"
            )
            return env_candidate
        logger.debug(f"resolve_project_root: CWD={cwd}")
        return cwd

    # LSP→MCP bridge — DEPRECATED (2026-08-06): LSP-сервер удалён 2026-07-20,
    # read_project_from_bridge всегда возвращает None. project_root резолвится
    # через CWD / PROJECT_PATH env / Zed SQLite (см. следующие блоки).

    # ─── 2. PROJECT_PATH env (явный override пользователя) ───
    env_root = _resolve_env_project_root()
    if env_root is not None:
        logger.debug(f"resolve_project_root: PROJECT_PATH={env_root}")
        return env_root

    # ─── 3. SQLite: multi_workspace_state.active_workspace_id ───
    # Используем кэшированное соединение (TTL 2с, см. _get_sqlite_connection).
    try:
        _conn = _get_sqlite_connection()
        if _conn is not None:
            import json as _json

            _cur = _conn.cursor()
            _cur.execute(
                "SELECT key, value FROM scoped_kv_store "
                "WHERE namespace = 'multi_workspace_state' "
                "ORDER BY rowid DESC "
                "LIMIT 1"
            )
            _row = _cur.fetchone()
            if _row:
                try:
                    _state = _json.loads(_row[1])
                    _active_id = _state.get("active_workspace_id")
                    if _active_id is not None:
                        _cur.execute(
                            "SELECT paths FROM workspaces WHERE workspace_id = ?",
                            (_active_id,),
                        )
                        _match = _cur.fetchone()
                        if _match and _match[0]:
                            # Guard: SQLite paths могут быть через \n (multi-root).
                            _raw = _match[0].strip()
                            _first = _raw.split("\n")[0].split(",")[0].strip()
                            _path = Path(_first)
                            if _path.exists() and _path.is_dir() and not _reject_self_index_target(
                                _path, source="ACTIVE_WORKSPACE"
                            ):
                                logger.debug(
                                    f"resolve_project_root: active_workspace_id={_active_id} → {_path}"
                                )
                                return _path.resolve()
                except (sqlite3.Error, OSError, ValueError) as _ws_err:
                    logger.debug(f"resolve_project_root: workspace parse failed: {_ws_err}")
    except (sqlite3.Error, OSError, ValueError) as _active_err:
        logger.debug(f"resolve_project_root: active_workspace error: {_active_err}")

    # ─── 4. Fallback: Zed SQLite DB (через то же кэшированное соединение) ───
    try:
        _conn2 = _get_sqlite_connection()
        if _conn2 is not None:
            _cur2 = _conn2.cursor()
            _cur2.execute(
                "SELECT paths, timestamp FROM workspaces WHERE paths != '' AND paths IS NOT NULL ORDER BY timestamp DESC"
            )
            _all_rows = _cur2.fetchall()
            _candidates = []
            for _row in _all_rows:
                if not _row[0]:
                    continue
                # Guard: SQLite paths may contain \n (multi-root workspace).
                _raw = _row[0].strip()
                _parts = _raw.split("\n") if "\n" in _raw else _raw.split(",")
                for _part in _parts:
                    _p = _part.strip()
                    if not _p:
                        continue
                    _path = Path(_p)
                    if _reject_self_index_target(_path, source="ZED_DB"):
                        continue
                    _score = 2 if (_path / ".git").exists() else 1
                    _candidates.append((_score, _row[1] or "", _path))
            if _candidates:
                _candidates.sort(key=lambda x: (x[0], x[1] or ""), reverse=True)
                _best = _candidates[0][2]
                logger.debug(
                    f"resolve_project_root: Zed DB ({len(_candidates)} candidates) → {_best}"
                )
                return _best.resolve()
    except (sqlite3.Error, OSError, ValueError) as _zed_err:
        logger.debug(f"resolve_project_root: Zed DB fallback error: {_zed_err}")

    # ─── 5. ZED_WORKTREE_ROOT env ───
    zed_root = os.environ.get("ZED_WORKTREE_ROOT")
    if zed_root:
        zed_path = Path(zed_root).resolve()
        if zed_path.exists() and not _reject_self_index_target(
            zed_path, source="ZED_WORKTREE_ROOT"
        ):
            logger.debug(f"resolve_project_root: ZED_WORKTREE_ROOT={zed_path}")
            return zed_path

    # Диагностика: почему все шаги провалились
    _log_project_resolution_failure()
    logger.warning(
        f"resolve_project_root: fallback to ext_root={ext_root} "
        f"(возможна self-indexing; установите PROJECT_PATH=$ZED_WORKTREE_ROOT)"
    )
    return ext_root


def _log_project_resolution_failure() -> None:
    """Логирует детальную причину падения resolve_project_root в ext_root."""
    # LSP→MCP bridge удалён (2026-07-20): чтение ~/.mscodebase/bridge больше
    # не выполняется — модуль lsp_project_bridge DEPRECATED, писатель мёртв.
    logger.debug("resolve_project_root: все источники (CWD/env/Zed-SQLite) пусты")
