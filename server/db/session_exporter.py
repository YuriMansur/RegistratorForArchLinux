"""
SessionExporter — экспорт данных сессии в xlsx и docx на диск сервера.
Вызывается когда End=True.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

EXPORT_DIR = Path("/home/user/registrator/exports")

# Теги, которые не попадают в экспорт (управляющие, служебные и т.д.)
# Добавляй сюда имена тегов (Tag.name) которые не нужны в таблице.
_EXCLUDE_TAG_NAMES: set[str] = {
    "inProcess",
    "End",
}

log = logging.getLogger(__name__)


def _to_local(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _fmt(dt: datetime) -> str:
    return dt.astimezone().strftime("%Y-%m-%d_%H-%M-%S")


def export_session(session_start: datetime, session_end: datetime, test_id: int) -> None:
    """Экспортировать данные испытания (автоматический вызов при End=True)."""
    _export(test_id, session_start, session_end)


def export_by_test_id(test_id: int) -> None:
    """Экспортировать данные испытания по его ID (ручной вызов из GUI)."""
    from db.database import SessionLocal
    from db.models import Checkout

    db = SessionLocal()
    try:
        checkout = db.get(Checkout, test_id)
        if checkout is None:
            log.warning("export_by_test_id: checkout %s not found", test_id)
            return
        started_at = checkout.started_at.replace(tzinfo=timezone.utc) \
            if checkout.started_at.tzinfo is None else checkout.started_at
        ended_at   = checkout.ended_at or datetime.now(timezone.utc)
        if ended_at.tzinfo is None:
            ended_at = ended_at.replace(tzinfo=timezone.utc)
    finally:
        db.close()

    _export(test_id, started_at, ended_at)


def export_by_date_range(from_dt: datetime, to_dt: datetime) -> None:
    """Экспортировать данные по произвольному диапазону дат (ручной вызов из GUI)."""
    from db.database import SessionLocal
    from db.models import TagHistory, Tag

    if from_dt.tzinfo is None:
        from_dt = from_dt.replace(tzinfo=timezone.utc)
    if to_dt.tzinfo is None:
        to_dt = to_dt.replace(tzinfo=timezone.utc)

    from_naive = from_dt.replace(tzinfo=None)
    to_naive   = to_dt.replace(tzinfo=None)

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        rows = (
            db.query(TagHistory, Tag)
            .outerjoin(Tag, TagHistory.tag_id == Tag.id)
            .filter(TagHistory.recorded_at >= from_naive)
            .filter(TagHistory.recorded_at <= to_naive)
            .order_by(TagHistory.recorded_at)
            .all()
        )
    finally:
        db.close()

    if not rows:
        log.warning("Export range: no rows found for %s — %s", from_dt, to_dt)
        return

    folder_name = f"Data_{_fmt(from_dt)}_{_fmt(to_dt)}"
    session_dir = EXPORT_DIR / folder_name
    session_dir.mkdir(parents=True, exist_ok=True)

    ts = _fmt(to_dt)
    _write_xlsx(session_dir / f"data_{ts}.xlsx", rows)
    _write_docx(session_dir / f"data_{ts}.docx", rows)
    _write_png_per_tag(session_dir, rows)
    log.info("Export range done: %d rows → %s", len(rows), session_dir.name)


def _export(test_id: int, session_start: datetime, session_end: datetime) -> None:
    """Общая логика: запросить TagHistory по test_id, записать xlsx и docx."""
    from db.database import SessionLocal
    from db.models import TagHistory, Tag

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        rows = (
            db.query(TagHistory, Tag)
            .outerjoin(Tag, TagHistory.tag_id == Tag.id)
            .filter(TagHistory.test_id == test_id)
            .order_by(TagHistory.recorded_at)
            .all()
        )
    finally:
        db.close()

    if not rows:
        log.warning("Export: no rows found for test_id=%s", test_id)
        return

    session_dir = EXPORT_DIR / f"checkout_{test_id}_{_fmt(session_start)}_{_fmt(session_end)}"
    session_dir.mkdir(parents=True, exist_ok=True)

    ts = _fmt(session_end)
    _write_xlsx(session_dir / f"session_{ts}.xlsx", rows)
    _write_docx(session_dir / f"session_{ts}.docx", rows)
    _write_png_per_tag(session_dir, rows)
    log.info("Export done: %d rows → %s", len(rows), session_dir.name)


def _pivot(rows: list):
    """Сгруппировать строки по времени — каждый тег становится колонкой.
    Возвращает:
        headers — список заголовков колонок: "Имя [единицы]"
        data    — dict {recorded_at: {header: value}}
    """
    from collections import defaultdict
    # Сохраняем порядок тегов по первому появлению
    headers = []
    data = defaultdict(dict)
    for h, tag in rows:
        name  = tag.name  if tag else str(h.tag_id)
        if name in _EXCLUDE_TAG_NAMES:
            continue
        units = tag.units if tag else ""
        header = f"{name} [{units}]" if units else name
        if header not in headers:
            headers.append(header)
        data[h.recorded_at][header] = h.value
    return headers, data


def _write_xlsx(path: Path, rows: list) -> None:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Сессия"

    headers, data = _pivot(rows)

    # Заголовок: Время + имя тега [единицы]
    ws.append(["Время"] + headers)

    # Одна строка на каждый момент времени
    for ts in sorted(data.keys()):
        row = [_to_local(ts)]
        for header in headers:
            row.append(data[ts].get(header, ""))
        ws.append(row)

    wb.save(path)


def _write_docx(path: Path, rows: list) -> None:
    from docx import Document
    doc = Document()
    doc.add_heading("Данные сессии OPC UA", 0)
    doc.add_paragraph(f"Записей: {len(rows)}")

    headers, data = _pivot(rows)
    timestamps = sorted(data.keys())

    table = doc.add_table(rows=1, cols=1 + len(headers))
    table.style = "Table Grid"

    # Заголовок: Время + имя тега [единицы]
    hdr = table.rows[0].cells
    hdr[0].text = "Время"
    for i, header in enumerate(headers, 1):
        hdr[i].text = header

    # Одна строка на каждый момент времени
    for ts in timestamps:
        cells = table.add_row().cells
        cells[0].text = _to_local(ts)
        for i, header in enumerate(headers, 1):
            cells[i].text = data[ts].get(header, "")

    doc.save(path)


def _write_png_per_tag(session_dir: Path, rows: list) -> None:
    headers, data = _pivot(rows)
    if not headers or not data:
        return

    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    timestamps = sorted(data.keys())

    for header in headers:
        # Берём только временны́е точки где есть значение этого тега
        tag_times = []
        values = []
        for ts in timestamps:
            v = data[ts].get(header, None)
            if v is None:
                continue
            try:
                val = float(v)
            except (ValueError, TypeError):
                continue
            dt = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
            tag_times.append(dt.astimezone(local_tz))
            values.append(val)

        if not tag_times:
            continue

        fig, ax = plt.subplots(figsize=(14, 6))
        ax.plot(tag_times, values, linewidth=1.2, color="steelblue")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S", tz=local_tz))
        fig.autofmt_xdate()
        ax.set_xlabel("Время")
        ax.set_ylabel(header)
        t_start = tag_times[0].strftime("%d.%m.%Y %H:%M:%S")
        t_end   = tag_times[-1].strftime("%d.%m.%Y %H:%M:%S")
        ax.set_title(f"{header}\n{t_start} — {t_end}", fontsize=11)
        ax.grid(True, linestyle="--", alpha=0.5)
        fig.tight_layout()

        # имя файла: безопасное имя тега (убираем спецсимволы)
        safe_name = header.replace("/", "_").replace(" ", "_").replace("[", "").replace("]", "")
        fig.savefig(session_dir / f"trend_{safe_name}.png", dpi=150)
        plt.close(fig)
