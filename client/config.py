import json
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"
DEFAULT_HOST = "192.168.100.100"
DEFAULT_PORT = 8000


def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"host": DEFAULT_HOST, "port": DEFAULT_PORT}


def save_config(host: str, port: int) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump({"host": host, "port": port}, f, indent=2)


def get_base_url() -> str:
    cfg = load_config()
    return f"http://{cfg['host']}:{cfg['port']}"
