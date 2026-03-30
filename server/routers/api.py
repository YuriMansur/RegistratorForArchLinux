from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import Record, TagValue, TagHistory, Tag
from db.schemas import RecordCreate, RecordUpdate, RecordOut, TagValueOut, TagHistoryOut
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


# ── USB ───────────────────────────────────────────────────────────────────────

@router.get("/usb/devices")
def get_usb_devices() -> list[dict]:
    return usb_monitor.get_devices()


@router.get("/usb/export-status")
def get_export_status() -> dict:
    return {"status": usb_exporter.get_status()}
