"""
ExplorationMixin — исследование OPC UA сервера (browse + history + methods)
===========================================================================

Объединяет все read-only операции изучения сервера:

  1. Browse — обход дерева узлов без знания node_id заранее.
     Позволяет найти доступные переменные, объекты, методы.

  2. Read Node Info — расширенное чтение узла (значение + timestamp + quality + тип).
     В отличие от read_node() возвращает полные метаданные.

  3. Method Discovery & Call — обнаружение и вызов методов на сервере (RPC).
     OPC UA Methods — аналог remote procedure call: StartPump(), ResetAlarm().

  4. History Read — чтение архивных данных из historian'а.
     Для серверов с включённым Historizing (Kepware, Prosys, UA).

Почему они объединены:
  - Все операции read-only, не изменяют состояние сервера
  - Одна общая цель: "понять что есть на сервере и прочитать данные"
  - Одинаковые зависимости: is_connected + _get_cached_node

Оптимизация: _browse_recursive и discover_methods читают метаданные
узлов ПАРАЛЛЕЛЬНО через asyncio.gather().

Содержит:
  Browse:
    - browse_nodes()       — обзор дерева с заданной точки
    - _browse_recursive()  — рекурсивный обход (внутренний)

  Node Info:
    - read_node_info()     — значение + timestamp + quality + тип

  Methods:
    - call_method()        — вызов OPC UA Method (RPC)
    - discover_methods()   — обнаружить методы объекта

  History:
    - read_history()          — история одного тега за период
    - read_history_multiple() — пакетное параллельное чтение нескольких тегов

Использование:
    class AsyncOpcUaWorker(ExplorationMixin, ...):
        ...
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ExplorationMixin:
    """
    Mixin для исследования OPC UA сервера: browse, node info, methods, history.

    Предполагает что подкласс имеет атрибуты:
        self.is_connected       — bool property
        self.client             — asyncua.Client
        self.latest_data        — Dict[str, Any]
        self._get_cached_node() — метод
    """

    # ══════════════════════════════════════════════════════════════════════
    # Browse — обзор дерева сервера
    # ══════════════════════════════════════════════════════════════════════

    async def browse_nodes(self, start_node_id: Optional[str] = None, depth: int = 1) -> List[Dict[str, Any]]:
        """
        Обзор дочерних узлов на OPC UA сервере.

        Позволяет найти доступные переменные без знания node_id заранее.
        По умолчанию начинает с Objects (i=85) — корня пользовательских данных.

        Args:
            start_node_id: Узел-точка старта.
                None — Objects (корень). "ns=2;s=MyFolder" — конкретная папка.
            depth: Глубина рекурсии.
                1 = только дочерние, 2 = дочерние + их дочерние, и т.д.

        Returns:
            [
                {
                    "node_id":    "ns=2;s=Temperature",
                    "name":       "Temperature",
                    "node_class": "Variable",   # Variable, Object, Method
                    "children":   [...]          # если depth > 1
                },
                ...
            ]

        Raises:
            ConnectionError: Не подключены к серверу.
            RuntimeError: Ошибка при обзоре.
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to OPC UA server")
        try:
            start = (
                self.client.get_node(start_node_id)
                if start_node_id
                else self.client.get_objects_node()
            )
            return await self._browse_recursive(start, depth)
        except Exception as e:
            raise RuntimeError(f"Failed to browse nodes: {e}")

    async def _browse_recursive(self, node, depth: int) -> List[Dict[str, Any]]:
        """
        Рекурсивный обход дочерних узлов (внутренний).

        Оптимизация: читает node_class и display_name для всех дочерних
        узлов ПАРАЛЛЕЛЬНО через asyncio.gather().
        """
        from asyncua import ua

        children = await node.get_children()
        if not children:
            return []

        # Параллельное чтение метаданных всех дочерних узлов за один round-trip
        node_classes, display_names = await asyncio.gather(
            asyncio.gather(*[child.read_node_class() for child in children]),
            asyncio.gather(*[child.read_display_name() for child in children]),
        )

        result = []
        for child, node_class, name in zip(children, node_classes, display_names):
            info: Dict[str, Any] = {
                "node_id":    str(child.nodeid),
                "name":       name.Text,
                "node_class": node_class.name if hasattr(node_class, 'name') else str(node_class),
            }
            if depth > 1 and node_class == ua.NodeClass.Object:
                info["children"] = await self._browse_recursive(child, depth - 1)
            else:
                info["children"] = []
            result.append(info)

        return result

    # ══════════════════════════════════════════════════════════════════════
    # Read Node Info — расширенное чтение узла с метаданными
    # ══════════════════════════════════════════════════════════════════════

    async def read_node_info(self, node_id: str) -> Dict[str, Any]:
        """
        Расширенное чтение узла — значение + timestamp + quality + тип.

        В отличие от read_node() (только значение), возвращает полную структуру DataValue.

        Args:
            node_id: Адрес узла ("ns=2;s=Temperature")

        Returns:
            {
                "node_id":          "ns=2;s=Temperature",
                "value":            24.1,
                "source_timestamp": datetime(...),  # когда PLC зафиксировал
                "server_timestamp": datetime(...),  # когда сервер отправил
                "status_code":      "Good",          # Good / Bad...
                "data_type":        "Float"
            }

        Raises:
            ConnectionError: Не подключены.
            RuntimeError: Узел не найден.
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to OPC UA server")
        try:
            node = self.client.get_node(node_id)
            dv = await node.read_data_value()

            result: Dict[str, Any] = {
                "node_id":          node_id,
                "value":            dv.Value.Value if dv.Value else None,
                "source_timestamp": dv.SourceTimestamp,
                "server_timestamp": dv.ServerTimestamp,
                "status_code":      str(dv.StatusCode_.name)
                    if hasattr(dv.StatusCode_, 'name') else str(dv.StatusCode_),
            }

            try:
                dt = await node.read_data_type_as_variant_type()
                result["data_type"] = dt.name if hasattr(dt, 'name') else str(dt)
            except Exception as e:
                logger.debug(f"Could not read data type for {node_id}: {e}")
                result["data_type"] = "Unknown"

            if result["value"] is not None:
                self.latest_data[node_id] = result["value"]

            return result
        except Exception as e:
            raise RuntimeError(f"Failed to read node info {node_id}: {e}")

    # ══════════════════════════════════════════════════════════════════════
    # Methods — обнаружение и вызов OPC UA Methods (RPC)
    #
    # OPC UA Method — функция на сервере, вызываемая удалённо.
    # Метод принадлежит Object-узлу:
    #   Objects → MyDevice → StartPump()
    #   parent_node_id = "ns=2;s=MyDevice"
    #   method_node_id = "ns=2;s=StartPump"
    # ══════════════════════════════════════════════════════════════════════

    async def call_method(
        self,
        parent_node_id: str,
        method_node_id: str,
        args: Optional[List[Any]] = None,
    ) -> Any:
        """
        Вызвать метод на OPC UA сервере (Remote Procedure Call).

        Args:
            parent_node_id: Адрес Object-узла владельца метода ("ns=2;s=MyDevice").
            method_node_id: Адрес самого метода ("ns=2;s=StartPump").
            args: Аргументы метода или None.
                Типы должны совпадать с сигнатурой на сервере.

        Returns:
            Результат метода или None если метод void.

        Raises:
            ConnectionError: Не подключены.
            RuntimeError: Метод не найден, неверные аргументы, ошибка выполнения.

        Пример:
            await worker.call_method("ns=2;s=Pump1", "ns=2;s=Start")

            from asyncua import ua
            result = await worker.call_method(
                "ns=2;s=Oven1", "ns=2;s=SetTemperature",
                args=[ua.Variant(250.0, ua.VariantType.Float)]
            )
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to OPC UA server")
        try:
            parent = self._get_cached_node(parent_node_id)
            method = self._get_cached_node(method_node_id)
            result = await parent.call_method(method, *args) if args else await parent.call_method(method)
            logger.info(f"Method called: {method_node_id} on {parent_node_id}, result={result}")
            return result
        except Exception as e:
            raise RuntimeError(f"Failed to call method {method_node_id} on {parent_node_id}: {e}")

    async def discover_methods(self, object_node_id: str) -> List[Dict[str, Any]]:
        """
        Обнаружить доступные методы на объекте.

        Args:
            object_node_id: Адрес Object-узла ("ns=2;s=MyDevice").

        Returns:
            [{"node_id": "ns=2;s=Start", "name": "Start"}, ...]
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to OPC UA server")
        try:
            from asyncua import ua

            parent = self._get_cached_node(object_node_id)
            children = await parent.get_children()

            # Читаем node_class для всех детей параллельно
            node_classes = await asyncio.gather(
                *[child.read_node_class() for child in children]
            )

            method_nodes = [
                child for child, nc in zip(children, node_classes)
                if nc == ua.NodeClass.Method
            ]
            if not method_nodes:
                return []

            display_names = await asyncio.gather(
                *[node.read_display_name() for node in method_nodes]
            )
            return [
                {"node_id": str(node.nodeid), "name": name.Text}
                for node, name in zip(method_nodes, display_names)
            ]
        except Exception as e:
            raise RuntimeError(f"Failed to discover methods on {object_node_id}: {e}")

    # ══════════════════════════════════════════════════════════════════════
    # History Read — чтение исторических данных
    #
    # Требует Historizing=True на узле и наличия Historian на сервере.
    # Поддерживают: Kepware, Prosys, Unified Automation и другие.
    # ══════════════════════════════════════════════════════════════════════

    async def read_history(
        self,
        node_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        num_values: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Чтение исторических данных переменной за период.

        Args:
            node_id: Адрес узла ("ns=2;s=Temperature").
                Узел должен быть Historizing=True на сервере.
            start_time: Начало периода UTC. None = час назад.
            end_time:   Конец периода UTC.  None = сейчас.
            num_values: Макс. число точек (0 = все, сервер определяет лимит).

        Returns:
            [
                {"timestamp": datetime(...), "value": 24.1, "status": "Good"},
                ...
            ]

        Raises:
            ConnectionError: Не подключены.
            RuntimeError: Узел не поддерживает историю или ошибка сервера.

        Пример:
            # Последний час
            data = await worker.read_history("ns=2;s=Temperature")

            # Конкретный период
            data = await worker.read_history(
                "ns=2;s=Temperature",
                start_time=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
                end_time=  datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
            )
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to OPC UA server")
        try:
            node = self._get_cached_node(node_id)

            if end_time is None:
                end_time = datetime.now(timezone.utc)
            if start_time is None:
                start_time = end_time - timedelta(hours=1)

            history = await node.read_raw_history(
                starttime=start_time,
                endtime=end_time,
                numvalues=num_values,
            )

            result = [
                {
                    "timestamp": dv.SourceTimestamp,
                    "value":     dv.Value.Value if dv.Value else None,
                    "status":    str(dv.StatusCode_.name)
                        if hasattr(dv.StatusCode_, 'name') else str(dv.StatusCode_),
                }
                for dv in history
            ]

            logger.info(f"History read: {node_id}, {len(result)} values ({start_time} to {end_time})")
            return result
        except Exception as e:
            raise RuntimeError(f"Failed to read history for {node_id}: {e}")

    async def read_history_multiple(
        self,
        node_ids: List[str],
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        num_values: int = 0,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Пакетное чтение истории нескольких переменных ПАРАЛЛЕЛЬНО.

        Args:
            node_ids: Список адресов узлов.
            start_time: Начало периода (None = час назад).
            end_time:   Конец периода (None = сейчас).
            num_values: Макс. число значений на узел (0 = все).

        Returns:
            {node_id: [{"timestamp": ..., "value": ..., "status": ...}, ...]}
            При ошибке узла — пустой список [].
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to OPC UA server")

        raw_results = await asyncio.gather(
            *[self.read_history(nid, start_time, end_time, num_values) for nid in node_ids],
            return_exceptions=True,
        )

        results = {}
        for node_id, result in zip(node_ids, raw_results):
            if isinstance(result, Exception):
                results[node_id] = []
                logger.error(f"History read error for {node_id}: {result}")
            else:
                results[node_id] = result
        return results
