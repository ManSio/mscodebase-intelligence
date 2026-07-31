"""
test_lsp_uri_conversion.py — unit-тесты _path_to_uri / _uri_to_path (WIN-3/WIN-4).

Покрывает:
1. Windows-путь C:\\x\\y.py → file:///C:/x/y.py → обратно
2. POSIX-путь /home/user/a.py → file:///home/user/a.py → обратно
3. UNC-путь \\\\server\\share\\file.py → file://server/share/file.py (WIN-3)
4. UNC URI file://server/share/file.py → //server/share/file.py (WIN-4)
5. Обратный round-trip: uri_to_path(path_to_uri(p)) восстанавливает p
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.core.lsp_client import LspClient


class TestPathToUri:
    def test_windows_drive_path(self):
        """C:\\x\\y.py → file:///C:/x/y.py (Windows)."""
        uri = LspClient._path_to_uri(r"C:\x\y.py")
        assert uri.startswith("file:///")
        assert "C:/x/y.py" in uri

    def test_posix_path(self):
        """/home/user/a.py → file:///home/user/a.py (на POSIX-платформах)."""
        if sys.platform == "win32":
            pytest.skip("POSIX-пути неразрешимы на Windows (монтируются на текущий диск)")
        uri = LspClient._path_to_uri("/home/user/a.py")
        assert uri == "file:///home/user/a.py"

    def test_unc_path(self):
        """\\\\server\\share\\file.py → file://server/share/file.py (WIN-3).

        Path.as_uri() для UNC возвращает authority (server), а не путь.
        """
        uri = LspClient._path_to_uri(r"\\server\share\file.py")
        # Path.as_uri() на Windows: file://server/share/file.py
        assert uri.startswith("file://")
        # authority = server — нет тройного слеша после file:
        assert "file:///" not in uri, f"UNC-путь получил лишний слеш: {uri}"
        assert "server" in uri and "share" in uri


class TestUriToPath:
    def test_windows_drive_uri(self):
        """file:///C:/x/y.py → C:/x/y.py."""
        p = LspClient._uri_to_path("file:///C:/x/y.py")
        assert p.replace("\\", "/").endswith("C:/x/y.py")

    def test_posix_uri(self):
        """file:///home/user/a.py → /home/user/a.py (на POSIX-платформах)."""
        if sys.platform == "win32":
            pytest.skip("POSIX-пути неразрешимы на Windows (монтируются на текущий диск)")
        p = LspClient._uri_to_path("file:///home/user/a.py")
        assert p == "/home/user/a.py"

    @pytest.mark.skipif(sys.platform != "win32", reason="UNC специфичен для Windows")
    def test_unc_uri(self):
        """file://server/share/file.py → //server/share/file.py (WIN-4)."""
        p = LspClient._uri_to_path("file://server/share/file.py")
        assert p.startswith("//server/share/"), f"UNC-путь не восстановлен: {p}"

    def test_round_trip_windows(self):
        """round-trip: uri_to_path(path_to_uri(p)) восстанавливает p."""
        if sys.platform == "win32":
            original = r"C:\x\y.py"
        else:
            original = "/home/user/y.py"
        uri = LspClient._path_to_uri(original)
        restored = LspClient._uri_to_path(uri)
        # Нормализуем разделители — на Windows Path.resolve может вернуть \.
        assert Path(restored).as_posix() == Path(original).as_posix(), (
            f"round-trip сломан: {original} → {uri} → {restored}"
        )
