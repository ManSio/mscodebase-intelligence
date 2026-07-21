"""
MSCodeBase LSP Server - проактивный индексатор через Language Server Protocol.

Интегрируется в Zed как language server и получает события файлов напрямую
от Rust-ядра редактора. Никакого polling, watchdog или ручного трекинга.

Два источника событий:
1. didSave - пользователь нажал Ctrl+S (файл гарантированно свободен от локов)
2. didChangeWatchedFiles - встроенный в Zed Rust-watcher заметил изменения на диске
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from src.core.di_container import ServiceCollection

_services_per_workspace: dict[str, ServiceCollection] = {}
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [LSP] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MSCodeBase-LSP")

# Подключаем файловое логирование
try:
    from src.core.log_manager import setup_project_logging

    _ext_root = Path(__file__).resolve().parent.parent
    setup_project_logging(_ext_root)
except Exception:
    pass  # Файловое логирование опционально

# Поддерживаемые расширения (код + конфиги + документация)
# Единый источник правды — extensions.py
from src.core.extensions import INDEX_EXTENSIONS as SUPPORTED_EXTENSIONS


def _uri_to_path(uri: str) -> Path:
    """Безопасная конвертация URI от редактора в системный Path (с учетом Windows)."""
    parsed = urlparse(uri)
    raw_path = parsed.path
    if sys.platform == "win32" and raw_path.startswith("/"):
        raw_path = raw_path.lstrip("/")
    return Path(raw_path).resolve()


def _get_rel_path_str(file_path: Path, project_path: Path) -> str:
    """Возвращает нормализованный относительный POSIX-путь для LanceDB."""
    return file_path.relative_to(project_path).as_posix()


# Multi-window LSP (INC-6BCB): один LSP-процесс обслуживает несколько
# workspace URI (несколько открытых проектов в Zed). Вместо одного
# глобального _services держим DI-контейнер на каждый workspace.
_services_per_workspace: dict[str, "ServiceCollection"] = {}
_workspace_lock = threading.Lock()

# Debounce-курок для did_change (см. INC-53EC / REFC-01):
# текст в pygls обновляется на каждый keystroke, но индексировать
# имеет смысл только когда пользователь перестал печатать.
_DID_CHANGE_DEBOUNCE_MS = 350
_did_change_pending: dict[str, asyncio.Task] = {}  # uri -> debounce task
_did_change_lock = asyncio.Lock()

# Sequential indexing queue (см. INC-53EC / LSP-03):
# предотвращает гонки при записи в LanceDB/SymbolIndex от параллельных
# did_open/did_change/did_save.
_indexing_serial_lock = asyncio.Lock()


def init_components(project_root: Path, workspace_uri: str = ""):
    """Ленивая инициализация компонентов через DI контейнер.

    Multi-window (INC-6BCB): для каждого workspace_uri создаётся
    свой DI-контейнер. Раньше был один глобальный _services —
    переключение окон ломало state.

    Args:
        project_root: корень проекта (для resolve).
        workspace_uri: уникальный URI workspace'а (для ключа).
                       Если пусто — используется project_root.
    """
    global _services_per_workspace

    key = workspace_uri or str(project_root.resolve())
    with _workspace_lock:
        if key in _services_per_workspace:
            return _services_per_workspace[key]

    from src.core.di_container import create_service_collection

    services = create_service_collection(project_root)
    with _workspace_lock:
        _services_per_workspace[key] = services

    # Инициализируем DebounceBatch для BM25 реиндексации
    # Multi-window (INC-6BCB-v2): batch теперь создаётся per-project внутри
    # _create_indexer_for_path() и доступен как indexer.bm25_batch.
    from src.core.di_container import ProjectRootKey
    from src.core.indexing.project_indexer_registry import ProjectIndexerRegistry

    registry: ProjectIndexerRegistry = services.resolve(ProjectIndexerRegistry)
    factory = _get_factory(services)
    # Прогреваем per-project Indexer (lazy) — чтобы bm25_batch был создан.
    _initial_indexer = registry.get_indexer(
        services.resolve(ProjectRootKey), factory=factory
    )
    logger.info(
        f"LSP: DI Container инициализирован для {project_root.name} "
        f"(workspace: {key}, BM25 debounce active per-project)"
    )
    return services


def _get_factory(services):
    """Извлекает IndexerFactory из services (multi-window)."""
    from src.core.di_container import IndexerFactoryKey

    return services.resolve(IndexerFactoryKey)


def _execute_file_indexing(
    file_path: Path,
    content: Optional[str] = None,
    workspace_uri: str = "",
    project_root: Optional[Path] = None,
):
    """Оркестрация проверки хеша и чанкера (вызывается в thread-пулу).

    Multi-window (INC-6BCB): получает workspace_uri/project_root от
    caller-а и резолвит правильный DI-контейнер.
    """
    key = workspace_uri or (str(project_root.resolve()) if project_root else "")
    services = _services_per_workspace.get(key) if key else None
    if services is None:
        # Fallback: первый доступный (legacy single-window).
        with _workspace_lock:
            if _services_per_workspace:
                services = next(iter(_services_per_workspace.values()))
    if services is None:
        # В LSP-контексте _services обязан быть инициализирован в on_initialize.
        # Fallback на Path.cwd() опасен (CWD сервера != проект пользователя).
        logger.error(
            f"[LSP INDEXING] Services not initialized for {file_path.name}; "
            f"skipping. Это баг инициализации LSP."
        )
        return

    from src.core.di_container import ProjectRootKey
    from src.core.indexing.project_indexer_registry import ProjectIndexerRegistry

    registry: ProjectIndexerRegistry = services.resolve(ProjectIndexerRegistry)
    factory = _get_factory(services)
    # Per-workspace indexer (multi-window, INC-6BCB).
    # Если project_root не передан явно — берём default из DI (один проект
    # на workspace, как задумано в multi-window архитектуре).
    if project_root is not None:
        target_path = project_root
    else:
        target_path = services.resolve(ProjectRootKey)
    target_indexer = registry.get_indexer(target_path, factory=factory)
    indexer = target_indexer

    # Проверки безопасности
    if not indexer.path_manager.is_safe_to_process(file_path):
        return
    if indexer.file_guard.should_skip_file(file_path):
        return

    try:
        rel_path_str = _get_rel_path_str(file_path, indexer.project_path)
    except ValueError:
        return

    logger.info(
        f"[LSP INDEXING] Анализ файла: {rel_path_str} (from_memory={content is not None})"
    )
    success = indexer._index_single_file(file_path, rel_path_str, content=content)

    # ★ ИСПРАВЛЕНО: BM25 реиндексация через DebounceBatch, а не на каждый файл ★
    if success:
        try:
            # Multi-window (INC-6BCB-v2): per-project batch живёт на Indexer-е.
            batch = getattr(indexer, "bm25_batch", None)
            if batch is not None:
                # Добавляем файл в debounce батч (асинхронно в фоне, fire-and-forget)
                import asyncio

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(batch.add(rel_path_str))
                    else:
                        loop.run_until_complete(batch.add(rel_path_str))
                except RuntimeError:
                    pass
            else:
                # Fallback: нет per-project batch — синхронная реиндексация.
                if indexer.searcher:
                    indexer.searcher.reindex()
        except Exception:
            # Fallback: немедленная реиндексация
            if indexer.searcher:
                indexer.searcher.reindex()


def _process_watched_changes(changes, services=None):
    """Синхронный воркер для обработки пачки внешних событий диска.

    Multi-window (INC-6BCB): принимает services от caller-а (per-workspace).
    """
    if services is None:
        with _workspace_lock:
            if _services_per_workspace:
                services = next(iter(_services_per_workspace.values()))
    if services is None:
        return

    # Per-workspace indexer (multi-window). Берём default project_root
    # сервисов как fallback.
    from src.core.di_container import ProjectRootKey
    from src.core.indexing.project_indexer_registry import ProjectIndexerRegistry

    registry: ProjectIndexerRegistry = services.resolve(ProjectIndexerRegistry)
    factory = _get_factory(services)
    project_root = services.resolve(ProjectRootKey)
    indexer = registry.get_indexer(project_root, factory=factory)
    # Multi-window (INC-6BCB-v2): per-project batch живёт на Indexer-е.
    batch = getattr(indexer, "bm25_batch", None)

    changed_files = []
    logger.info(f"[LSP WATCHER] Received {len(changes)} file change(s)")

    for change in changes:
        file_path = _uri_to_path(change.uri)
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            logger.debug(f"[LSP WATCHER] Skip unsupported: {file_path.name}")
            continue

        try:
            rel_path_str = _get_rel_path_str(file_path, indexer.project_path)
        except ValueError:
            logger.debug(f"[LSP WATCHER] Skip (not in project): {file_path.name}")
            continue

        # FileChangeType.Deleted == 3
        if change.type == 3:
            logger.info(f"[LSP DELETE] {rel_path_str}")
            try:
                escaped = indexer._escape_file_path_for_lance(rel_path_str)
                indexer.table.delete(f"file_path = '{escaped}'")
                logger.info(f"  └─ Deleted from index: {rel_path_str}")
            except Exception as del_err:
                logger.debug(f"delete() error: {del_err}")
            changed_files.append(rel_path_str)

        # FileChangeType.Created == 1 или Changed == 2
        elif change.type in (1, 2):
            change_type = "CREATE" if change.type == 1 else "CHANGE"
            logger.info(f"[LSP {change_type}] {rel_path_str}")
            try:
                if indexer._index_single_file(file_path, rel_path_str):
                    logger.info(f"  └─ Reindexed: {rel_path_str}")
                    changed_files.append(rel_path_str)
                else:
                    logger.info(f"  └─ No changes (hash match): {rel_path_str}")
            except Exception as e:
                logger.error(f"  └─ Indexing failed: {rel_path_str}: {e}")

    # ★ Вместо немедленного searcher.reindex() — через DebounceBatch ★
    if changed_files and batch is not None:
        logger.info(
            f"[LSP WATCHER] {len(changed_files)} files changed, queuing BM25 debounce"
        )
        try:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                for f in changed_files:
                    asyncio.ensure_future(batch.add(f))
            else:
                for f in changed_files:
                    loop.run_until_complete(batch.add(f))
        except Exception:
            # Fallback если asyncio недоступен
            if indexer.searcher:
                logger.info(
                    "[LSP WATCHER] Debounce failed, fallback to direct BM25 rebuild"
                )
                indexer.searcher.reindex()
    elif changed_files and batch is None:
        # Нет per-project batch (legacy путь) — синхронный reindex.
        logger.info(
            f"[LSP WATCHER] {len(changed_files)} files changed, no per-project batch — direct reindex"
        )
        if indexer.searcher:
            indexer.searcher.reindex()
    else:
        logger.info("[LSP WATCHER] No indexing needed")


# ============================================================================
# LSP Server
# ============================================================================

try:
    from lsprotocol.types import (
        TEXT_DOCUMENT_DID_SAVE,
        DidSaveTextDocumentParams,
        InitializeParams,
        InitializeResult,
        TextDocumentSyncKind,
    )
    from pygls.lsp.server import LanguageServer

    class MSCodeBaseLanguageServer(LanguageServer):
        """Language Server для проактивной индексации."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._initialized = False

    server = MSCodeBaseLanguageServer("mscodebase-lsp", "1.0.0")

    # === 1. ЖИЗНЕННЫЙ ЦИКЛ ДОКУМЕНТА (didOpen, didChange, didClose) ===
    # Эти события приходят от Zed когда ИИ-ассистент меняет код в закрытых файлах!

    @server.feature("textDocument/didOpen")
    async def did_open(ls: MSCodeBaseLanguageServer, params):
        """Вызывается когда Zed открывает файл (в т.ч. в фоне для ИИ-ассистента)."""
        try:
            file_path = _uri_to_path(params.text_document.uri)
            logger.info(f"[LSP DID_OPEN] {file_path.name}")

            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                return

            # При didOpen текст гарантированно в памяти pygls
            content = None
            try:
                document = ls.workspace.get_document(params.text_document.uri)
                content = document.source
            except Exception:
                pass

            async with _indexing_serial_lock:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    _execute_file_indexing,
                    file_path,
                    content,
                    getattr(ls, "_workspace_uri", ""),
                    getattr(ls, "_project_root", None),
                )
        except Exception as e:
            logger.error(f"[LSP DID_OPEN] Error: {e}")

    @server.feature("textDocument/didChange")
    async def did_change(ls: MSCodeBaseLanguageServer, params):
        """Вызывается при каждом изменении текста (включая правки ИИ-ассистента).

        Debounced (см. INC-53EC / REFC-01): не индексируем на каждый keystroke.
        Если в течение _DID_CHANGE_DEBOUNCE_MS приходит новое изменение —
        предыдущий таск отменяется, таймер сбрасывается. did_save остаётся
        надёжным source of truth для долговременной индексации.

        Multi-window (INC-6BCB-v2): workspace_uri и project_root пробрасываются
        в _execute_file_indexing, чтобы per-workspace registry попал в нужный
        DI-контейнер (раньше _execute_file_indexing падал на default
        ProjectRootKey для не-default окон).
        """
        try:
            file_path = _uri_to_path(params.text_document.uri)

            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                return

            uri = params.text_document.uri
            try:
                document = ls.workspace.get_document(uri)
                content = document.source
            except Exception:
                content = None

            workspace_uri = getattr(ls, "_workspace_uri", "")
            project_root = getattr(ls, "_project_root", None)
            logger.info(
                f"[LSP DID_CHANGE] {file_path.name} "
                f"({len(content) if content else 0} chars, "
                f"ws={workspace_uri[:40] if workspace_uri else 'default'}) — debounced"
            )

            async def _delayed_index():
                try:
                    await asyncio.sleep(_DID_CHANGE_DEBOUNCE_MS / 1000)
                except asyncio.CancelledError:
                    return
                # Сериализуем через глобальный lock, чтобы избежать
                # одновременной записи в LanceDB (см. INC-53EC / LSP-03).
                async with _indexing_serial_lock:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None,
                        _execute_file_indexing,
                        file_path,
                        content,
                        workspace_uri,
                        project_root,
                    )

            async with _did_change_lock:
                old_task = _did_change_pending.pop(uri, None)
                if old_task and not old_task.done():
                    old_task.cancel()
                _did_change_pending[uri] = asyncio.create_task(_delayed_index())
        except Exception as e:
            logger.error(f"[LSP DID_CHANGE] Error: {e}")

    @server.feature("textDocument/didClose")
    async def did_close(ls: MSCodeBaseLanguageServer, params):
        """Вызывается когда Zed закрывает буфер (в т.ч. после работы ИИ-ассистента).

        В этот момент Zed уже зафлашил все изменения на диск,
        поэтому можно безопасно прочитать файл с диска.

        Multi-window (INC-6BCB-v2): пробрасываем workspace_uri/project_root
        чтобы попасть в правильный per-workspace DI.
        """
        try:
            file_path = _uri_to_path(params.text_document.uri)
            workspace_uri = getattr(ls, "_workspace_uri", "")
            project_root = getattr(ls, "_project_root", None)
            logger.info(
                f"[LSP DID_CLOSE] {file_path.name} "
                f"(ws={workspace_uri[:40] if workspace_uri else 'default'})"
            )

            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                return

            # Отменяем debounce, если висит (его работа больше не нужна).
            async with _did_change_lock:
                pending = _did_change_pending.pop(params.text_document.uri, None)
                if pending and not pending.done():
                    pending.cancel()

            async with _indexing_serial_lock:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    _execute_file_indexing,
                    file_path,
                    None,
                    workspace_uri,
                    project_root,
                )
        except Exception as e:
            logger.error(f"[LSP DID_CLOSE] Error: {e}")

    @server.feature(TEXT_DOCUMENT_DID_SAVE)
    async def did_save(ls: MSCodeBaseLanguageServer, params: DidSaveTextDocumentParams):
        """Триггерится нативным Ctrl+S в Zed. Файл уже свободен от локов Windows."""
        try:
            file_path = _uri_to_path(params.text_document.uri)

            logger.info(
                f"[LSP DID_SAVE] File: {file_path.name}, Suffix: {file_path.suffix}"
            )

            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                logger.info(f"[LSP DID_SAVE] Skip unsupported: {file_path.suffix}")
                return

            # Отменяем debounce — Ctrl+S форсирует немедленную индексацию.
            async with _did_change_lock:
                pending = _did_change_pending.pop(params.text_document.uri, None)
                if pending and not pending.done():
                    pending.cancel()

            # Берём текст из памяти LSP (pygls хранит актуальное содержимое)
            # Это решает проблему отложенной записи на диск в Windows!
            content = None
            try:
                document = ls.workspace.get_document(params.text_document.uri)
                content = document.source
                logger.info(f"[LSP DID_SAVE] Got {len(content)} chars from memory")
            except Exception as mem_err:
                logger.warning(f"[LSP DID_SAVE] Could not get from memory: {mem_err}")

            logger.info(f"[LSP DID_SAVE] Starting indexing: {file_path.name}")

            workspace_uri = getattr(ls, "_workspace_uri", "")
            project_root = getattr(ls, "_project_root", None)
            async with _indexing_serial_lock:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    _execute_file_indexing,
                    file_path,
                    content,
                    workspace_uri,
                    project_root,
                )

            logger.info(f"[LSP DID_SAVE] Indexing complete: {file_path.name}")

        except Exception as e:
            logger.error(
                f"[LSP DID_SAVE] Error: {e}",
                exc_info=True,
            )

    # === 2. ОБРАБОТКА ВНЕШНИХ ИЗМЕНЕНИЙ (git checkout, удаление вне редактора) ===
    @server.feature("workspace/didChangeWatchedFiles")
    async def did_change_watched_files(ls: MSCodeBaseLanguageServer, params):
        """
        Вызывается, когда встроенный в Zed (Rust) файловый watcher
        заметил физические изменения на диске.

        Multi-window (INC-6BCB-v2): берём services для текущего workspace_uri
        из _services_per_workspace (раньше была ссылка на несуществующую
        глобальную _services → NameError при первом же watcher-событии).
        """
        try:
            workspace_uri = getattr(ls, "_workspace_uri", "")
            workspace_services = _services_per_workspace.get(workspace_uri)
            if workspace_services is None:
                # Fallback: первый доступный (multi-window: не идеально,
                # но лучше чем NameError).
                with _workspace_lock:
                    if _services_per_workspace:
                        workspace_services = next(
                            iter(_services_per_workspace.values())
                        )
            if workspace_services is None:
                logger.warning(
                    "[LSP WATCHER] Services not initialized for any workspace, skip"
                )
                return

            logger.info(f"[LSP WATCHER] Zed sent {len(params.changes)} change(s)")
            for change in params.changes:
                logger.info(f"  - URI: {change.uri}, Type: {change.type}")

            async with _indexing_serial_lock:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    _process_watched_changes,
                    params.changes,
                    workspace_services,
                )
        except Exception as e:
            logger.error(
                f"[LSP RECOVERY] Ошибка обработки изменений воркспейса: {e}",
                exc_info=True,
            )

    # === 3. ИНИЦИАЛИЗАЦИЯ ===
    @server.feature("initialize")
    async def on_initialize(ls: MSCodeBaseLanguageServer, params: InitializeParams):
        r"""При старте забираем у Zed корни открытых воркспейсов.

        Multi-root (INC-6BCB-v3): LSP 3.6+ присылает `workspaceFolders` —
        массив ВСЕХ открытых воркспейсов одновременно. Это РЕШАЕТ проблему
        self-indexing Zed-установки: если Zed открыл D:\AI\Zed И
        D:\Project\MSCodeBase, мы видим ОБА, и можем выбрать
        правильный через фильтр (skip Zed install dir).

        Fallback на `params.root_uri` (single-root legacy, Zed <0.130).
        """
        # Извлекаем список корней: workspaceFolders (LSP 3.6+) приоритетнее
        # чем rootUri. Если workspaceFolders пуст/NULL — берём rootUri.
        workspace_folders = getattr(params, "workspace_folders", None) or []
        workspace_uris: list[str] = []

        if workspace_folders:
            for wf in workspace_folders:
                try:
                    uri_str = str(wf.uri) if hasattr(wf, "uri") else str(wf)
                    parsed_path = Path(urlparse(uri_str).path)
                    if sys.platform == "win32" and str(parsed_path).startswith("\\"):
                        parsed_path = Path(str(parsed_path).lstrip("\\"))
                    if parsed_path.exists() and parsed_path.is_dir():
                        workspace_uris.append(uri_str)
                except Exception as wf_err:
                    logger.warning(f"[LSP INIT] Bad workspace folder: {wf_err}")
        elif params.root_uri:
            workspace_uris.append(params.root_uri)

        if not workspace_uris:
            logger.warning(
                "[LSP INIT] No workspace folders AND no root_uri — "
                "Zed открыт без проекта (single file?). Indexing will skip."
            )
            ls._workspace_uri = ""
            ls._project_root = None
            ls._all_workspaces = []
            return InitializeResult(
                capabilities={
                    "text_document_sync": TextDocumentSyncKind.Incremental,
                }
            )

        # Фильтруем Zed-установку (self-indexing guard на LSP-стороне).
        # Не индексируем саму директорию, где лежит Zed.exe.
        from src.core.lsp_project_bridge import is_zed_install_dir

        filtered = []
        for uri in workspace_uris:
            try:
                p = Path(urlparse(uri).path)
                if sys.platform == "win32" and str(p).startswith("\\"):
                    p = Path(str(p).lstrip("\\"))
                if is_zed_install_dir(p):
                    logger.info(
                        f"[LSP INIT] Skipping Zed install dir: {p} "
                        f"(would be self-indexing)"
                    )
                    continue
                filtered.append(uri)
            except Exception:
                filtered.append(uri)  # на всякий случай оставляем

        if not filtered:
            # Все workspace folders — это Zed install. Fallback на первый
            # (лучше self-indexing чем вообще ничего).
            logger.warning(
                "[LSP INIT] Все workspace folders = Zed install dir. "
                "Fallback на первый (может быть self-indexing)."
            )
            filtered = [workspace_uris[0]]

        # Берём ПЕРВЫЙ (most recent) filtered workspace как primary.
        primary_uri = filtered[0]
        primary_path = Path(urlparse(primary_uri).path)
        if sys.platform == "win32" and str(primary_path).startswith("\\"):
            primary_path = Path(str(primary_path).lstrip("\\"))

        logger.info(
            f"[LSP INIT] Primary workspace: {primary_path} "
            f"({len(filtered)} total filtered, {len(workspace_uris)} raw)"
        )

        # Передаём primary корень MCP-серверу через bridge.
        try:
            from src.core.lsp_project_bridge import write_active_project

            write_active_project(primary_path, all_workspaces=filtered)
        except Exception as e:
            logger.warning(f"[LSP INIT] Не удалось записать project_root в bridge: {e}")

        # ★ Инициализируем DI-контейнеры для КАЖДОГО workspace folder ★
        for uri in filtered:
            try:
                p = Path(urlparse(uri).path)
                if sys.platform == "win32" and str(p).startswith("\\"):
                    p = Path(str(p).lstrip("\\"))
                init_components(p, workspace_uri=uri)
            except Exception as comp_err:
                logger.warning(
                    f"[LSP INIT] Не удалось инициализировать DI для {uri}: {comp_err}"
                )

        ls._workspace_uri = primary_uri
        ls._project_root = primary_path
        ls._all_workspaces = filtered  # для будущих обработчиков
        ls._initialized = True

        return InitializeResult(
            capabilities={
                "text_document_sync": TextDocumentSyncKind.Incremental,
                # LSP 3.6+: сообщаем клиенту, что мы хотим получать
                # уведомления о смене workspace folders (если откроет ещё).
                "workspace": {
                    "workspaceFolders": {
                        "supported": True,
                        "changeNotifications": True,
                    },
                },
            }
        )

    @server.feature("initialized")
    async def on_initialized(ls: MSCodeBaseLanguageServer, params):
        """После успешной инициализации подписываемся на системный watcher редактора."""
        try:
            from lsprotocol.types import (
                DidChangeWatchedFilesRegistrationOptions,
                FileSystemWatcher,
            )

            # Фильтруем на стороне LSP-протокола, чтобы не получать
            # события для .codebase_indices/, .git/, бинарников и т.п.
            # (см. INC-53EC / REFC-08). Поддерживаемые расширения → один glob.
            ext_pattern = ",".join(sorted(e.lstrip(".") for e in SUPPORTED_EXTENSIONS))
            main_pattern = f"**/*.{{{ext_pattern}}}"
            watchers = [
                FileSystemWatcher(glob_pattern=main_pattern),
            ]
            options = DidChangeWatchedFilesRegistrationOptions(watchers=watchers)
            await ls.register_capability_async(
                "workspace/didChangeWatchedFiles", options
            )
            logger.info(
                f"[LSP INIT] Подписка на watcher оформлена "
                f"({len(SUPPORTED_EXTENSIONS)} extensions, pattern='**/*.{{...}}')"
            )
        except Exception as e:
            logger.warning(f"[LSP INIT] Не удалось подписаться на watcher: {e}")

except ImportError:
    logger.warning("pygls/lsprotocol не установлены. LSP-сервер недоступен.")
    server = None


def main():
    """Запуск LSP сервера."""
    if server is None:
        logger.error("LSP: Не удалось запустить сервер (отсутствуют зависимости)")
        sys.exit(1)

    # Чистим старые bridge-файлы при старте
    try:
        from src.core.lsp_project_bridge import cleanup_stale

        cleanup_stale()
    except Exception:
        pass

    logger.info("=" * 60)
    logger.info("MSCodeBase LSP Server запущен")
    logger.info("Версия: 1.0.0")
    logger.info(f"Python: {sys.version.split()[0]}")
    logger.info(f"Рабочая директория: {Path.cwd()}")
    logger.info(f"Поддерживаемые расширения: {len(SUPPORTED_EXTENSIONS)} типов")
    logger.info("Ожидание подключения Zed через stdio...")
    logger.info("=" * 60)
    server.start_io()


if __name__ == "__main__":
    main()
