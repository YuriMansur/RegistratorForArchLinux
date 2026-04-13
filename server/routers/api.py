import io
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db.schemas import TagValueOut, TagHistoryOut, CheckoutOut
from db.session_exporter import EXPORT_DIR, export_by_test_id, export_by_date_range
from usb import usb_monitor, usb_exporter
from services.tag_service import TagRepository, TagService
from services.checkout_service import CheckoutRepository, CheckoutService
from services.history_service import HistoryRepository, HistoryService
from services import live_data

router = APIRouter()


# ── Tags ──────────────────────────────────────────────────────────────────────

@router.get("/tags/latest", response_model=list[TagValueOut])
async def get_latest_tags(db: AsyncSession = Depends(get_db)):
    return await TagService(TagRepository(db)).get_all()


@router.get("/tags/live")
async def get_live_tags() -> list[dict]:
    return live_data.get_all()


# ── Checkouts ─────────────────────────────────────────────────────────────────

@router.get("/checkouts", response_model=list[CheckoutOut])
async def get_checkouts(db: AsyncSession = Depends(get_db)):
    return await CheckoutService(CheckoutRepository(db)).get_all()


@router.post("/checkouts/{checkout_id}/export", status_code=202)
async def export_checkout(
    checkout_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    await CheckoutService(CheckoutRepository(db)).get_by_id(checkout_id)
    background_tasks.add_task(export_by_test_id, checkout_id)
    return {"status": "export started", "checkout_id": checkout_id}


@router.get("/checkouts/{checkout_id}/history", response_model=list[TagHistoryOut])
async def get_checkout_history(checkout_id: int, db: AsyncSession = Depends(get_db)):
    return await HistoryService(HistoryRepository(db)).get_by_checkout(checkout_id)


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/history", response_model=list[TagHistoryOut])
async def get_history(limit: int = 1000, db: AsyncSession = Depends(get_db)):
    return await HistoryService(HistoryRepository(db)).get_recent(limit)


@router.get("/history/range/count")
async def get_history_range_count(
    from_dt: datetime,
    to_dt: datetime,
    db: AsyncSession = Depends(get_db),
) -> dict:
    count = await HistoryService(HistoryRepository(db)).count_range(from_dt, to_dt)
    return {"count": count}


@router.get("/history/range", response_model=list[TagHistoryOut])
async def get_history_range(
    from_dt: datetime,
    to_dt: datetime,
    tags: Optional[list[str]] = Query(default=None),
    max_points: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await HistoryService(HistoryRepository(db)).get_range(from_dt, to_dt, tags, max_points)


@router.get("/history/stream")
async def stream_history_range(
    from_dt: datetime,
    to_dt: datetime,
    tags: Optional[list[str]] = Query(default=None),
):
    from db.database import AsyncSessionLocal

    async def _generate():
        async with AsyncSessionLocal() as db:
            async for line in HistoryRepository(db).stream_range(from_dt, to_dt, tags):
                yield line

    return StreamingResponse(_generate(), media_type="application/x-ndjson")


@router.post("/history/export-range", status_code=202)
async def export_history_range(
    from_dt: datetime,
    to_dt: datetime,
    background_tasks: BackgroundTasks,
):
    background_tasks.add_task(export_by_date_range, from_dt, to_dt)
    return {"status": "export started"}


# ── Exports ───────────────────────────────────────────────────────────────────

@router.get("/exports")
async def list_exports() -> list[dict]:
    if not EXPORT_DIR.exists():
        return []
    result = []
    for folder in sorted(EXPORT_DIR.iterdir()):
        if not folder.is_dir():
            continue
        # Читаем содержимое один раз — избегаем race condition при двойном iterdir()
        files = sorted(f for f in folder.iterdir() if f.is_file())
        result.append({
            "folder": folder.name,
            "files": [f.name for f in files],
            "mtime": max((f.stat().st_mtime for f in files), default=0),
        })
    return result


@router.get("/exports/{folder_name}/download")
async def download_export_folder(folder_name: str):
    folder = (EXPORT_DIR / folder_name).resolve()
    # Защита от path traversal: убеждаемся что папка находится внутри EXPORT_DIR
    if not str(folder).startswith(str(EXPORT_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Недопустимое имя папки")
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=404, detail="Папка не найдена")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.iterdir()):
            if f.is_file():
                zf.write(f, f.name)
    size = buf.tell()
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={folder_name}.zip",
            "Content-Length": str(size),
        },
    )


# ── Disk ──────────────────────────────────────────────────────────────────────

_HOME = Path("/home/user")
_DB_BACKUPS = _HOME / "registrator_backups"
_SYS_BACKUPS = _HOME / "system_backups"


@router.get("/disk/status")
async def get_disk_status() -> dict:
    usage = shutil.disk_usage(_HOME)
    db_path = Path("/home/user/registrator.db")
    db_mb = round(db_path.stat().st_size / 1024**2, 1) if db_path.exists() else 0
    return {
        "free_gb": round(usage.free / 1024**3, 1),
        "total_gb": round(usage.total / 1024**3, 1),
        "used_percent": round(usage.used / usage.total * 100, 1),
        "db_mb": db_mb,
        "db_backups_count": len(list(_DB_BACKUPS.glob("*"))) if _DB_BACKUPS.exists() else 0,
        "system_backups_count": len(list(_SYS_BACKUPS.glob("*.fsa"))) if _SYS_BACKUPS.exists() else 0,
    }


@router.get("/db/download")
async def download_db():
    import asyncio
    import sqlite3 as _sqlite3
    import tempfile
    db_path = Path("/home/user/registrator.db")
    if not db_path.exists():
        raise HTTPException(status_code=404, detail="БД не найдена")

    # Создаём консистентный бэкап (включает WAL) во временный файл
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    tmp_path = Path(tmp.name)

    def _backup():
        src = _sqlite3.connect(str(db_path))
        dst = _sqlite3.connect(str(tmp_path))
        src.backup(dst)
        dst.close()
        src.close()

    await asyncio.get_running_loop().run_in_executor(None, _backup)

    size = tmp_path.stat().st_size

    def _iter():
        try:
            with open(tmp_path, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    yield chunk
        finally:
            tmp_path.unlink(missing_ok=True)

    filename = f"registrator_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.db"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    # Content-Length передаём только если < 2GB — requests не поддерживает больше
    if size < 2 * 1024 ** 3:
        headers["Content-Length"] = str(size)
    else:
        headers["X-File-Size"] = str(size)
    return StreamingResponse(
        _iter(),
        media_type="application/octet-stream",
        headers=headers,
    )


# ── USB ───────────────────────────────────────────────────────────────────────

@router.get("/usb/devices")
async def get_usb_devices() -> list[dict]:
    return usb_monitor.get_devices()


@router.get("/usb/export-status")
async def get_export_status() -> dict:
    return {"status": usb_exporter.get_status()}
