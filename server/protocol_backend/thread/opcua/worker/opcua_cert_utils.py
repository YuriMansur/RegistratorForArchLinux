"""
opcua_cert_utils — утилиты генерации X.509 сертификатов для OPC UA
==================================================================

Одноразовые инструменты подготовки: генерация самоподписанного сертификата.
Не является частью runtime-протокола — вызывается один раз при настройке.

Использование:
    from unified_backend_package.backend.thread.opcua.opcua_cert_utils import (
        generate_self_signed_certificate
    )

    cert, key = generate_self_signed_certificate(
        output_dir="certs",
        common_name="SCADA Client",
        valid_days=3650
    )
    worker.set_certificate(cert, key)
    await worker.connect()
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def generate_self_signed_certificate(
    output_dir: str = "certs",
    common_name: str = "OPC UA Client",
    organization: str = "Development",
    country: str = "US",
    key_size: int = 2048,
    valid_days: int = 365,
    uri: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Сгенерировать самоподписанный X.509 сертификат и закрытый ключ.

    Для тестирования и разработки. В продакшне используйте сертификаты от CA.

    Args:
        output_dir  : папка для сохранения (создаётся автоматически)
        common_name : имя клиента (поле CN), отображается в логах сервера
        organization: организация (поле O)
        country     : код страны ISO 3166 (поле C), например "RU", "US"
        key_size    : размер RSA-ключа в битах (2048 — быстро, 4096 — безопаснее)
        valid_days  : срок действия в днях (365 = 1 год, 3650 = 10 лет)
        uri         : Application URI — None = авто "urn:opcua:client:{common_name}"

    Returns:
        Tuple[str, str]: (certificate_path, private_key_path) — абсолютные пути

    Raises:
        RuntimeError: Ошибка генерации (нет библиотеки cryptography или иная).
    """
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend
        from datetime import timedelta, timezone

        cert_dir = Path(output_dir)
        cert_dir.mkdir(parents=True, exist_ok=True)

        # --- RSA-ключ ---
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
            backend=default_backend(),
        )

        # --- Subject ---
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, country),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ])

        app_uri = uri or f"urn:opcua:client:{common_name.replace(' ', '_')}"
        now = datetime.now(timezone.utc)

        # --- Сборка сертификата ---
        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=valid_days))
        )

        # --- Расширения ---
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.UniformResourceIdentifier(app_uri)]),
            critical=False,
        )
        builder = builder.add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True,
        )
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=True,
                content_commitment=True, data_encipherment=True,
                key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([
                ExtendedKeyUsageOID.CLIENT_AUTH,
                ExtendedKeyUsageOID.SERVER_AUTH,
            ]),
            critical=False,
        )

        # --- Подпись ---
        certificate = builder.sign(
            private_key=private_key,
            algorithm=hashes.SHA256(),
            backend=default_backend(),
        )

        # --- Сохранение ---
        cert_file = cert_dir / "client_cert.der"
        cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.DER))

        key_file = cert_dir / "client_key.pem"
        key_file.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

        cert_path_str = str(cert_file.resolve())
        key_path_str = str(key_file.resolve())
        logger.info(
            f"Self-signed certificate generated:\n"
            f"  Certificate: {cert_path_str}\n"
            f"  Private key: {key_path_str}\n"
            f"  CN={common_name}, O={organization}, C={country}\n"
            f"  URI={app_uri}, Key={key_size}bit, Valid={valid_days}days"
        )
        return cert_path_str, key_path_str

    except ImportError:
        raise RuntimeError(
            "Library 'cryptography' is not installed. "
            "Install it: pip install cryptography"
        )
    except Exception as e:
        raise RuntimeError(f"Failed to generate certificate: {e}")
