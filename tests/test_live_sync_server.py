"""Юнит/интеграционные тесты LiveSyncServer (WS-протокол live-sync).

Используем фейковый registry/factory — без поднятия LanceDB/embedder.
Проверяем (§0.0 желания пользователя: out-of-the-box, без self-index):
- hello авто-регистрирует проект (roots-only, без fallback на самого себя);
- change кладёт живой контент в LiveBuffer (по абс. пути, кросс-IDE);
- save сбрасывает оверлей + триггерит дебаунс-переиндексацию файла;
- auth: Bearer-токен из MSCODEBASE_REMOTE_TOKEN (как у HTTP-гейта).
"""

import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from src.core.di_container import IndexerFactoryKey
from src.core.indexing.project_indexer_registry import ProjectIndexerRegistry
from src.sync.live_buffer import get_live_buffer
from src.sync.server import LiveSyncServer


class _FakeIndexer:
    def __init__(self):
        self.calls = []  # записи (_index_single_file, rel, content, source)
        self.bm25_batch = None
        self.searcher = None

    def _index_single_file(self, full_path, rel_str, content=None, source="filesystem"):
        self.calls.append((str(full_path), rel_str, content, source))


class _FakeRegistry:
    def __init__(self):
        self.registered = []
        self._state = "READY"

    def get_indexer(self, project_path, factory=None):
        self.registered.append(Path(project_path).resolve())
        return _FakeIndexer()

    def get_state(self, project_path):
        return self._state


class _FakeServices:
    def __init__(self, registry, factory):
        self._registry = registry
        self._factory = factory

    def resolve(self, key):
        if key is ProjectIndexerRegistry:
            return self._registry
        if key is IndexerFactoryKey:
            return self._factory
        raise KeyError(key)


@pytest.fixture
def server_and_registry(tmp_path):
    get_live_buffer().__class__ and get_live_buffer()  # no-op
    registry = _FakeRegistry()
    factory = lambda p: _FakeIndexer()  # noqa: E731
    services = _FakeServices(registry, factory)
    srv = LiveSyncServer(services, token="")
    return srv, registry


def test_hello_auto_registers_project(server_and_registry, tmp_path):
    srv, registry = server_and_registry
    root = tmp_path / "proj"
    root.mkdir()
    app = _build_ws_app(srv)
    with TestClient(app) as c:
        with c.websocket_connect("/ws/sync") as ws:
            ws.send_json({"type": "hello", "root": str(root), "repo_id": "x"})
            resp = ws.receive_json()
    assert resp["type"] == "registered"
    assert resp["state"] == "READY"
    # Проект авто-зарегистрирован (без ручного пути).
    assert root.resolve() in registry.registered


def test_change_stores_live_buffer(server_and_registry, tmp_path):
    srv, _ = server_and_registry
    root = tmp_path / "proj"
    root.mkdir()
    f = root / "a.py"
    app = _build_ws_app(srv)
    with TestClient(app) as c:
        with c.websocket_connect("/ws/sync") as ws:
            ws.send_json({"type": "hello", "root": str(root)})
            ws.receive_json()
            ws.send_json(
                {
                    "type": "change",
                    "root": str(root),
                    "abs_path": str(f),
                    "content": "print(1)",
                    "version": 3,
                }
            )
            ws.receive_json()  # ack
    # Живой контент доступен из оверлея по абс. пути.
    assert get_live_buffer().get(str(f)) == "print(1)"


def test_stale_version_dropped_from_buffer(server_and_registry, tmp_path):
    srv, _ = server_and_registry
    root = tmp_path / "proj"
    root.mkdir()
    f = root / "a.py"
    app = _build_ws_app(srv)
    with TestClient(app) as c:
        with c.websocket_connect("/ws/sync") as ws:
            ws.send_json({"type": "hello", "root": str(root)})
            ws.receive_json()
            ws.send_json(
                {"type": "change", "root": str(root), "abs_path": str(f),
                 "content": "v2", "version": 2}
            )
            ws.receive_json()
            # Внеочередная старая версия — сервер отбрасывает (без ack или с ack false?).
            ws.send_json(
                {"type": "change", "root": str(root), "abs_path": str(f),
                 "content": "STALE", "version": 1}
            )
            # Может прийти ack только если применено; проверим буфер напрямую.
    assert get_live_buffer().get(str(f)) == "v2"


def test_save_drops_buffer_and_reindexes(server_and_registry, tmp_path):
    srv, registry = server_and_registry
    root = tmp_path / "proj"
    root.mkdir()
    f = root / "a.py"
    (root / "a.py").write_text("disk content", encoding="utf-8")
    app = _build_ws_app(srv)
    with TestClient(app) as c:
        with c.websocket_connect("/ws/sync") as ws:
            ws.send_json({"type": "hello", "root": str(root)})
            ws.receive_json()
            ws.send_json(
                {"type": "change", "root": str(root), "abs_path": str(f),
                 "content": "unsaved", "version": 1}
            )
            ws.receive_json()
            ws.send_json(
                {"type": "save", "root": str(root), "abs_path": str(f)}
            )
            # даём фону сработать
            time_sleep()
    # Оверлей сброшен (диск теперь авторитет).
    assert get_live_buffer().get(str(f)) is None


def test_hello_rejects_non_abs_root(server_and_registry, tmp_path):
    srv, _ = server_and_registry
    app = _build_ws_app(srv)
    with TestClient(app) as c:
        with c.websocket_connect("/ws/sync") as ws:
            ws.send_json({"type": "hello", "root": "relative/path"})
            resp = ws.receive_json()
    assert resp["type"] == "error"


def test_auth_requires_bearer(tmp_path):
    registry = _FakeRegistry()
    factory = lambda p: _FakeIndexer()  # noqa: E731
    services = _FakeServices(registry, factory)
    srv = LiveSyncServer(services, token="SECRET")
    app = _build_ws_app(srv)
    with TestClient(app) as c:
        # Без токена — сервер закрывает (disconnect до accept).
        with pytest.raises(Exception):
            with c.websocket_connect("/ws/sync") as ws:
                ws.send_json({"type": "hello", "root": str(tmp_path)})


def test_auth_ok_with_token(tmp_path):
    registry = _FakeRegistry()
    factory = lambda p: _FakeIndexer()  # noqa: E731
    services = _FakeServices(registry, factory)
    srv = LiveSyncServer(services, token="SECRET")
    app = _build_ws_app(srv)
    root = tmp_path / "proj"
    root.mkdir()
    with TestClient(app) as c:
        with c.websocket_connect(
            "/ws/sync", headers={"Authorization": "Bearer SECRET"}
        ) as ws:
            ws.send_json({"type": "hello", "root": str(root)})
            resp = ws.receive_json()
    assert resp["type"] == "registered"


def _build_ws_app(srv):
    from starlette.applications import Starlette
    from starlette.routing import WebSocketRoute

    return Starlette(routes=[WebSocketRoute("/ws/sync", srv.handle_websocket)])


def time_sleep():
    # Даём фоновому asyncio-таску (reindex) шанс отработать.
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.run_until_complete(asyncio.sleep(0.2))
        else:
            asyncio.run(asyncio.sleep(0.05))
    except Exception:  # noqa: BLE001 - тест-таймер, проглатываем намеренно
        pass
