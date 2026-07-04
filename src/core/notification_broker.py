# src/core/notification_broker.py
import asyncio
import logging
from typing import Optional, Any, Dict

logger = logging.getLogger("mscodebase.notification_broker")

class NotificationBroker:
    """Глобальный брокер событий для отправки Push-уведомлений в Zed через JSON-RPC."""

    def __init__(self) -> None:
        self._session: Optional[Any] = None  # Инстанс BaseSession из mcp
        self._lock = asyncio.Lock()

    def attach_session(self, session: Any) -> None:
        """Динамически связывает активную сессию stdio-транспорта с брокером.

        Вызывается в mcp/server.py в момент инициализации JSON-RPC соединения.
        """
        self._session = session
        logger.info("JSON-RPC session successfully attached to NotificationBroker.")

    def detach_session(self) -> None:
        """Сбрасывает сессию при закрытии соединения во избежание утечек памяти."""
        self._session = None
        logger.info("JSON-RPC session detached from NotificationBroker.")

    async def publish(self, method: str, params: Dict[str, Any]) -> bool:
        """Безопасно отправляет асинхронное уведомление (Push) в Zed IDE.

        Возвращает True в случае успешной отправки, иначе False.
        """
        async with self._lock:
            if not self._session:
                logger.debug(f"Drop event '{method}': No active JSON-RPC session attached.")
                return False

            try:
                # Проверяем гипотетический статус активности сессии, если он доступен в API
                if hasattr(self._session, "is_active") and not self._session.is_active:
                    return False

                await self._session.send_notification(method, params)
                return True
            except Exception as e:
                logger.error(f"Failed to publish notification '{method}': {e}", exc_info=True)
                return False
