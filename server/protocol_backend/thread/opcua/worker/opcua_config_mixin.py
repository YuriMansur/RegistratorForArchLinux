"""
ConfigMixin — экспорт/импорт конфигурации AsyncOpcUaWorker
===========================================================

Mixin-класс: сохранение и восстановление конфигурации в JSON.

Сохраняет:
  - Параметры подключения (endpoint, namespace, timeout)
  - Security (username — без пароля!, certificate paths)
  - Подписанные теги и их имена
  - Параметры poll loop'ов
  - Настройки auto-reconnect

ВАЖНО: Пароль и закрытый ключ НЕ сохраняются в файл (безопасность).
Они передаются отдельно при восстановлении через from_config().

Содержит:
  - export_config()       — сохранить конфигурацию в JSON
  - from_config()         — classmethod: создать Worker из JSON
  - restore_from_config() — восстановить подписки/polling из JSON

Использование:
    class AsyncOpcUaWorker(ConfigMixin, ...):
        ...
"""

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class ConfigMixin:
    """
    Mixin для сохранения/загрузки конфигурации в JSON-файл.

    Предполагает что подкласс имеет атрибуты:
        self.endpoint               — str
        self.namespace              — int
        self.timeout                — float
        self._username              — Optional[str]
        self._certificate_path      — Optional[str]
        self._security_policy       — Optional[str]
        self._security_mode         — Optional[str]
        self._auto_reconnect        — bool
        self._reconnect_interval    — float
        self._max_reconnect_attempts — int
        self.subscribed_tags        — Dict
        self.latest_data            — Dict
        self._poll_loops            — Dict
        self.subscribe_tag()        — метод
        self.start_polling()        — метод
    """

    def export_config(self, file_path: str) -> None:
        """
        Экспортировать текущую конфигурацию в JSON-файл.

        ВАЖНО: Пароль и закрытый ключ НЕ сохраняются в файл (безопасность).

        Args:
            file_path: Путь к файлу для сохранения.
                Пример: "config/plc1_config.json"

        Пример:
            worker.export_config("config/opc_config.json")
        """
        config = {
            # Параметры подключения
            "endpoint":  self.endpoint,
            "namespace": self.namespace,
            "timeout":   self.timeout,

            # Security (без пароля и закрытого ключа!)
            "username":         self._username,
            # password        — НЕ сохраняем (безопасность)
            "certificate_path": self._certificate_path,
            # private_key_path — НЕ сохраняем (безопасность)
            "security_policy":  self._security_policy,
            "security_mode":    self._security_mode,

            # Подписанные теги
            "subscribed_tags": list(self.subscribed_tags.keys()),
            # Маппинг имён тегов
            "tag_names": {
                node_id: self.latest_data.get(f"{node_id}_name")
                for node_id in self.subscribed_tags.keys()
                if self.latest_data.get(f"{node_id}_name")
            },

            # Poll loop'ы
            "poll_loops": {
                name: {"nodes": info["nodes"], "interval": info["interval"]}
                for name, info in self._poll_loops.items()
            },

            # Auto-reconnect
            "auto_reconnect":          self._auto_reconnect,
            "reconnect_interval":      self._reconnect_interval,
            "max_reconnect_attempts":  self._max_reconnect_attempts,
        }

        # Создаём папку если не существует
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Записываем JSON с отступами для читаемости
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"Config exported to {file_path}")

    @classmethod
    def from_config(
        cls,
        file_path: str,
        password: Optional[str] = None,
        private_key_path: Optional[str] = None,
        on_data_changed: Optional[Callable] = None,
    ) -> "ConfigMixin":
        """
        Создать AsyncOpcUaWorker из JSON-файла конфигурации.

        Args:
            file_path: Путь к JSON-файлу (созданному через export_config()).
            password: Пароль для аутентификации (не хранится в файле).
            private_key_path: Путь к закрытому ключу (не хранится в файле).
            on_data_changed: Callback для изменений данных.

        Returns:
            Настроенный экземпляр AsyncOpcUaWorker (не подключённый).
            Нужно вызвать await worker.connect() после создания.

        Пример:
            worker = AsyncOpcUaWorker.from_config(
                "config/opc_config.json",
                password="secret123",
                private_key_path="certs/key.pem"
            )
            await worker.connect()

            # Восстановить подписки из конфига
            await worker.restore_from_config("config/opc_config.json")
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        worker = cls(
            endpoint                = config["endpoint"],
            namespace               = config.get("namespace", 2),
            timeout                 = config.get("timeout", 10.0),
            on_data_changed         = on_data_changed,
            username                = config.get("username"),
            password                = password,
            certificate_path        = config.get("certificate_path"),
            private_key_path        = private_key_path,
            security_policy         = config.get("security_policy"),
            security_mode           = config.get("security_mode"),
            auto_reconnect          = config.get("auto_reconnect", False),
            reconnect_interval      = config.get("reconnect_interval", 5.0),
            max_reconnect_attempts  = config.get("max_reconnect_attempts", 0),
        )

        logger.info(f"Worker created from config: {file_path}")
        return worker

    async def restore_from_config(self, file_path: str) -> Dict[str, Any]:
        """
        Восстановить подписки и poll loop'ы из конфиг-файла.

        Вызывать ПОСЛЕ connect(). Читает конфиг и пересоздаёт:
          - Подписки на теги (subscribe_tag)
          - Poll loop'ы (start_polling)

        Args:
            file_path: Путь к JSON-файлу конфигурации.

        Returns:
            Результат восстановления:
            {
                "subscriptions_restored": 10,
                "subscriptions_failed":   0,
                "polls_restored":         2,
                "polls_failed":           0,
            }
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        result = {
            "subscriptions_restored": 0,
            "subscriptions_failed":   0,
            "polls_restored":         0,
            "polls_failed":           0,
        }

        # Восстанавливаем подписки
        tag_names = config.get("tag_names", {})
        for node_id in config.get("subscribed_tags", []):
            try:
                tag_name = tag_names.get(node_id)
                await self.subscribe_tag(node_id, tag_name)
                result["subscriptions_restored"] += 1
            except Exception as e:
                result["subscriptions_failed"] += 1
                logger.error(f"Failed to restore subscription {node_id}: {e}")

        # Восстанавливаем poll loop'ы
        for name, params in config.get("poll_loops", {}).items():
            try:
                await self.start_polling(name, params["nodes"], params["interval"])
                result["polls_restored"] += 1
            except Exception as e:
                result["polls_failed"] += 1
                logger.error(f"Failed to restore poll '{name}': {e}")

        logger.info(f"Config restored from {file_path}: {result}")
        return result
