import io
import threading
import zipfile
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import Record, TagValue, TagHistory, Tag, Checkout
from db.schemas import RecordCreate, RecordUpdate, RecordOut, TagValueOut, TagHistoryOut, CheckoutOut
from usb import usb_monitor, usb_exporter

router = APIRouter()


# ── Records ───────────────────────────────────────────────────────────────────

@router.get("/records/", response_model=list[RecordOut])
def list_records(db: Session = Depends(get_db)):
    return db.query(Record).order_by(Record.created_at.desc()).all()


@router.post("/records/", response_model=RecordOut, status_code=201)
def create_record(payload: RecordCreate, db: Session = Depends(get_db)):
    record = Record(**payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/records/{record_id}", response_model=RecordOut)
def get_record(record_id: int, db: Session = Depends(get_db)):
    record = db.query(Record).filter(Record.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


@router.put("/records/{record_id}", response_model=RecordOut)
def update_record(record_id: int, payload: RecordUpdate, db: Session = Depends(get_db)):
    record = db.query(Record).filter(Record.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(record, field, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/records/{record_id}", status_code=204)
def delete_record(record_id: int, db: Session = Depends(get_db)):
    record = db.query(Record).filter(Record.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    db.delete(record)
    db.commit()


# ── Tags ──────────────────────────────────────────────────────────────────────

@router.get("/tags/latest", response_model=list[TagValueOut])
def get_latest_tags(db: Session = Depends(get_db)):
    return db.query(TagValue).order_by(TagValue.tag_name).all()


@router.get("/tags/latest/{tag_id:path}", response_model=TagValueOut)
def get_tag(tag_id: str, db: Session = Depends(get_db)):
    row = db.get(TagValue, tag_id)
    if not row:
        raise HTTPException(status_code=404, detail="Tag not found")
    return row


# ── Checkouts ─────────────────────────────────────────────────────────────────

@router.get("/checkouts", response_model=list[CheckoutOut])
def get_checkouts(db: Session = Depends(get_db)):
    return db.query(Checkout).order_by(Checkout.started_at.desc()).all()


@router.post("/checkouts/{checkout_id}/export", status_code=202)
def export_checkout(checkout_id: int, db: Session = Depends(get_db)):
    checkout = db.get(Checkout, checkout_id)
    if not checkout:
        raise HTTPException(status_code=404, detail="Checkout not found")
    from db import session_exporter
    threading.Thread(
        target=session_exporter.export_by_test_id,
        args=(checkout_id,),
        daemon=True,
    ).start()
    return {"status": "export started", "checkout_id": checkout_id}


@router.get("/checkouts/{checkout_id}/history", response_model=list[TagHistoryOut])
def get_checkout_history(checkout_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(TagHistory, Tag)
        .outerjoin(Tag, TagHistory.tag_id == Tag.id)
        .filter(TagHistory.test_id == checkout_id)
        .order_by(TagHistory.recorded_at)
        .all()
    )
    result = []
    for h, tag in rows:
        h.tag_name = tag.name if tag else ""
        result.append(h)
    return result


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/history", response_model=list[TagHistoryOut])
def get_history(limit: int = 1000, db: Session = Depends(get_db)):
    rows = (
        db.query(TagHistory, Tag)
        .outerjoin(Tag, TagHistory.tag_id == Tag.id)
        .order_by(TagHistory.recorded_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for h, tag in rows:
        h.tag_name = tag.name if tag else ""
        result.append(h)
    return result


@router.get("/history/range", response_model=list[TagHistoryOut])
def get_history_range(
    from_dt: datetime,
    to_dt: datetime,
    tags: Optional[list[str]] = Query(default=None),
    db: Session = Depends(get_db),
):
    # SQLite хранит naive UTC — снимаем tzinfo перед сравнением
    from_naive = from_dt.replace(tzinfo=None)
    to_naive   = to_dt.replace(tzinfo=None)
    q = (
        db.query(TagHistory, Tag)
        .outerjoin(Tag, TagHistory.tag_id == Tag.id)
        .filter(TagHistory.recorded_at >= from_naive)
        .filter(TagHistory.recorded_at <= to_naive)
    )
    if tags:
        q = q.filter(Tag.name.in_(tags))
    rows = q.order_by(TagHistory.recorded_at).all()
    result = []
    for h, tag in rows:
        h.tag_name = tag.name if tag else ""
        result.append(h)
    return result


# ── Exports ───────────────────────────────────────────────────────────────────

@router.get("/exports")
def list_exports() -> list[dict]:
    from db.session_exporter import EXPORT_DIR
    if not EXPORT_DIR.exists():
        return []
    result = []
    for folder in sorted(EXPORT_DIR.iterdir()):
        if folder.is_dir():
            files = sorted(f.name for f in folder.iterdir() if f.is_file())
            result.append({"folder": folder.name, "files": files})
    return result


@router.get("/exports/{folder_name}/download")
def download_export_folder(folder_name: str):
    from db.session_exporter import EXPORT_DIR
    folder = EXPORT_DIR / folder_name
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=404, detail="Папка не найдена")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.iterdir()):
            if f.is_file():
                zf.write(f, f.name)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={folder_name}.zip"},
    )


# ── USB ───────────────────────────────────────────────────────────────────────

@router.get("/usb/devices")
def get_usb_devices() -> list[dict]:
    return usb_monitor.get_devices()


@router.get("/usb/export-status")
def get_export_status() -> dict:
    return {"status": usb_exporter.get_status()}
