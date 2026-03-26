from fastapi import APIRouter
import usb_monitor

router = APIRouter(prefix="/usb", tags=["usb"])


@router.get("/devices")
def get_usb_devices() -> list[dict]:
    """Список подключённых USB-накопителей (только диски с ID_BUS=usb)."""
    return usb_monitor.get_devices()
