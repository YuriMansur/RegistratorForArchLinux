"""
ExplorationMixin — исследование OPC UA сервера (browse + methods)
=================================================================

Объединяет read-only операции изучения сервера:

  1. Browse — обход дерева узлов без знания node_id заранее.
     Позволяет найти доступные переменные, объекты, методы.

  2. Read Node Info — расширенное чтение узла (значение + timestamp + quality + тип).
     В отличие от read_node() возвращает полные метаданные.

  3. Method Discovery & Call — обнаружение и вызов методов на сервере (RPC).
     OPC UA Methods — аналог remote procedure call: StartPump(), ResetAlarm().

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

Использование:
    class AsyncOpcUaWorker(ExplorationMixin, ...):
        ...
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ExplorationMixin:
    """
    Mixin для исследования OPC UA сервера: browse, node info.

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


