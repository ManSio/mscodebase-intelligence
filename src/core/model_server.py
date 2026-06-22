"""
Единый фоновый сервер модели эмбеддингов.
- Запускается install.py при установке расширения
- Живёт как фоновый процесс
- MCP-сервера подключаются к нему через httpx
- При завершении последнего проекта в Zed — выключается через 60с

Запуск:
  python -m src.core.model_server --daemon

Остановка:
  python -m src.core.model_server --stop
"""

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

# ============================================================================
# Пути
# ============================================================================

_EXT_DIR: Path | None = None


def ext_dir() -> Path:
    global _EXT_DIR
    if _EXT_DIR is None:
        _EXT_DIR = Path(__file__).resolve().parent.parent.parent
    return _EXT_DIR


def pid_file() -> Path:
    return ext_dir() / ".model_server.pid"


def port_file() -> Path:
    return ext_dir() / ".model_server.port"


def server_info() -> tuple[int, int] | None:
    pf, pt = pid_file(), port_file()
    if not pf.exists() or not pt.exists():
        return None
    try:
        return int(pf.read_text().strip()), int(pt.read_text().strip())
    except (ValueError, OSError):
        return None


class ModelServer:
    """Запускает HTTP-сервер с моделью. Должен работать в отдельном процессе."""

    def __init__(self):
        self.server: HTTPServer | None = None
        self._embedder = None
        self._refcount = 0
        self._lock = Lock()

    def run(self, port: int):
        """Загружает модель и запускает сервер. Блокирующий вызов."""
        from src.core.embedder import Embedder

        # Принудительно локальный режим
        os.environ["EMBEDDING_MODE"] = "local"

        model_dir = ext_dir() / os.getenv("MODEL_DIR", ".codebase_models")
        logger.info(f"Загрузка модели из {model_dir}...")
        self._embedder = Embedder(model_dir=model_dir)
        t = time.time()
        ok = self._embedder.load()
        if not ok:
            logger.error("Не удалось загрузить модель")
            return False

        logger.info(
            f"Модель загружена за {time.time() - t:.1f}с, размерность={self._embedder.dimension}"
        )

        pid_file().write_text(str(os.getpid()))
        port_file().write_text(str(port))

        self.server = HTTPServer(("127.0.0.1", port), _make_handler(self))
        logger.info(f"Model server запущен на порту {port} (PID={os.getpid()})")
        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.server.server_close()
            pid_file().unlink(missing_ok=True)
            port_file().unlink(missing_ok=True)
        return True

    def embed_batch(self, texts: list[str], is_query: bool) -> list[list[float]]:
        if not self._embedder or not self._embedder.is_available:
            return [[] for _ in texts]
        return self._embedder.embed_batch(texts, is_query=is_query)


def _make_handler(server: ModelServer):
    """Фабрика классов-обработчиков с замыканием на сервер."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                ok = server._embedder and server._embedder.is_available
                self._json({"status": "ok" if ok else "loading"})
            elif self.path == "/info":
                if server._embedder:
                    self._json(
                        {
                            "provider": server._embedder.active_provider,
                            "dimension": server._embedder.dimension,
                            "model_name": server._embedder.model_name,
                            "available": server._embedder.is_available,
                        }
                    )
                else:
                    self._json({"available": False})
            else:
                self.send_error(404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                self._json({"error": "empty"}, 400)
                return
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._json({"error": "invalid json"}, 400)
                return

            if self.path == "/embed":
                try:
                    if not server._embedder:
                        self._json({"error": "embedder not ready"}, 503)
                        return
                    vec = server._embedder.embed(
                        data.get("text", ""),
                        is_query=data.get("is_query", False),
                    )
                    self._json({"embedding": vec})
                except Exception as e:
                    self._json({"error": str(e)}, 500)

            elif self.path == "/embed_batch":
                try:
                    embs = server.embed_batch(
                        data.get("texts", []),
                        data.get("is_query", False),
                    )
                    self._json({"embeddings": embs})
                except Exception as e:
                    self._json({"error": str(e)}, 500)
            else:
                self.send_error(404)

        def _json(self, data, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def log_message(self, format, *args):
            logger.debug("HTTP: " + format % args)

    return Handler


def daemonize(port: int):
    """Запускает сервер как detached-процесс на Windows."""
    python = sys.executable
    script = Path(__file__).resolve()
    env = os.environ.copy()
    env["EMBEDDING_MODE"] = "local"

    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        [python, "-u", str(script), "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        creationflags=flags,
    )

    # Ждём готовности
    for _ in range(60):
        time.sleep(0.5)
        try:
            import urllib.request

            r = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            if r.status == 200:
                return True
        except Exception:
            continue
    return False


def stop_server():
    info = server_info()
    if not info:
        print("Model server не запущен")
        return
    pid, _ = info
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=5)
    pid_file().unlink(missing_ok=True)
    port_file().unlink(missing_ok=True)
    print(f"Model server (PID={pid}) остановлен")


def remote_embedder():
    """Создаёт RemoteEmbedder, подключаясь к работающему серверу."""
    from src.core.remote_embedder import RemoteEmbedder

    info = server_info()
    if not info:
        # Пробуем запустить
        port = _find_free_port()
        ok = daemonize(port)
        if not ok:
            logger.error("Не удалось запустить model server")
            return None
        # Ждём появления pid файла
        for _ in range(10):
            info = server_info()
            if info:
                break
            time.sleep(0.5)
        if not info:
            return None

    pid, port = info
    re = RemoteEmbedder(port=port)
    return re if re.is_available else None


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [ModelServer] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.stop:
        stop_server()
    elif args.status:
        info = server_info()
        if info:
            pid, port = info
            import urllib.request

            try:
                h = json.loads(
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/health", timeout=2
                    ).read()
                )
                i = json.loads(
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/info", timeout=2
                    ).read()
                )
                print(
                    f"PID={pid} port={port} health={h['status']} model={i.get('model_name', '?')} dim={i.get('dimension', '?')}"
                )
            except Exception as e:
                print(f"PID={pid} error={e}")
        else:
            print("Model server не запущен")
    elif args.daemon or args.port:
        port = args.port or _find_free_port()
        srv = ModelServer()
        srv.run(port)
    else:
        parser.print_help()
