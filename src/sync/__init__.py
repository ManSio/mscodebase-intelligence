"""Live-sync subsystem: editor RAM buffer → демон (out-of-the-box мульти-IDE).

Этот пакет реализует плоскость «живого буфера» (см. архитектурный обзор
2026-08-24): изменения из оперативной памяти редактора (до сохранения на
диск) перехватываются расширением IDE и передаются в демон MSCodeBase через
WebSocket. Демон держит актуальное содержимое в RAM-оверлее (LiveBuffer) и
отдаёт его на чтение/поиск с приоритетом над диском.

ВАЖНО (Red Team §1.16 / §2.3): LiveBuffer НИКОГДА не пишет несохранённое
содержимое на диск. Несохранённый буфер эфемерен по определению — он живёт
только в RAM до момента save (тогда overlay сбрасывается, а диск-индекс
обновляется отдельно, дебаунсом).
"""
from __future__ import annotations

from .live_buffer import LiveBuffer, get_live_buffer
from .server import LiveSyncServer

__all__ = ["LiveBuffer", "get_live_buffer", "LiveSyncServer"]
