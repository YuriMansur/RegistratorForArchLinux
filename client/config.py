# json — для чтения и записи конфига в формате JSON.
import json
# os — доступ к %APPDATA% для пути конфига установленного приложения.
import os
# sys — определить, запущено ли приложение из собранного .exe (PyInstaller).
import sys
# Path — для удобной работы с путями к файлам.
from pathlib import Path


def _config_dir() -> Path:
    """Папка с config.json.
    - Установленное приложение (PyInstaller, sys.frozen): %APPDATA%\\Registrator —
      доступно на запись при установке в Program Files / %LOCALAPPDATA%, настройки
      переживают переустановку и удаление приложения.
    - Запуск из исходников: client/config/.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "Registrator"
    return Path(__file__).parent / "config"


# Путь к файлу конфига.
CONFIG_FILE = _config_dir() / "config.json"

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
    Остальные ключи (например trends_visible) сохраняются — мерджим с существующими.
    """
    # Гарантируем существование папки config/ перед записью (первый сейв после клонирования).
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Читаем существующее, чтобы не стереть произвольные ключи (UI-prefs и т.п.).
    existing = load_config() if CONFIG_FILE.exists() else {}
    existing["host"] = host
    existing["port"] = port
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        # ensure_ascii=False — чтобы русские подписи (если попадут в конфиг) остались читаемыми.
        json.dump(existing, f, indent=2, ensure_ascii=False)


def get_key(key: str, default=None):
    """Прочитать произвольный ключ из config.json. Возвращает default если нет ключа или файла."""
    return load_config().get(key, default)


def save_key(key: str, value) -> None:
    """Сохранить произвольный ключ в config.json, сохраняя остальные.
    Используется для UI-prefs (видимость кривых трендов и т.п.)."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = load_config() if CONFIG_FILE.exists() else {}
    existing[key] = value
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


def get_base_url() -> str:
    """Вернуть базовый URL сервера для HTTP-запросов.

    Читает конфиг при каждом вызове — изменения в SettingsDialog применяются сразу.
    Возвращает строку вида "http://192.168.10.222:8000".
    """
    # Загружаем актуальный конфиг (может быть изменён пользователем).
    cfg = load_config()
    # Собираем URL из протокола, хоста и порта.
    return f"http://{cfg['host']}:{cfg['port']}"
