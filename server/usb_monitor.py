"""
UsbMonitor — обнаружение USB-флешек через pyudev.
Запускается как daemon-поток; работает только на Linux.
"""
import threading
import logging
from typing import Dict, List, Optional, Callable

log = logging.getLogger(__name__)

_devices: Dict[str, dict] = {}       # device_node -> info
_lock = threading.Lock()
_stop_event = threading.Event()
_thread: Optional[threading.Thread] = None

on_inserted: Optional[Callable[[dict], None]] = None
on_removed:  Optional[Callable[[dict], None]] = None


def _make_info(device) -> dict:
    return {
        "node":   device.device_node or "",
        "vendor": device.get("ID_VENDOR",       "Unknown"),
        "model":  device.get("ID_MODEL",        "Unknown"),
        "serial": device.get("ID_SERIAL_SHORT", ""),
    }


def _monitor_loop():
    try:
        import pyudev
    except ImportError:
        log.warning("pyudev not installed — USB monitoring disabled")
        return

    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem="block", device_type="disk")
    monitor.start()

    # Снимок уже подключённых USB-дисков
    for dev in context.list_devices(subsystem="block"):
        if dev.get("DEVTYPE") != "disk":
            continue
        if dev.get("ID_BUS") != "usb":
            continue
        info = _make_info(dev)
        with _lock:
            _devices[info["node"]] = info
        log.info("USB already connected: %s %s (%s)", info["vendor"], info["model"], info["node"])

    import select
    while not _stop_event.is_set():
        r, _, _ = select.select([monitor.fileno()], [], [], 1.0)
        if not r:
            continue
        device = monitor.poll(timeout=0)
        if device is None:
            continue
        if device.get("ID_BUS") != "usb":
            continue

        info = _make_info(device)

        if device.action == "add":
            with _lock:
                _devices[info["node"]] = info
            log.info("USB inserted: %s %s (%s)", info["vendor"], info["model"], info["node"])
            if on_inserted:
                on_inserted(info)

        elif device.action == "remove":
            with _lock:
                _devices.pop(info["node"], None)
            log.info("USB removed: %s %s (%s)", info["vendor"], info["model"], info["node"])
            if on_removed:
                on_removed(info)


def start():
    global _thread
    _stop_event.clear()
    _thread = threading.Thread(target=_monitor_loop, daemon=True, name="usb-monitor")
    _thread.start()


def stop():
    _stop_event.set()


def get_devices() -> List[dict]:
    with _lock:
        return list(_devices.values())
