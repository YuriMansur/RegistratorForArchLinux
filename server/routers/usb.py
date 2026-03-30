from fastapi import APIRouter
import server.usb.usb_monitor as usb_monitor
import server.usb.usb_exporter as usb_exporter

router = APIRouter(prefix="/usb", tags=["usb"])


@router.get("/devices")
def get_usb_devices() -> list[dict]:
    """Список подключённых USB-накопителей (только диски с ID_BUS=usb)."""
    return usb_monitor.get_devices()


@router.get("/export-status")
def get_export_status() -> dict:
    """Текущий статус экспорта на флешку."""
    return {"status": usb_exporter.get_status()}
