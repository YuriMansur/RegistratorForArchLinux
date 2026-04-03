from datetime import datetime
import requests
from config import get_base_url

TIMEOUT = 5  # seconds


def _url(path: str) -> str:
    return f"{get_base_url()}{path}"


def health_check() -> bool:
    try:
        r = requests.get(_url("/health"), timeout=TIMEOUT)
        return r.status_code == 200
    except requests.RequestException:
        return False


def get_records() -> list[dict]:
    r = requests.get(_url("/records/"), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def create_record(title: str, description: str = "", tags: str = "") -> dict:
    payload = {"title": title, "description": description, "tags": tags}
    r = requests.post(_url("/records/"), json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def update_record(record_id: int, title: str, description: str, tags: str) -> dict:
    payload = {"title": title, "description": description, "tags": tags}
    r = requests.put(_url(f"/records/{record_id}"), json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def delete_record(record_id: int) -> None:
    r = requests.delete(_url(f"/records/{record_id}"), timeout=TIMEOUT)
    r.raise_for_status()


def get_tags() -> list[dict]:
    r = requests.get(_url("/tags/latest"), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_history(limit: int = 10000) -> list[dict]:
    r = requests.get(_url("/history"), params={"limit": limit}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_checkouts() -> list[dict]:
    r = requests.get(_url("/checkouts"), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def export_checkout(checkout_id: int) -> dict:
    r = requests.post(_url(f"/checkouts/{checkout_id}/export"), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_checkout_history(checkout_id: int) -> list[dict]:
    r = requests.get(_url(f"/checkouts/{checkout_id}/history"), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_exports() -> list[dict]:
    r = requests.get(_url("/exports"), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def download_export_folder(folder_name: str) -> bytes:
    r = requests.get(_url(f"/exports/{folder_name}/download"), timeout=60)
    r.raise_for_status()
    return r.content


def get_history_range(from_dt: datetime, to_dt: datetime, tags: list[str] | None = None) -> list[dict]:
    params: dict = {
        "from_dt": from_dt.isoformat(),
        "to_dt":   to_dt.isoformat(),
    }
    if tags:
        params["tags"] = tags
    r = requests.get(_url("/history/range"), params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def export_date_range(from_dt: datetime, to_dt: datetime) -> dict:
    params = {
        "from_dt": from_dt.isoformat(),
        "to_dt":   to_dt.isoformat(),
    }
    r = requests.post(_url("/history/export-range"), params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_usb_devices() -> list[dict]:
    r = requests.get(_url("/usb/devices"), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_usb_export_status() -> str:
    r = requests.get(_url("/usb/export-status"), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("status", "idle")
