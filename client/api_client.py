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
