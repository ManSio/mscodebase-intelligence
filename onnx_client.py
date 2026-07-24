#!/usr/bin/env python3
"""
ONNX Client — Discover-or-Launch клиент для ONNX Singleton Server.
Использует Windows Named Mutex для предотвращения гонки при запуске сервера.
"""

import os
import sys
import json
import time
import socket
import subprocess
import urllib.request
import threading
from pathlib import Path
from typing import List, Optional


class OnnxEmbedderClient:
    """
    Клиент для ONNX Singleton Server.
    
    Паттерн:
    1. Проверяет, запущен ли сервер на порту (health check)
    2. Если нет — пытается захватить Named Mutex
    3. Если мутекс захвачен — запускает subprocess сервер
    4. Ждёт готовности сервера
    5. Отдаёт мутекс
    6. Если мутекс занят — ждёт пока другой процесс запустит сервер
    """
    
    def __init__(self, port: int = 9876, model_name: str = "bge-m3"):
        self.port = port
        self.model_name = model_name
        self.base_url = f"http://127.0.0.1:{port}"
        self._mutex_name = f"Global\\MSCodeBase_OnnxServer_{model_name}"
        self._mutex_handle = None
        self._server_started_by_us = False
        
    def _is_server_running(self) -> bool:
        """Быстрая проверка: отвечает ли сервер на /health."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex(("127.0.0.1", self.port)) == 0
        except Exception:
            return False
    
    def _health_check(self) -> bool:
        """Полный health check через HTTP."""
        try:
            req = urllib.request.Request(f"{self.base_url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode())
                return data.get("status") == "ok"
        except Exception:
            return False
    
    def _acquire_launch_mutex(self) -> bool:
        """
        Пытается захватить Named Mutex для запуска сервера.
        Возвращает True если мы стали владельцем и должны запускать сервер.
        Возвращает False если другой процесс уже запускает/запустил сервер.
        """
        if sys.platform != 'win32':
            # На Unix используем файловый лок (упрощённо)
            return True
            
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            
            # CreateMutex с bInitialOwner=FALSE — не захватываем сразу
            self._mutex_handle = kernel32.CreateMutexW(None, False, self._mutex_name)
            last_error = kernel32.GetLastError()
            
            # ERROR_ALREADY_EXISTS = 183 — мутекс уже есть
            if last_error == 183:
                # Мутекс существует — другой процесс уже запускает сервер
                kernel32.CloseHandle(self._mutex_handle)
                self._mutex_handle = None
                return False
            
            # Мутекс создан нами, захватываем его
            result = kernel32.WaitForSingleObject(self._mutex_handle, 10000)  # 10 сек таймаут
            if result not in (0, 128):  # WAIT_OBJECT_0 = 0, WAIT_ABANDONED = 128
                kernel32.CloseHandle(self._mutex_handle)
                self._mutex_handle = None
                return False
                
            return True
            
        except Exception as e:
            print(f"[ONNX Client] Mutex error: {e}", file=sys.stderr)
            return True  # На всякий случай пробуем запустить
    
    def _release_launch_mutex(self):
        """Освобождает мутекс запуска."""
        if self._mutex_handle and sys.platform == 'win32':
            try:
                import ctypes
                ctypes.windll.kernel32.ReleaseMutex(self._mutex_handle)
                ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
            except Exception:
                pass
            self._mutex_handle = None
    
    def _launch_server(self) -> bool:
        """Запускает onnx_server.py как detached процесс."""
        server_script = PROJECT_ROOT / "onnx_server.py"
        if not server_script.exists():
            print(f"[ONNX Client] Server script not found: {server_script}", file=sys.stderr)
            return False
        
        # Флаги для Windows: DETACHED_PROCESS | CREATE_NO_WINDOW
        creation_flags = 0
        if sys.platform == 'win32':
            creation_flags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
        
        env = os.environ.copy()
        env["ONNX_PORT"] = str(self.port)
        env["ONNX_IDLE_TIMEOUT"] = "600"
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        
        try:
            proc = subprocess.Popen(
                [sys.executable, str(server_script), f"--port={self.port}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=creation_flags,
                cwd=str(PROJECT_ROOT)
            )
            self._server_pid = proc.pid
            self._server_started_by_us = True
            print(f"[ONNX Client] Launched server PID={proc.pid}", file=sys.stderr)
            return True
        except Exception as e:
            print(f"[ONNX Client] Failed to launch server: {e}", file=sys.stderr)
            return False
    
    def _wait_for_server(self, timeout: float = 30.0) -> bool:
        """Ждёт готовности сервера."""
        start = time.time()
        while time.time() - start < timeout:
            if self._health_check():
                return True
            time.sleep(0.5)
        return False
    
    def ensure_server_running(self) -> bool:
        """
        Гарантирует, что сервер запущен.
        Thread-safe: использует модульный lock для координации между потоками.
        """
        # Быстрая проверка без лока
        if self._health_check():
            return True
        
        # Межпоточный lock (на случай если несколько потоков одновременно вызывают)
        with _client_lock:
            # Double-check под локом
            if self._health_check():
                return True
            
            # Пытаемся захватить межпроцессный мутекс
            if not self._acquire_launch_mutex():
                # Другой процесс запускает — ждём
                print(f"[ONNX Client] Waiting for another process to start server...", file=sys.stderr)
                return self._wait_for_server()
            
            # Мы владелец мутекса — запускаем сервер
            try:
                if not self._launch_server():
                    return False
                return self._wait_for_server()
            finally:
                self._release_launch_mutex()
    
    def embed(self, text: str) -> List[float]:
        """Эмбеддинг одного текста."""
        if not self.ensure_server_running():
            raise RuntimeError("ONNX server not available")
        
        data = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/embed",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            if "error" in result:
                raise RuntimeError(result["error"])
            return result["vector"]
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Эмбеддинг батча текстов."""
        if not self.ensure_server_running():
            raise RuntimeError("ONNX server not available")
        
        data = json.dumps({"texts": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/embed_batch",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
            if "error" in result:
                raise RuntimeError(result["error"])
            return result["vectors"]
    
    def shutdown(self):
        """Явное завершение (для тестов)."""
        if self._server_started_by_us and hasattr(self, '_server_pid'):
            try:
                if sys.platform == 'win32':
                    subprocess.run(['taskkill', '/F', '/PID', str(self._server_pid)], 
                                 capture_output=True)
                else:
                    os.kill(self._server_pid, 15)
            except Exception:
                pass


# Глобальный lock для координации внутри процесса
_client_lock = threading.Lock()

# Путь к корню проекта
PROJECT_ROOT = Path(__file__).resolve().parent

# ─── Singleton accessor ────────────────────────────────────

_client_instance: Optional[OnnxEmbedderClient] = None
_client_lock_module = threading.Lock()

def get_onnx_client(port: int = 9876, model_name: str = "bge-m3") -> OnnxEmbedderClient:
    """Возвращает singleton клиент ONNX."""
    global _client_instance
    with _client_lock_module:
        if _client_instance is None:
            _client_instance = OnnxEmbedderClient(port=port, model_name=model_name)
        return _client_instance


# ─── Удобные функции ──────────────────────────────────────

def embed_text(text: str, port: int = 9876) -> List[float]:
    """Быстрый вызов: эмбеддинг одного текста."""
    return get_onnx_client(port).embed(text)

def embed_batch(texts: List[str], port: int = 9876) -> List[List[float]]:
    """Быстрый вызов: эмбеддинг батча."""
    return get_onnx_client(port).embed_batch(texts)


if __name__ == "__main__":
    # CLI для тестов
    import sys
    client = get_onnx_client()
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        vec = client.embed(text)
        print(f"Dim: {len(vec)}, first 5: {vec[:5]}")
    else:
        print("Usage: python onnx_client.py <text>")