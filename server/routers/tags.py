from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import TagValue
from schemas import TagValueOut

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("/latest", response_model=list[TagValueOut])
def get_latest_tags(db: Session = Depends(get_db)):
    """Вернуть последние значения всех OPC UA тегов."""
    return db.query(TagValue).order_by(TagValue.tag_name).all()


@router.get("/latest/{tag_id:path}", response_model=TagValueOut)
def get_tag(tag_id: str, db: Session = Depends(get_db)):
    """Вернуть последнее значение одного тега по его ID."""
    row = db.get(TagValue, tag_id)
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tag not found")
    return row
