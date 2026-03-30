"""
Управление испытаниями (Test) в БД.
"""
from datetime import datetime, timezone
from db.database import SessionLocal
from db.models import Checkout


def start_test() -> int:
    """Создать новое испытание, вернуть его id."""
    db = SessionLocal()
    try:
        checkout = Checkout(started_at=datetime.now(timezone.utc))
        db.add(checkout)
        db.commit()
        db.refresh(checkout)
        return checkout.id
    finally:
        db.close()


def end_test(test_id: int) -> None:
    """Закрыть испытание — записать ended_at."""
    db = SessionLocal()
    try:
        checkout = db.get(Checkout, test_id)
        if checkout:
            checkout.ended_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
