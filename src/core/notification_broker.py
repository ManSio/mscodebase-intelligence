# src/core/notification_broker.py
import asyncio
import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger("mscodebase.notification_broker")

class NotificationBroker:
    """Глобальный брокер событий для отправки Push-уведомлений в Zed через JSON-RPC.

    Lock выбран threading.Lock (не asyncio.Lock), потому что:
    - Брокер шарится между LSP- и MCP-процессами (DI-контейнер),
      у каждого свой event loop.
    - asyncio.Lock привязывается к loop, в котором его впервые await'нули —
      это дедлок при кросс-loop использовании.
    - Реальные операции здесь — send_notification (await) под Lock,
      а сам Lock защищает только session-указатель от race.
    """

    def __init__(self) -> None:
        self._session: Optional[Any] = None  # Инстанс BaseSession из mcp
        self._lock = threading.Lock()  # см. INC-53EC / REFC-03
        self._publish_lock = threading.Lock()  # защищает сериализацию publish_sync

    def attach_session(self, session: Any) -> None:
        """Динамически связывает активную сессию stdio-транспорта с брокером.

        Вызывается в mcp/server.py в момент получения нотификации initialized.
        Перед сохранением новой сессии принудительно detachит старую —
        это защита от hot-reload Rust-расширения, когда старая сессия
        уже закрыта, но объект ещё висит в памяти.
        """
        with self._lock:
            self._session = session
        logger.info("🔗 JSON-RPC session attached to NotificationBroker.")

    def detach_session(self) -> None:
        """Сбрасывает сессию при закрытии соединения во избежание утечек памяти."""
        with self._lock:
            self._session = None
        logger.info("JSON-RPC session detached from NotificationBroker.")

    def _get_session(self) -> Optional[Any]:
        with self._lock:
            return self._session

    async def publish(self, method: str, params: Dict[str, Any]) -> bool:
        """Безопасно отправляет асинхронное уведомление (Push) в Zed IDE.

        Вызывается из async-контекста (других корутин).
        Возвращает True в случае успешной отправки, иначе False.
        """
        session = self._get_session()
        if not session:
            logger.debug(f"Drop event '{method}': No active JSON-RPC session attached.")
            return False

        try:
            if hasattr(session, "is_active") and not session.is_active:
                return False

            await session.send_notification(method, params)
            return True
        except Exception as e:
            logger.error(f"Failed to publish notification '{method}': {e}", exc_info=True)
            return False

    def publish_sync(self, method: str, params: Dict[str, Any]) -> bool:
        """Синхронная версия publish() для вызова из thread-потоков (Indexer).

        Использует asyncio.run_coroutine_threadsafe для безопасной отправки
        из любого thread-пула в основной event loop.
        """
        # _publish_lock сериализует одновременные publish_sync из разных
        # thread-ов (например, Indexer + CircuitBreaker callback).
        with self._publish_lock:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        self.publish(method, params), loop
                    )
                    # Ждём до 2 секунд (не блокируем Indexer надолго)
                    future.result(timeout=2.0)
                    return True
            except asyncio.TimeoutError:
                logger.debug(f"publish_sync timeout: {method}")
            except RuntimeError:
                logger.debug(f"publish_sync: no event loop, drop: {method}")
            except Exception as e:
                logger.debug(f"publish_sync error: {e}")
        return False
