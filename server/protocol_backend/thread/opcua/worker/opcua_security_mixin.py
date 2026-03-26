"""
SecurityMixin — управление безопасностью OPC UA клиента
=======================================================

Mixin-класс: объединяет аутентификацию и X.509 сертификаты.

Три уровня безопасности (можно комбинировать):
  1. Только сертификат — аутентификация + шифрование канала
  2. Сертификат + username/password — двойная аутентификация
  3. Без сертификата, только username/password — аутентификация без шифрования

Содержит:
  Credentials:
    - set_credentials()              — задать логин/пароль
    - clear_credentials()            — сбросить на анонимный доступ
    - is_authenticated               — проверить наличие credentials

  Endpoints:
    - get_server_endpoints()         — получить список endpoint'ов сервера

  Certificate (X.509):
    - set_certificate()                  — привязать сертификат
    - clear_certificate()                — убрать сертификат
    - has_certificate                    — проверить наличие
    - _apply_certificate_security()      — внутренний: применить перед connect()
    - get_server_certificate_info()      — получить инфо о сертификате сервера

Использование:
    class AsyncOpcUaWorker(SecurityMixin, ...):
        ...
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from asyncua import Client, ua

logger = logging.getLogger(__name__)


class SecurityMixin:
    """
    Mixin для управления безопасностью OPC UA клиента.

    Предполагает что подкласс имеет атрибуты:
        self.client              — asyncua.Client
        self.endpoint            — str
        self.timeout             — float
        self._username           — Optional[str]
        self._password           — Optional[str]
        self._certificate_path   — Optional[str]
        self._private_key_path   — Optional[str]
        self._security_policy    — Optional[str]
        self._security_mode      — Optional[str]
    """

    # ── Credentials — аутентификация по логину/паролю ─────────────────────

    def set_credentials(self, username: str, password: str) -> None:
        """
        Установить или изменить логин/пароль для аутентификации.

        Вызывать ПЕРЕД connect(). Если уже подключены — нужно
        disconnect() → set_credentials() → connect() для применения.

        Args:
            username: Имя пользователя на OPC UA сервере.
            password: Пароль.

        Пример:
            worker.set_credentials("operator", "secret123")
            await worker.connect()
        """
        self._username = username
        self._password = password
        logger.info(f"Credentials set for user '{username}'")

    def clear_credentials(self) -> None:
        """
        Убрать аутентификацию — переключиться на анонимный доступ.

        После вызова следующий connect() будет без логина/пароля.
        """
        self._username = None
        self._password = None
        logger.info("Credentials cleared, anonymous access")

    @property
    def is_authenticated(self) -> bool:
        """
        Проверить, заданы ли credentials для аутентификации.

        Returns:
            True если username и password заданы.
            Не означает что аутентификация прошла успешно —
            только что credentials будут отправлены при connect().
        """
        return self._username is not None and self._password is not None

    # ── Endpoints — обнаружение политик безопасности сервера ──────────────

    async def get_server_endpoints(self) -> List[Dict[str, Any]]:
        """
        Получить список доступных endpoint'ов сервера с их политиками безопасности.

        Полезно для диагностики: какие методы аутентификации поддерживает сервер.
        Не требует подключения — создаёт временный Client.

        Returns:
            Список endpoint'ов:
            [
                {
                    "url": "opc.tcp://192.168.1.10:4840",
                    "security_mode": "None",            # None, Sign, SignAndEncrypt
                    "security_policy": "None",           # None, Basic256Sha256, ...
                    "user_tokens": ["Anonymous", "Username"]  # доступные методы входа
                },
                ...
            ]

        Raises:
            RuntimeError: Сервер недоступен.
        """
        try:
            # Создаём временный клиент только для запроса endpoint'ов
            temp_client = Client(url=self.endpoint, timeout=self.timeout)
            endpoints = await temp_client.connect_and_get_server_endpoints()

            result = []
            for ep in endpoints:
                tokens = []
                # Извлекаем доступные методы аутентификации
                if ep.UserIdentityTokens:
                    for token in ep.UserIdentityTokens:
                        token_type = str(token.TokenType)
                        # Преобразуем enum в читаемое имя
                        if "Anonymous" in token_type:
                            tokens.append("Anonymous")
                        elif "UserName" in token_type:
                            tokens.append("Username")
                        elif "Certificate" in token_type:
                            tokens.append("Certificate")
                        else:
                            tokens.append(token_type)

                result.append({
                    "url": ep.EndpointUrl,
                    "security_mode": str(ep.SecurityMode).split(".")[-1],
                    "security_policy": ep.SecurityPolicyUri.split("#")[-1] if ep.SecurityPolicyUri else "None",
                    "user_tokens": tokens,
                })
            return result

        except Exception as e:
            raise RuntimeError(f"Failed to get server endpoints: {e}")

    # ── Certificate — X.509 сертификаты ───────────────────────────────────
    #
    # OPC UA поддерживает X.509 сертификаты для:
    #   - Аутентификации клиента (вместо или вместе с username/password)
    #   - Шифрования канала (TLS-подобный handshake)
    #
    # Схема работы:
    #   1. Клиент имеет пару: сертификат (.der/.pem) + закрытый ключ (.pem)
    #   2. Сервер имеет свой сертификат (получаем автоматически при подключении)
    #   3. При connect() клиент отправляет свой сертификат серверу
    #   4. Сервер проверяет сертификат (должен быть в trust-list сервера)
    #   5. После handshake — канал зашифрован, данные защищены

    def set_certificate(self, certificate_path: str, private_key_path: str,
                        security_policy: Optional[str] = "Basic256Sha256",
                        security_mode: Optional[str] = "SignAndEncrypt") -> None:
        """
        Установить клиентский сертификат для аутентификации и шифрования.

        Вызывать ПЕРЕД connect(). Если уже подключены — нужно
        disconnect() → set_certificate() → connect().

        Args:
            certificate_path: Путь к файлу сертификата (.der или .pem).
            private_key_path: Путь к файлу закрытого ключа (.pem).
                ВАЖНО: этот файл НИКОГДА не передаётся серверу.
            security_policy: Алгоритм шифрования канала.
                "Basic256Sha256" — рекомендуемая (AES-256 + SHA-256)
                "Aes128Sha256RsaOaep" — новая альтернатива
                None — без шифрования (только аутентификация по сертификату)
            security_mode: Режим защиты сообщений.
                "SignAndEncrypt" — подпись + шифрование (рекомендуется)
                "Sign"           — только подпись
                None             — без защиты

        Raises:
            FileNotFoundError: Файл сертификата или ключа не найден.
        """
        cert_path = Path(certificate_path)
        key_path = Path(private_key_path)

        if not cert_path.exists():
            raise FileNotFoundError(f"Certificate file not found: {certificate_path}")
        if not key_path.exists():
            raise FileNotFoundError(f"Private key file not found: {private_key_path}")

        self._certificate_path = str(cert_path.resolve())
        self._private_key_path = str(key_path.resolve())
        self._security_policy = security_policy
        self._security_mode = security_mode
        logger.info(f"Certificate set: {cert_path.name}, policy={security_policy}, mode={security_mode}")

    def clear_certificate(self) -> None:
        """
        Убрать привязку сертификата — переключиться на незащищённый канал.

        После вызова следующий connect() будет без сертификата.
        Если также заданы username/password — они продолжат работать
        (но канал не будет зашифрован).
        """
        self._certificate_path = None
        self._private_key_path = None
        self._security_policy = None
        self._security_mode = None
        logger.info("Certificate cleared, unsecured channel")

    @property
    def has_certificate(self) -> bool:
        """
        Проверить, привязан ли сертификат.

        Returns:
            True если certificate_path и private_key_path заданы.
        """
        return self._certificate_path is not None and self._private_key_path is not None

    async def _apply_certificate_security(self) -> None:
        """
        Внутренний метод: применить настройки сертификата к Client перед connect().

        Вызывается из connect() если сертификат задан.
        Raises:
            RuntimeError: Ошибка загрузки сертификата или ключа.
        """
        try:
            policy_map = {
                "Basic256Sha256":     "http://opcfoundation.org/UA/SecurityPolicy#Basic256Sha256",
                "Basic256":           "http://opcfoundation.org/UA/SecurityPolicy#Basic256",
                "Basic128Rsa15":      "http://opcfoundation.org/UA/SecurityPolicy#Basic128Rsa15",
                "Aes128Sha256RsaOaep":"http://opcfoundation.org/UA/SecurityPolicy#Aes128_Sha256_RsaOaep",
                "Aes256Sha256RsaPss": "http://opcfoundation.org/UA/SecurityPolicy#Aes256_Sha256_RsaPss",
                None: None,
            }
            mode_map = {
                "Sign":          ua.MessageSecurityMode.Sign,
                "SignAndEncrypt": ua.MessageSecurityMode.SignAndEncrypt,
                None:            ua.MessageSecurityMode.SignAndEncrypt,
            }

            policy_uri = policy_map.get(self._security_policy, policy_map[None])
            mode = mode_map.get(self._security_mode, mode_map[None])

            if policy_uri:
                await self.client.set_security(
                    policy=policy_uri,
                    certificate_path=self._certificate_path,
                    private_key_path=self._private_key_path,
                    mode=mode,
                )
                logger.info(f"Security applied: policy={self._security_policy}, mode={self._security_mode}")
            else:
                await self.client.load_client_certificate(self._certificate_path)
                await self.client.load_private_key(self._private_key_path)
                logger.info("Certificate loaded without channel encryption")

        except Exception as e:
            raise RuntimeError(
                f"Failed to apply certificate security: {e}. "
                f"Check certificate format (.der/.pem) and key file (.pem)"
            )

    async def get_server_certificate_info(self) -> Dict[str, Any]:
        """
        Получить информацию о сертификате OPC UA сервера.

        Returns:
            {
                "server_certificate_exists": True/False,
                "endpoints_with_security": [
                    {"url": ..., "security_policy": ..., "security_mode": ..., "accepts_certificates": ...}
                ]
            }

        Raises:
            RuntimeError: Не удалось получить информацию.
        """
        try:
            endpoints = await self.get_server_endpoints()

            secure_eps = []
            for ep in endpoints:
                has_cert_token = "Certificate" in ep.get("user_tokens", [])
                secure_eps.append({
                    "url": ep["url"],
                    "security_policy": ep["security_policy"],
                    "security_mode": ep["security_mode"],
                    "accepts_certificates": has_cert_token,
                })

            has_server_cert = False
            if self.client and hasattr(self.client, 'server_certificate'):
                has_server_cert = self.client.server_certificate is not None

            return {
                "server_certificate_exists": has_server_cert,
                "endpoints_with_security": secure_eps,
            }

        except Exception as e:
            raise RuntimeError(f"Failed to get server certificate info: {e}")
