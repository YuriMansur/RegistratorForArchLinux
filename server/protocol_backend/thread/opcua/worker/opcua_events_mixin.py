"""
EventsMixin — подписка на OPC UA события
=========================================

Mixin-класс: поддержка OPC UA Events (аварии, условия, системные уведомления).

В отличие от Data Change (изменение значения переменной),
Events — это разовые уведомления:
  - Alarm triggered   (авария сработала)
  - Condition changed (состояние изменилось)
  - System event      (перезагрузка сервера, ошибка)

Цепочка доставки:
  Сервер генерирует Event
    → asyncua доставляет в _EventHandler.event_notification()
    → EventsMixin._on_event callback
    → пользовательский код

Содержит:
  - _EventHandler          — внутренний адаптер asyncua → callback
  - subscribe_events()     — подписаться на события источника
  - unsubscribe_events()   — отписаться

Использование:
    class AsyncOpcUaWorker(EventsMixin, ...):
        ...
"""

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class EventsMixin:
    """
    Mixin для подписки на OPC UA события.

    Предполагает что подкласс имеет атрибуты:
        self.is_connected          — bool property
        self.client                — asyncua.Client
        self._event_subscriptions  — Dict[str, Dict[str, Any]]
        self._on_event             — Optional[Callable]
        self._get_cached_node()    — метод
    """

    class _EventHandler:
        """Внутренний адаптер asyncua → callback для OPC UA событий."""

        def __init__(self, callback: Optional[Callable[[Dict[str, Any]], None]] = None):
            self.callback = callback

        def event_notification(self, event) -> None:
            """
            Вызывается автоматически asyncua при получении события.

            Args:
                event: Объект события от asyncua.
                    Содержит поля: SourceName, Message, Severity, Time и др.
            """
            if not self.callback:
                return
            try:
                # severity обёрнут в try: на случай нечислового значения от сервера.
                try:
                    severity = int(getattr(event, 'Severity', 0))
                except (TypeError, ValueError):
                    severity = 0
                event_dict = {
                    "source":     str(getattr(event, 'SourceName', 'Unknown')),
                    "message":    str(getattr(event, 'Message', '')),
                    "severity":   severity,
                    "time":       getattr(event, 'Time', None),
                    "event_type": str(getattr(event, 'EventType', 'Unknown')),
                }
                self.callback(event_dict)
            except Exception as e:
                logger.error(f"EventHandler: error processing event: {e}")

    # Подписка на события
    async def subscribe_events(
        self,
        source_node_id: Optional[str] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> bool:
        """
        Подписаться на события (аварии, условия, системные уведомления).

        Args:
            source_node_id: Узел-источник событий.
                None — подписка на Server object (все события сервера).
                "ns=2;s=MyDevice" — события конкретного устройства.

            event_callback: Функция-обработчик событий.
                Принимает один аргумент — словарь с полями события:
                {
                    "source":     "PLC1",
                    "message":    "Temperature alarm triggered",
                    "severity":   500,          # 0-1000 (0=info, 1000=critical)
                    "time":       datetime(...),
                    "event_type": "AlarmConditionType"
                }

        Returns:
            True если подписка создана.

        Raises:
            ConnectionError: Не подключены.
            RuntimeError: Ошибка подписки.

        Пример:
            def on_event(event):
                print(f"ALARM: {event['message']} (severity={event['severity']})")

            await worker.subscribe_events(
                source_node_id="ns=2;s=PLC1",
                event_callback=on_event
            )
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to OPC UA server")

        try:
            from asyncua import ua

            # Сохраняем callback для событий
            if event_callback:
                self._on_event = event_callback

            # Определяем источник событий
            if source_node_id:
                source = self._get_cached_node(source_node_id)
            else:
                # Server object — получаем все события сервера
                source = self.client.get_node(ua.ObjectIds.Server)

            # Создаём обработчик событий
            handler = self._EventHandler(callback=self._on_event)

            # Создаём отдельную подписку для событий.
            # asyncua требует отдельный handler с event_notification(),
            # несовместимый с datachange_notification handler'ом.
            sub = await self.client.create_subscription(500, handler)
            handle = await sub.subscribe_events(source)

            # Сохраняем объект подписки и handle для корректной отписки
            key = source_node_id or "server"
            self._event_subscriptions[key] = {"sub": sub, "handle": handle}
            logger.info(f"Event subscription created for: {key}")
            return True

        except Exception as e:
            raise RuntimeError(f"Failed to subscribe to events: {e}")

    # Отписка от событий
    async def unsubscribe_events(self, source_node_id: Optional[str] = None) -> bool:
        """
        Отписаться от событий.

        Args:
            source_node_id: Источник событий для отписки.
                None — отписка от Server object.
        """
        key = source_node_id or "server"
        if key in self._event_subscriptions:
            try:
                await self._event_subscriptions[key]["sub"].delete()
            except Exception as e:
                logger.warning(f"Failed to delete event subscription '{key}': {e}")
            del self._event_subscriptions[key]
            logger.info(f"Event subscription removed: {key}")
        return True
