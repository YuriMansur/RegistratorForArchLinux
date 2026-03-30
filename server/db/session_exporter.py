"""
SessionExporter — экспорт данных сессии в xlsx и docx на диск сервера.
Вызывается когда End=True.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

EXPORT_DIR = Path("/home/user/registrator/exports")

log = logging.getLogger(__name__)


def _to_local(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _fmt(dt: datetime) -> str:
    return dt.astimezone().strftime("%Y-%m-%d_%H-%M-%S")


def export_session(session_start: datetime, session_end: datetime, test_id: int) -> None:
    """Экспортировать строки TagHistory за период сессии в xlsx и docx."""
    from db.database import SessionLocal
    from db.models import TagHistory

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        from db.models import Tag
        from sqlalchemy.orm import outerjoin
        rows = (
            db.query(TagHistory, Tag)
            .outerjoin(Tag, TagHistory.tag_id == Tag.id)
            .filter(TagHistory.recorded_at >= session_start)
            .filter(TagHistory.recorded_at <= session_end)
            .order_by(TagHistory.recorded_at)
            .all()
        )
    finally:
        db.close()

    if not rows:
        log.warning("Session export: no rows found for test_id=%s", test_id)
        return

    dir_name = f"checkout_{test_id}_{_fmt(session_start)}_{_fmt(session_end)}"

    session_dir = EXPORT_DIR / dir_name
    session_dir.mkdir(parents=True, exist_ok=True)

    ts = _fmt(session_end)
    _write_xlsx(session_dir / f"session_{ts}.xlsx", rows)
    _write_docx(session_dir / f"session_{ts}.docx", rows)
    log.info("Session exported: %d rows → %s", len(rows), session_dir.name)


def _write_xlsx(path: Path, rows: list) -> None:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Сессия"
    ws.append(["#", "Название", "Единицы", "Значение", "Время"])
    for i, (h, tag) in enumerate(rows, 1):
        name  = tag.name  if tag else ""
        units = tag.units if tag else ""
        ws.append([i, name, units, h.value, _to_local(h.recorded_at)])
    wb.save(path)


def _write_docx(path: Path, rows: list) -> None:
    from docx import Document
    doc = Document()
    doc.add_heading("Данные сессии OPC UA", 0)
    doc.add_paragraph(f"Записей: {len(rows)}")
    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    hdr[0].text = "Название"
    hdr[1].text = "Единицы"
    hdr[2].text = "Значение"
    hdr[3].text = "Время"
    for h, tag in rows:
        cells = table.add_row().cells
        cells[0].text = tag.name  if tag else ""
        cells[1].text = tag.units if tag else ""
        cells[2].text = h.value
        cells[3].text = _to_local(h.recorded_at)
    doc.save(path)
