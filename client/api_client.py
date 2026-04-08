from datetime import datetime
import requests
from config import get_base_url

TIMEOUT = 5  # seconds


def _url(path: str) -> str:
    return f"{get_base_url()}{path}"


def _get(path: str, **kwargs):
    with requests.Session() as s:
        r = s.get(_url(path), **kwargs)
        r.raise_for_status()
        return r


def _post(path: str, **kwargs):
    with requests.Session() as s:
        r = s.post(_url(path), **kwargs)
        r.raise_for_status()
        return r


def _put(path: str, **kwargs):
    with requests.Session() as s:
        r = s.put(_url(path), **kwargs)
        r.raise_for_status()
        return r


def _delete(path: str, **kwargs):
    with requests.Session() as s:
        r = s.delete(_url(path), **kwargs)
        r.raise_for_status()
        return r


def health_check() -> bool:
    try:
        _get("/health", timeout=TIMEOUT)
        return True
    except requests.RequestException:
        return False


def get_tags() -> list[dict]:
    return _get("/tags/latest", timeout=TIMEOUT).json()


def get_history(limit: int = 10000) -> list[dict]:
    return _get("/history", params={"limit": limit}, timeout=TIMEOUT).json()


def get_checkouts() -> list[dict]:
    return _get("/checkouts", timeout=TIMEOUT).json()


def export_checkout(checkout_id: int) -> dict:
    return _post(f"/checkouts/{checkout_id}/export", timeout=TIMEOUT).json()


def get_checkout_history(checkout_id: int) -> list[dict]:
    return _get(f"/checkouts/{checkout_id}/history", timeout=TIMEOUT).json()


def get_exports() -> list[dict]:
    return _get("/exports", timeout=TIMEOUT).json()


def download_export_folder(folder_name: str) -> bytes:
    return _get(f"/exports/{folder_name}/download", timeout=60).content


def get_history_range_count(from_dt: datetime, to_dt: datetime) -> int:
    params = {"from_dt": from_dt.isoformat(), "to_dt": to_dt.isoformat()}
    return _get("/history/range/count", params=params, timeout=10).json()["count"]


def get_history_range(
    from_dt: datetime,
    to_dt: datetime,
    tags: list[str] | None = None,
    max_points: int | None = None,
) -> list[dict]:
    params: dict = {"from_dt": from_dt.isoformat(), "to_dt": to_dt.isoformat()}
    if tags:
        params["tags"] = tags
    if max_points:
        params["max_points"] = max_points
    return _get("/history/range", params=params, timeout=60).json()


def stream_history_range(
    from_dt: datetime,
    to_dt: datetime,
    tags: list[str] | None = None,
):
    """Генератор: читает NDJSON построчно через отдельную сессию."""
    import json as _json
    params: dict = {"from_dt": from_dt.isoformat(), "to_dt": to_dt.isoformat()}
    if tags:
        params["tags"] = tags
    with requests.Session() as s:
        with s.get(_url("/history/stream"), params=params, stream=True, timeout=None) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    yield _json.loads(line)


def export_date_range(from_dt: datetime, to_dt: datetime) -> dict:
    params = {"from_dt": from_dt.isoformat(), "to_dt": to_dt.isoformat()}
    return _post("/history/export-range", params=params, timeout=TIMEOUT).json()


def get_usb_devices() -> list[dict]:
    return _get("/usb/devices", timeout=TIMEOUT).json()


def get_usb_export_status() -> str:
    return _get("/usb/export-status", timeout=TIMEOUT).json().get("status", "idle")


def download_db() -> bytes:
    return _get("/db/download", timeout=120).content


def get_disk_status() -> dict | None:
    try:
        return _get("/disk/status", timeout=TIMEOUT).json()
    except requests.RequestException:
        return None
