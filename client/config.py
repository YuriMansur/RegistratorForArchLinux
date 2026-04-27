# json — для чтения и записи конфига в формате JSON.
import json
# Path — для удобной работы с путями к файлам.
from pathlib import Path

# Путь к файлу конфига рядом с config.py (в папке client/).
CONFIG_FILE = Path(__file__).parent / "config.json"

# IP-адрес сервера по умолчанию — используется если config.json не существует.
DEFAULT_HOST = "192.168.100.100"
# Порт сервера по умолчанию — совпадает с портом uvicorn на сервере.
DEFAULT_PORT = 8000


def load_config() -> dict:
    """Загрузить конфигурацию из файла config.json.

    Если файл не существует (первый запуск) — возвращает значения по умолчанию.
    Вызывается при каждом HTTP-запросе через get_base_url(), чтобы изменения
    настроек применялись без перезапуска клиента.
    """
    if CONFIG_FILE.exists():
        # Читаем JSON-файл и возвращаем словарь {host, port}.
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    # Файл не найден — используем значения по умолчанию.
    return {"host": DEFAULT_HOST, "port": DEFAULT_PORT}


def save_config(host: str, port: int) -> None:
    """Сохранить настройки подключения в config.json.

    Вызывается из SettingsDialog при нажатии OK.
    indent=2 — форматированный JSON для читаемости при ручном редактировании.
    """
    with open(CONFIG_FILE, "w") as f:
        # Записываем host и port в файл рядом с клиентом.
        json.dump({"host": host, "port": port}, f, indent=2)


def get_base_url() -> str:
    """Вернуть базовый URL сервера для HTTP-запросов.

    Читает конфиг при каждом вызове — изменения в SettingsDialog применяются сразу.
    Возвращает строку вида "http://192.168.10.222:8000".
    """
    # Загружаем актуальный конфиг (может быть изменён пользователем).
    cfg = load_config()
    # Собираем URL из протокола, хоста и порта.
    return f"http://{cfg['host']}:{cfg['port']}"
