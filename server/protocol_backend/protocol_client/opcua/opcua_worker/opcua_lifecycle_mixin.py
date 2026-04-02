"""
LifecycleMixin — polling циклы + auto-reconnect + watchdog
===========================================================

Объединяет три тесно связанных механизма управления жизненным циклом соединения:

  1. Poll Loops — именованные циклы периодического опроса тегов.
     Поддерживает несколько параллельных циклов с разными интервалами:
       "fast" (200мс) — критичные теги
       "slow" (5с)    — статусные теги

  2. Auto-Reconnect — цикл повторных подключений при обрыве.
     При успехе восстанавливает подписки и poll loop'ы.

  3. Connection Watchdog — heartbeat-проверка живости соединения.
     Обнаруживает обрыв ДО ошибки в read/write → запускает reconnect раньше.

Почему они объединены (а не в отдельных файлах):
  ┌──────────────┐       ConnectionError       ┌──────────────────┐
  │  _poll_loop  │ ─────────────────────────►  │ _start_reconnect │
  └──────────────┘                             │       _loop      │
  ┌──────────────┐       connection lost        │                  │
  │_watchdog_loop│ ─────────────────────────►  │                  │
  └──────────────┘                             └────────┬─────────┘
                                                        │ success
                                                        ▼
                                               start_polling()  ← вызывает PollingMixin

Содержит:
  Poll Loops:
    - start_polling()      — запустить именованный цикл
    - stop_polling()       — остановить один или все циклы
    - _stop_single_poll()  — внутренний: остановить один цикл
    - _poll_loop()         — внутренний: тело цикла
    - get_active_polls()   — информация об активных циклах

  Auto-Reconnect:
    - _start_reconnect_loop()  — запустить цикл (внутренний)
    - _reconnect_loop()        — тело цикла (внутренний)
    - trigger_reconnect()      — ручной запуск reconnect
    - stop_reconnect()         — остановить reconnect

  Watchdog:
    - start_watchdog()         — запустить проверку живости
    - stop_watchdog()          — остановить watchdog
    - _watchdog_loop()         — тело цикла (внутренний)
    - is_watchdog_active       — property: watchdog запущен?

Использование:
    class AsyncOpcUaWorker(LifecycleMixin, ...):
        ...
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LifecycleMixin:
    """
    Mixin для управления жизненным циклом соединения OPC UA:
    polling, auto-reconnect и watchdog.

    Предполагает что подкласс имеет атрибуты:
        self.is_connected            — bool property
        self.client                  — asyncua.Client
        self._connected              — bool
        self._auto_reconnect         — bool
        self._reconnect_interval     — float
        self._max_reconnect_attempts — int
        self._reconnect_task         — Optional[asyncio.Task]
        self._watchdog_task          — Optional[asyncio.Task]
        self._watchdog_interval      — float
        self._poll_loops             — Dict[str, Dict[str, Any]]
        self._saved_subscriptions    — Dict
        self._saved_polls            — Dict
        self.subscribed_tags         — Dict
        self.latest_data             — Dict
        self._stats                  — Dict
        self.on_data_changed         — Optional[Callable]
        self.connect()               — метод
        self.subscribe_tag()         — метод
        self.read_multiple_nodes()   — метод
    """

    # ══════════════════════════════════════════════════════════════════════
    # Poll Loops — именованные циклы опроса тегов
    # ══════════════════════════════════════════════════════════════════════

    async def start_polling(self, name: str, node_ids: List[str], interval: float = 1.0, sequential: bool = False) -> None:
        """
        Запустить именованный цикл опроса тегов.
        Args:
            name: Уникальное имя цикла ("fast", "slow", "diagnostics").
            node_ids: Список адресов узлов для опроса.
            interval: Интервал опроса в секундах (по умолчанию 1.0).
            sequential: True — читать узлы по одному в порядке списка (гарантирует порядок
                        доставки). False (по умолчанию) — параллельное чтение через asyncio.gather.
        Raises:
            ConnectionError: Не подключены к серверу.
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to OPC UA server")
        # Если цикл с таким именем уже существует — останавливаем старый
        if name in self._poll_loops:
            await self.stop_polling(name)
        loop_info: Dict[str, Any] = {
            "nodes":      node_ids,
            "interval":   interval,
            "sequential": sequential,
            "active":     True,
            "task":       None,
        }
        loop_info["task"] = asyncio.create_task(self._poll_loop(name))
        self._poll_loops[name] = loop_info
        logger.info(f"Poll '{name}' started: {len(node_ids)} nodes, interval={interval}s, sequential={sequential}")

    async def stop_polling(self, name: Optional[str] = None) -> None:
        """
        Остановить цикл(ы) опроса.
        Args:
            name: Имя цикла. None — остановить ВСЕ циклы.
        """
        if name is not None:
            await self._stop_single_poll(name)
        else:
            # Копируем список — _stop_single_poll() удаляет из dict во время итерации
            for loop_name in list(self._poll_loops.keys()):
                await self._stop_single_poll(loop_name)

    async def _stop_single_poll(self, name: str) -> None:
        """Остановить один именованный цикл (внутренний)."""
        if name not in self._poll_loops:
            return
        loop_info = self._poll_loops[name]
        loop_info["active"] = False
        task = loop_info["task"]
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        del self._poll_loops[name]
        logger.info(f"Poll '{name}' stopped")

    async def _poll_loop(self, name: str) -> None:
        """
        Внутренний цикл опроса.

        Каждую итерацию: читает все теги параллельно → вызывает on_data_changed
        для каждого успешного результата → ждёт interval секунд → повторяет.

        При ConnectionError: если auto-reconnect включён — запускает _start_reconnect_loop().
        """
        try:
            loop_info = self._poll_loops.get(name)
            if not loop_info:
                return

            while loop_info["active"]:
                try:
                    batch: dict = {}
                    if loop_info.get("sequential"):
                        # Читаем узлы строго по одному — порядок доставки гарантирован
                        for node_id in loop_info["nodes"]:
                            value = await self.read_node(node_id)
                            if value is not None:
                                if self.on_data_changed:
                                    self.on_data_changed(node_id, value)
                                batch[node_id] = value
                    else:
                        data = await self.read_multiple_nodes(loop_info["nodes"])
                        for node_id, value in data.items():
                            if value is not None:
                                if self.on_data_changed:
                                    self.on_data_changed(node_id, value)
                                batch[node_id] = value
                    if batch and self.on_poll_batch:
                        self.on_poll_batch(name, batch)

                except ConnectionError:
                    logger.error(f"Poll '{name}': connection lost")
                    loop_info["active"] = False
                    if self._auto_reconnect:
                        await self._start_reconnect_loop()
                    break
                except Exception as e:
                    # Непредвиденная ошибка — логируем, но НЕ останавливаем цикл.
                    logger.error(f"Poll '{name}' error: {e}")

                await asyncio.sleep(loop_info["interval"])

        except asyncio.CancelledError:
            logger.info(f"Poll '{name}' cancelled")

    def get_active_polls(self) -> Dict[str, Dict[str, Any]]:
        """
        Получить информацию о всех активных poll loop'ах.

        Returns:
            {name: {"nodes": [...], "interval": float}}
        """
        return {
            name: {"nodes": info["nodes"], "interval": info["interval"]}
            for name, info in self._poll_loops.items()
            if info["active"]
        }

    # ══════════════════════════════════════════════════════════════════════
    # Auto-Reconnect — автоматическое переподключение
    # ══════════════════════════════════════════════════════════════════════

    async def _start_reconnect_loop(self) -> None:
        """
        Запустить цикл переподключения (внутренний).

        Сохраняет текущие подписки и poll loop'ы для восстановления после успеха.
        Не дублирует — если reconnect уже запущен, повторный вызов игнорируется.
        """
        # Если reconnect уже запущен — не дублируем
        if self._reconnect_task and not self._reconnect_task.done():
            return

        # Сохраняем подписки для восстановления
        self._saved_subscriptions = {
            node_id: self.latest_data.get(f"{node_id}_name")
            for node_id in list(self.subscribed_tags.keys())
        }

        # Сохраняем параметры poll loop'ов
        self._saved_polls = {
            name: {"nodes": info["nodes"], "interval": info["interval"]}
            for name, info in self._poll_loops.items()
        }

        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """
        Внутренний цикл переподключения.

        Пытается подключиться с интервалом _reconnect_interval.
        При успехе восстанавливает подписки и poll loop'ы.
        """
        attempt = 0
        try:
            while True:
                attempt += 1
                if self._max_reconnect_attempts > 0 and attempt > self._max_reconnect_attempts:
                    logger.error(f"Reconnect: max attempts ({self._max_reconnect_attempts}) reached, giving up")
                    break

                logger.info(f"Reconnect attempt {attempt}...")

                try:
                    # Очищаем старое соединение
                    self.client = None
                    self.subscription = None
                    self.handler = None
                    self._connected = False
                    self.subscribed_tags.clear()

                    await self.connect()
                    self._stats["reconnects"] += 1
                    logger.info(f"Reconnect: connected after {attempt} attempt(s)")

                    # Восстанавливаем подписки
                    for node_id, tag_name in self._saved_subscriptions.items():
                        try:
                            await self.subscribe_tag(node_id, tag_name)
                            logger.info(f"Reconnect: restored subscription {node_id}")
                        except Exception as e:
                            logger.error(f"Reconnect: failed to restore subscription {node_id}: {e}")

                    # Восстанавливаем poll loop'ы
                    for name, params in self._saved_polls.items():
                        try:
                            await self.start_polling(name, params["nodes"], params["interval"])
                            logger.info(f"Reconnect: restored poll '{name}'")
                        except Exception as e:
                            logger.error(f"Reconnect: failed to restore poll '{name}': {e}")

                    self._saved_subscriptions.clear()
                    self._saved_polls.clear()
                    return  # Успех

                except Exception as e:
                    logger.warning(f"Reconnect attempt {attempt} failed: {e}")

                await asyncio.sleep(self._reconnect_interval)

        except asyncio.CancelledError:
            logger.info("Reconnect loop cancelled")

    async def trigger_reconnect(self) -> None:
        """
        Вручную запустить переподключение.

        Полезно когда внешний код обнаружил обрыв связи.
        Ничего не делает если auto_reconnect=False.
        """
        if not self._auto_reconnect:
            logger.warning("Auto-reconnect is disabled")
            return
        await self._start_reconnect_loop()

    async def stop_reconnect(self) -> None:
        """Остановить цикл переподключения."""
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        self._reconnect_task = None

    # ══════════════════════════════════════════════════════════════════════
    # Connection Watchdog — heartbeat-проверка живости соединения
    # ══════════════════════════════════════════════════════════════════════

    async def start_watchdog(self, interval: float = 5.0) -> None:
        """
        Запустить периодическую проверку живости соединения.

        Читает ServerStatus каждые N секунд. При сбое — запускает reconnect.

        Args:
            interval: Интервал проверки (секунды). Рекомендуется 3–10с.
        """
        await self.stop_watchdog()
        self._watchdog_interval = interval
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info(f"Watchdog started (interval={interval}s)")

    async def stop_watchdog(self) -> None:
        """Остановить watchdog."""
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
        self._watchdog_task = None

    async def _watchdog_loop(self) -> None:
        """
        Внутренний цикл watchdog.

        Читает ServerStatus.CurrentTime (i=2258) — самый лёгкий запрос,
        доступный на любом OPC UA сервере. Сбой = соединение потеряно.
        """
        from asyncua import ua
        try:
            while self.is_connected:
                try:
                    # Захватываем локальную ссылку — client может стать None (race condition)
                    client = self.client
                    if client is None:
                        break
                    node = client.get_node(ua.ObjectIds.Server_ServerStatus_CurrentTime)
                    await node.read_value()

                except Exception as e:
                    logger.error(f"Watchdog: connection lost ({e})")
                    self._connected = False
                    if self._auto_reconnect:
                        await self._start_reconnect_loop()
                    break

                await asyncio.sleep(self._watchdog_interval)

        except asyncio.CancelledError:
            logger.info("Watchdog cancelled")

    @property
    def is_watchdog_active(self) -> bool:
        """True если watchdog запущен и работает."""
        return self._watchdog_task is not None and not self._watchdog_task.done()
