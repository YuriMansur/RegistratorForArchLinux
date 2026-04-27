# datetime — для передачи временных диапазонов в параметрах запросов.
from datetime import datetime
# requests — синхронная HTTP-библиотека для запросов к FastAPI серверу.
import requests
# get_base_url — читает конфиг и возвращает "http://host:port".
from config import get_base_url

# Таймаут по умолчанию для большинства запросов в секундах.
# При превышении requests.exceptions.Timeout → обрабатывается вызывающим кодом.
TIMEOUT = 5


def _url(path: str) -> str:
    """Собрать полный URL из базового адреса и пути эндпоинта."""
    return f"{get_base_url()}{path}"


def _get(path: str, **kwargs):
    """Выполнить GET-запрос. Вызывает raise_for_status() при HTTP 4xx/5xx."""
    with requests.Session() as s:
        r = s.get(_url(path), **kwargs)
        # raise_for_status() выбросит HTTPError если код ответа не 2xx.
        r.raise_for_status()
        return r


def _post(path: str, **kwargs):
    """Выполнить POST-запрос. Вызывает raise_for_status() при HTTP 4xx/5xx."""
    with requests.Session() as s:
        r = s.post(_url(path), **kwargs)
        r.raise_for_status()
        return r


def _put(path: str, **kwargs):
    """Выполнить PUT-запрос. Вызывает raise_for_status() при HTTP 4xx/5xx."""
    with requests.Session() as s:
        r = s.put(_url(path), **kwargs)
        r.raise_for_status()
        return r


def _delete(path: str, **kwargs):
    """Выполнить DELETE-запрос. Вызывает raise_for_status() при HTTP 4xx/5xx."""
    with requests.Session() as s:
        r = s.delete(_url(path), **kwargs)
        r.raise_for_status()
        return r


def health_check() -> bool:
    """Проверить доступность сервера. Возвращает True если сервер отвечает."""
    try:
        # GET /health возвращает {"status": "ok"} — нас интересует только факт ответа.
        _get("/health", timeout=TIMEOUT)
        return True
    except requests.RequestException:
        # Любая ошибка сети или таймаут — сервер недоступен.
        return False


def get_tags() -> list[dict]:
    """Получить последние значения всех тегов из БД (GET /tags/latest)."""
    return _get("/tags/latest", timeout=TIMEOUT).json()


def get_live_tags() -> list[dict]:
    """Получить последние значения тегов из памяти сервера (GET /tags/live).

    Быстрее get_tags() — не делает запрос к SQLite, читает из RAM.
    """
    return _get("/tags/live", timeout=TIMEOUT).json()


def get_history(limit: int = 10000) -> list[dict]:
    """Получить последние N записей истории из БД (GET /history)."""
    return _get("/history", params={"limit": limit}, timeout=TIMEOUT).json()


def get_checkouts() -> list[dict]:
    """Получить список всех испытаний, от новых к старым (GET /checkouts)."""
    return _get("/checkouts", timeout=TIMEOUT).json()


def export_checkout(checkout_id: int) -> dict:
    """Запустить генерацию XLSX/DOCX/PNG для испытания на сервере (POST /checkouts/{id}/export).

    Возвращает немедленно — генерация идёт в фоне. Клиент ждёт появления папки.
    """
    return _post(f"/checkouts/{checkout_id}/export", timeout=TIMEOUT).json()


def get_checkout_history(checkout_id: int) -> list[dict]:
    """Получить все записи истории для конкретного испытания (GET /checkouts/{id}/history)."""
    return _get(f"/checkouts/{checkout_id}/history", timeout=TIMEOUT).json()


def get_exports() -> list[dict]:
    """Получить список папок с экспортами на сервере (GET /exports).

    Используется для отображения в дереве экспортов и для ожидания завершения генерации.
    """
    return _get("/exports", timeout=TIMEOUT).json()


def download_export_folder(folder_name: str) -> bytes:
    """Скачать папку с экспортом как ZIP-архив (GET /exports/{folder}/download).

    Таймаут 60с — архив может быть большим (графики PNG + XLSX + DOCX).
    """
    return _get(f"/exports/{folder_name}/download", timeout=60).content


