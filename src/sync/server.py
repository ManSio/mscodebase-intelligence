"""LiveSyncServer — WebSocket-эндпоинт приёма изменений из редакторов.

Работает ВНУТРИ демона (remote_main): один процесс демона одновременно
служит MCP (stdio/HTTP) и принимает живые изменения из всех IDE/расширений
через единый WebSocket `/ws/sync`.

Протокол (JSON, одно сообщение = один JSON-объект на строку/фрейм):
  Client → Server:
    {"type":"hello", "root":"<abs>", "repo_id":"<str>",
     "dirty":[{"abs_path":"<abs>", "content":"...", "version":N}]}
    {"type":"change", "root":"<abs>", "abs_path":"<abs>",
     "content":"...", "version":N, "client_id":"<str>"}
    {"type":"save",  "root":"<abs>", "abs_path":"<abs>"}
    {"type":"close", "root":"<abs>", "abs_path":"<abs>"}
  Server → Client:
    {"type":"registered", "root":"<abs>", "state":"READY|INDEXING|STARTING|FAILED"}
    {"type":"ack", "root":"<abs>", "abs_path":"<abs>", "version":N}
    {"type":"error", "message":"..."}

Проектная идентичность (out-of-the-box, §0.0 желания пользователя):
- Никакого ручного пути: расширение само шлёт `root` = свой workspace-folder;
- Демон только ТАК и узнаёт проект (MCP roots-модель) → убираем угадывание
  из CWD/Zed-SQLite/ext_root и **запрещаем self-index** (нет fallback'а на
  самого себя — тем самым закрыт сценарий «парсит сам себя»).
- Авто-регистрация: `registry.get_indexer(root, factory=factory)` лениво
  создаёт Indexer (STARTING→INDEXING/READY) и триггерит индекс — без
  участия человека.

Безопасность (домашняя сеть): Bearer-токен из MSCODEBASE_REMOTE_TOKEN, тот же
что и для HTTP-гейта. Пустой токен = auth выключен (localhost-сценарий).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from starlette.websockets import WebSocket, WebSocketState

from src.core.di_container import IndexerFactoryKey, ServiceCollection
from src.core.indexing.project_indexer_registry import ProjectIndexerRegistry
from src.sync.live_buffer import LiveBuffer, get_live_buffer

logger = logging.getLogger("mscodebase_server.live_sync")

# Состояния, понятные клиенту (из ProjectState).
_STATE_NAMES = {
    "STARTING": "STARTING",
    "INDEXING": "INDEXING",
    "READY": "READY",
    "FAILED": "FAILED",
    "UNINITIALIZED": "UNINITIALIZED",
}


class LiveSyncServer:
    """Принимает живые изменения из редакторов по WebSocket."""

    def __init__(
        self,
        services: ServiceCollection,
        live_buffer: Optional[LiveBuffer] = None,
        registry: Optional[ProjectIndexerRegistry] = None,
        factory: Optional[Callable[[Path], Any]] = None,
        token: Optional[str] = None,
    ) -> None:
        self._services = services
        self._buffer = live_buffer or get_live_buffer()
        # registry/factory — из глобального DI (ProjectIndexerRegistry это
        # module-singleton, IndexerFactoryKey резолвится из того же контейнера).
        if registry is None:
            registry = services.resolve(ProjectIndexerRegistry)
        if factory is None:
            factory = services.resolve(IndexerFactoryKey)
        self._registry = registry
        self._factory = factory
        self._token = token if token is not None else os.environ.get(
            "MSCODEBASE_REMOTE_TOKEN", ""
        ).strip()

        # Фоновая TTL-сборка мусора оверлея.
        self._sweeper = threading.Thread(
            target=self._sweep_loop, name="live-buffer-sweeper", daemon=True
        )
        self._sweeper.start()

    # ─── ASGI WebSocket endpoint (Starlette) ───────────────────────
    async def handle_websocket(self, websocket: WebSocket) -> None:
        """Starlette WebSocketRoute handler: /ws/sync."""
        if not self._auth_ok(websocket):
            await websocket.close(code=1008)  # Policy violation
            return
        await websocket.accept()
        logger.info("[live-sync] WS подключён")
        try:
            while True:
                raw = await websocket.receive_text()
                await self._on_message(websocket, raw)
        except Exception as e:  # noqa: BLE001 - любое исключение = завершение WS-сессии
            # Нормальное завершение — disconnect (WebSocketDisconnect).
            logger.debug(f"[live-sync] WS сессия завершена: {type(e).__name__}: {e}")
        finally:
            logger.info("[live-sync] WS отключён")

    # ─── Обработка сообщений ───────────────────────────────────────
    async def _on_message(self, websocket: WebSocket, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await self._send(websocket, {"type": "error", "message": "bad json"})
            return
        mtype = msg.get("type")
        try:
            if mtype == "hello":
                await self._on_hello(websocket, msg)
            elif mtype == "change":
                await self._on_change(websocket, msg)
            elif mtype == "save":
                await self._on_save(websocket, msg)
            elif mtype == "close":
                await self._on_close(websocket, msg)
            else:
                await self._send(
                    websocket, {"type": "error", "message": f"unknown type: {mtype}"}
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[live-sync] ошибка обработки {mtype}: {e}")
            await self._send(websocket, {"type": "error", "message": str(e)})

    async def _on_hello(self, websocket: WebSocket, msg: dict) -> None:
        root = msg.get("root")
        if not root or not Path(root).is_absolute():
            await self._send(
                websocket, {"type": "error", "message": "hello: abs root required"}
            )
            return
        root_path = Path(root).resolve()
        if not root_path.exists() or not root_path.is_dir():
            await self._send(
                websocket, {"type": "error", "message": f"root not a dir: {root}"}
            )
            return
        # Авто-регистрация проекта (roots-only: никакого self-index fallback).
        state = await self._ensure_project(root_path)
        await self._send(
            websocket, {"type": "registered", "root": str(root_path), "state": state}
        )
        # Ре-синхронизация несохранённых буферов после реконнекта (идемпотентно).
        for d in msg.get("dirty", []) or []:
            ap = d.get("abs_path")
            if ap and d.get("content") is not None:
                self._buffer.update(ap, d["content"], int(d.get("version", 0) or 0))
        logger.info(f"[live-sync] hello: project {root_path.name} → {state}")

    async def _on_change(self, websocket: WebSocket, msg: dict) -> None:
        ap = msg.get("abs_path")
        content = msg.get("content")
        version = int(msg.get("version", 0) or 0)
        if not ap or content is None:
            return
        applied = self._buffer.update(ap, content, version)
        if applied:
            # Подтверждаем только применённую версию (для диагностики клиента).
            await self._send(
                websocket,
                {
                    "type": "ack",
                    "abs_path": ap,
                    "version": version,
                },
            )

    async def _on_save(self, websocket: WebSocket, msg: dict) -> None:
        ap = msg.get("abs_path")
        root = msg.get("root")
        if not ap:
            return
        # 1) Сбрасываем оверлей: теперь диск — авторитет.
        self._buffer.drop(ap)
        # 2) Дебаунс-обновление постоянного индекса (как notify_change, но
        #    без спама на каждый клик — событие save уже редкое).
        if root:
            await self._reindex_file(Path(root).resolve(), Path(ap).resolve())

    async def _on_close(self, websocket: WebSocket, msg: dict) -> None:
        ap = msg.get("abs_path")
        if ap:
            # Несохранённое содержимое потеряно (редактор закрыл файл) — держать
            # в оверлее незачем.
            self._buffer.drop(ap)

    # ─── Внутреннее ───────────────────────────────────────────────
    async def _ensure_project(self, root_path: Path) -> str:
        """Авто-регистрирует проект в реестре (lazy create + index)."""
        try:
            self._registry.get_indexer(root_path, factory=self._factory)
            state = self._registry.get_state(root_path)
            return _STATE_NAMES.get(str(state), str(state))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[live-sync] ensure_project failed for {root_path}: {e}")
            return "FAILED"

    async def _reindex_file(self, root_path: Path, abs_path: Path) -> None:
        """Дебаунс-переиндексация одного файла (mirrors notify_change)."""
        try:
            indexer = self._registry.get_indexer(root_path, factory=self._factory)
            rel = abs_path.relative_to(root_path)
            rel_str = str(rel)

            async def _bg():
                try:
                    await asyncio.to_thread(
                        indexer._index_single_file,
                        abs_path,
                        rel_str,
                        content=None,  # берём с диска (только что saved)
                        source="filesystem",
                    )
                    batch = getattr(indexer, "bm25_batch", None)
                    if batch is not None:
                        await batch.add(rel_str)
                    elif indexer.searcher:
                        await asyncio.to_thread(indexer.searcher.reindex)
                    logger.info(f"📊 live-sync save reindex done: {rel_str}")
                except Exception as _e:  # noqa: BLE001 - фоновая переиндексация, логируем и продолжаем
                    logger.warning(f"live-sync reindex error {rel_str}: {_e}")

            asyncio.create_task(_bg())
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[live-sync] reindex_file skip {abs_path}: {e}")

    def _auth_ok(self, websocket: WebSocket) -> bool:
        if not self._token:
            return True  # auth выключен (localhost)
        auth = websocket.headers.get("authorization", "")
        return auth == f"Bearer {self._token}"

    @staticmethod
    async def _send(websocket: WebSocket, obj: dict) -> None:
        try:
            if websocket.application_state == WebSocketState.CONNECTED:
                await websocket.send_text(json.dumps(obj, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass

    def _sweep_loop(self) -> None:
        while True:
            try:
                self._buffer.sweep()
            except Exception:  # noqa: BLE001
                pass
            # 5 мин интервал.
            threading.Event().wait(300)