def get_history_range_count(from_dt: datetime, to_dt: datetime) -> int:
    """Получить количество записей истории за период (GET /history/range/count).

    Используется перед экспортом чтобы проверить есть ли данные.
    Быстрый запрос — только COUNT(*), без передачи данных.
    """
    # Передаём datetime в формате ISO 8601 как строковые параметры запроса.
    params = {"from_dt": from_dt.isoformat(), "to_dt": to_dt.isoformat()}
    return _get("/history/range/count", params=params, timeout=10).json()["count"]


def get_history_range(
    from_dt: datetime,
    to_dt: datetime,
    tags: list[str] | None = None,      # фильтр по именам тегов; None = все теги
    max_points: int | None = None,       # прореживание; None = все точки
) -> list[dict]:
    """Получить историю за диапазон дат (GET /history/range).

    Таймаут 60с — за большой период может быть много данных.
    """
    # Базовые параметры — временной диапазон.
    params: dict = {"from_dt": from_dt.isoformat(), "to_dt": to_dt.isoformat()}
    # Добавляем фильтр по тегам если задан.
    if tags:
        params["tags"] = tags
    # Добавляем лимит точек если задан (для прореживания на сервере).
    if max_points:
        params["max_points"] = max_points
    return _get("/history/range", params=params, timeout=60).json()


def stream_history_range(
    from_dt: datetime,
    to_dt: datetime,
    tags: list[str] | None = None,
):
    """Получить историю за диапазон через стриминг NDJSON (GET /history/stream).

    Генератор — возвращает записи по мере получения, не ждёт весь ответ.
    Используется в TrendsWidget для отображения данных по мере загрузки.
    timeout=None — нет таймаута, стрим может идти долго для больших периодов.
    """
    import json as _json
    params: dict = {"from_dt": from_dt.isoformat(), "to_dt": to_dt.isoformat()}
    # Добавляем фильтр по тегам если задан.
    if tags:
        params["tags"] = tags
    # stream=True — requests не буферизует весь ответ, отдаёт по частям.
    with requests.Session() as s:
        with s.get(_url("/history/stream"), params=params, stream=True, timeout=None) as r:
            r.raise_for_status()
            # Читаем ответ построчно — каждая строка это JSON-объект (NDJSON).
            for line in r.iter_lines():
                if line:
                    # Декодируем каждую строку в словарь и передаём вызывающему коду.
                    yield _json.loads(line)


def export_date_range(from_dt: datetime, to_dt: datetime) -> dict:
    """Запустить генерацию XLSX/DOCX/PNG за произвольный период (POST /history/export-range).

    Возвращает немедленно — генерация идёт в фоне на сервере.
    """
    params = {"from_dt": from_dt.isoformat(), "to_dt": to_dt.isoformat()}
    return _post("/history/export-range", params=params, timeout=TIMEOUT).json()


def get_usb_devices() -> list[dict]:
    """Получить список подключённых USB-накопителей (GET /usb/devices)."""
    return _get("/usb/devices", timeout=TIMEOUT).json()


def get_usb_export_status() -> str:
    """Получить статус экспорта на USB (GET /usb/export-status).

    Возможные значения: "idle", "waiting", "writing", "done", "error".
    """
    return _get("/usb/export-status", timeout=TIMEOUT).json().get("status", "idle")


def download_db() -> bytes:
    """Скачать консистентный снимок SQLite БД (GET /db/download).

    Таймаут 120с — БД может весить несколько сотен МБ.
    Сервер делает sqlite3.backup() перед отдачей — включает WAL.
    """
    return _get("/db/download", timeout=120).content


def get_disk_status() -> dict | None:
    """Получить статус дискового пространства и размер БД (GET /disk/status).

    Возвращает None если сервер недоступен — вызывающий код должен это обрабатывать.
    """
    try:
        return _get("/disk/status", timeout=TIMEOUT).json()
    except requests.RequestException:
        # Сервер недоступен — возвращаем None вместо исключения.
        return None
