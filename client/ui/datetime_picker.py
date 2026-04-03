"""
DateTimePicker — единая кнопка, попап: сначала календарь → потом циферблат.
"""
import math
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QFrame, QCalendarWidget, QStackedWidget, QLineEdit,
)
from PyQt6.QtCore import Qt, QDate, QDateTime, QPoint, QRect, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QBrush, QPolygonF
from PyQt6.QtCore import QPointF


# ── Циферблат ──────────────────────────────────────────────────────────────────

class _ClockFace(QWidget):
    done = pyqtSignal(int, int)   # (hour, minute)

    _SIZE = 240
    _R    = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self._SIZE, self._SIZE)
        self.setMouseTracking(True)
        self._mode      = "hour"
        self._hour      = 0
        self._minute    = 0
        self._hover_val = None
        self._cursor_x  = None
        self._cursor_y  = None

    def reset(self, hour: int, minute: int):
        self._hour     = hour
        self._minute   = minute
        self._mode     = "hour"
        self._hover_val = None
        self._cursor_x  = None
        self._cursor_y  = None
        self.update()

    def _cx(self): return self.width()  // 2
    def _cy(self): return self.height() // 2

    @staticmethod
    def _angle(value: int, total: int) -> float:
        return (value / total) * 2 * math.pi - math.pi / 2

    def _pos(self, value: int, total: int, r: float):
        a = self._angle(value, total)
        return self._cx() + r * math.cos(a), self._cy() + r * math.sin(a)

    def _val_from_pos(self, px: float, py: float):
        dx, dy = px - self._cx(), py - self._cy()
        dist   = math.hypot(dx, dy)
        angle  = math.atan2(dy, dx) + math.pi / 2
        if angle < 0:
            angle += 2 * math.pi
        if self._mode == "hour":
            h12 = round(angle / (2 * math.pi) * 12) % 12
            if dist < self._R * 0.68:
                return h12 + 12 if h12 != 0 else 0
            return h12 if h12 != 0 else 12
        else:
            return round(angle / (2 * math.pi) * 60) % 60

    def _hand_tip(self, cx, cy, R):
        val = self._hover_val
        if self._mode == "hour":
            h = val if val is not None else self._hour
            is_inner = (h == 0 or h > 12)
            r = R * 0.55 if is_inner else R * 0.80
            return self._pos(h % 12 or 12, 12, r)
        else:
            m = val if val is not None else self._minute
            return self._pos(m, 60, R * 0.80)

    def mouseMoveEvent(self, event):
        self._cursor_x  = event.position().x()
        self._cursor_y  = event.position().y()
        self._hover_val = self._val_from_pos(self._cursor_x, self._cursor_y)
        self.update()

    def mousePressEvent(self, event):
        val = self._val_from_pos(event.position().x(), event.position().y())
        if self._mode == "hour":
            self._hour = val
            self._mode = "minute"
            self._cursor_x = self._cursor_y = None
            self._hover_val = None
        else:
            self._minute = val
            self.done.emit(self._hour, self._minute)
        self.update()

    def leaveEvent(self, event):
        self._hover_val = None
        self._cursor_x  = None
        self._cursor_y  = None
        self.update()

    # ── отрисовка ─────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, R = self._cx(), self._cy(), self._R

        p.setBrush(QBrush(QColor("#2b2b2b")))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx - R, cy - R, 2 * R, 2 * R)

        p.setPen(QPen(QColor("#555555"), 1))
        for i in range(60):
            a  = self._angle(i, 60)
            r0 = R - (6 if i % 5 == 0 else 3)
            p.drawLine(int(cx + r0 * math.cos(a)), int(cy + r0 * math.sin(a)),
                       int(cx + (R-1) * math.cos(a)), int(cy + (R-1) * math.sin(a)))

        if self._mode == "hour":
            self._draw_hours(p, cx, cy, R)
        else:
            self._draw_minutes(p, cx, cy, R)

        p.setBrush(QBrush(QColor("#4fc3f7")))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx - 5, cy - 5, 10, 10)

    def _draw_hand(self, p, cx, cy, x, y, r=13):
        p.setPen(QPen(QColor("#4fc3f7"), 2))
        p.drawLine(cx, cy, int(x), int(y))
        p.setBrush(QBrush(QColor("#4fc3f7")))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(int(x) - r, int(y) - r, r * 2, r * 2)

    def _draw_num(self, p, x, y, text: str, selected: bool, hovered: bool, r: int = 13):
        if selected:
            p.setBrush(QBrush(QColor("#4fc3f7")))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(int(x) - r, int(y) - r, r * 2, r * 2)
        p.setPen(QColor("white" if selected else "#cccccc"))
        fs = 10 if r >= 12 else 8
        p.setFont(QFont("Arial", fs, QFont.Weight.Bold if selected else QFont.Weight.Normal))
        p.drawText(QRect(int(x)-r, int(y)-r, r*2, r*2), Qt.AlignmentFlag.AlignCenter, text)

    def _draw_hours(self, p, cx, cy, R):
        hx, hy = self._hand_tip(cx, cy, R)
        is_inner = self._hour == 0 or self._hour > 12
        self._draw_hand(p, cx, cy, hx, hy, r=10 if is_inner else 13)

        is_inner = self._hour == 0 or self._hour > 12
        for h in range(1, 13):
            x, y = self._pos(h, 12, R * 0.80)
            self._draw_num(p, x, y, str(h),
                           (not is_inner) and self._hour % 12 == h % 12,
                           self._hover_val == h)
        for h in list(range(13, 24)) + [0]:
            x, y = self._pos(h % 12 or 12, 12, R * 0.55)
            self._draw_num(p, x, y, str(h),
                           is_inner and self._hour == h,
                           self._hover_val == h,
                           r=10)

        p.setPen(QColor("#666"))
        p.setFont(QFont("Arial", 8))
        p.drawText(QRect(cx-40, cy+R+4, 80, 16), Qt.AlignmentFlag.AlignCenter, "часы")

    def _draw_minutes(self, p, cx, cy, R):
        mx, my = self._hand_tip(cx, cy, R)
        self._draw_hand(p, cx, cy, mx, my)

        for m in range(0, 60, 5):
            x, y = self._pos(m, 60, R * 0.80)
            self._draw_num(p, x, y, f"{m:02d}",
                           self._minute == m,
                           self._hover_val == m)

        p.setPen(QColor("#666"))
        p.setFont(QFont("Arial", 8))
        p.drawText(QRect(cx-40, cy+R+4, 80, 16), Qt.AlignmentFlag.AlignCenter, "минуты")


# ── Попап: календарь → циферблат ──────────────────────────────────────────────

class _Popup(QFrame):
    def __init__(self, dt: QDateTime, callback, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._callback = callback
        self._date     = dt.date()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # ── Страница 0: календарь ─────────────────────────────────────────────
        self._cal = QCalendarWidget()
        self._cal.setSelectedDate(dt.date())
        self._cal.setGridVisible(True)
        self._cal.clicked.connect(self._on_date_picked)
        self._stack.addWidget(self._cal)

        # ── Страница 1: циферблат ─────────────────────────────────────────────
        clock_page = QWidget()
        cl = QVBoxLayout(clock_page)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)

        self._time_label = QLabel()
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_label.setStyleSheet(
            "font-size: 26px; font-weight: bold; color: #4fc3f7;")
        cl.addWidget(self._time_label)

        self._clock = _ClockFace()
        self._clock.done.connect(self._on_time_picked)
        # Обновляем лейбл при движении
        orig_move = self._clock.mouseMoveEvent
        def _move(ev):
            orig_move(ev)
            self._update_time_label()
        self._clock.mouseMoveEvent = _move
        cl.addWidget(self._clock, alignment=Qt.AlignmentFlag.AlignCenter)

        self._stack.addWidget(clock_page)

        self._clock.reset(dt.time().hour(), dt.time().minute())
        self._update_time_label()
        self.adjustSize()

    def _update_time_label(self):
        hv = self._clock._hover_val
        h  = self._clock._hour
        m  = self._clock._minute
        if self._clock._mode == "hour" and hv is not None:
            self._time_label.setText(
                f"{self._date.toString('dd.MM.yyyy')}  {hv:02d}:{m:02d}")
        elif self._clock._mode == "minute" and hv is not None:
            self._time_label.setText(
                f"{self._date.toString('dd.MM.yyyy')}  {h:02d}:{hv:02d}")
        else:
            self._time_label.setText(
                f"{self._date.toString('dd.MM.yyyy')}  {h:02d}:{m:02d}")

    def _on_date_picked(self, date: QDate):
        self._date = date
        self._stack.setCurrentIndex(1)
        self.adjustSize()

    def _on_time_picked(self, hour: int, minute: int):
        dt = QDateTime(
            self._date.year(), self._date.month(), self._date.day(),
            hour, minute, 0,
        )
        self._callback(dt)
        self.close()


# ── Кнопка-стрелка ────────────────────────────────────────────────────────────

class _ArrowButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pressed = False
        self._hovered = False

    def enterEvent(self, e):
        self._hovered = True;  self.update()

    def leaveEvent(self, e):
        self._hovered = False; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True;  self.update()

    def mouseReleaseEvent(self, e):
        if self._pressed and e.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            self.update()
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # Фон
        if self._pressed:
            bg = QColor("#3a3a3a")
        elif self._hovered:
            bg = QColor("#4a4a4a")
        else:
            bg = QColor("#353535")
        p.setBrush(QBrush(bg))
        p.setPen(QPen(QColor("#606060"), 1))
        p.drawRoundedRect(1, 1, w - 2, h - 2, 3, 3)

        # Треугольник вниз
        cx = w / 2
        cy = h / 2 + 1
        tw, th = 7.0, 4.0
        tri = QPolygonF([
            QPointF(cx - tw / 2, cy - th / 2),
            QPointF(cx + tw / 2, cy - th / 2),
            QPointF(cx,          cy + th / 2),
        ])
        p.setBrush(QBrush(QColor("#aaaaaa") if not self._hovered else QColor("#ffffff")))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(tri)


# ── Публичный виджет ──────────────────────────────────────────────────────────

_FMT = "dd.MM.yyyy HH:mm"
_PY_FMT = "%d.%m.%Y %H:%M"


class DateTimePicker(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("дд.мм.гггг чч:мм")
        self._edit.setMinimumWidth(130)
        self._edit.editingFinished.connect(self._on_manual_edit)
        layout.addWidget(self._edit)

        self._arrow = _ArrowButton()
        self._arrow.clicked.connect(self._open)
        layout.addWidget(self._arrow)

        self._dt = QDateTime.currentDateTime()
        self._sync_edit()

    def _open(self):
        # Если в поле уже введено корректное время — открываем с ним
        self._try_parse_edit()
        popup = _Popup(self._dt, self._on_picked)
        pos = self._edit.mapToGlobal(QPoint(0, self._edit.height()))
        popup.move(pos)
        popup.show()

    def _on_picked(self, dt: QDateTime):
        self._dt = dt
        self._sync_edit()

    def _on_manual_edit(self):
        self._try_parse_edit()

    def _try_parse_edit(self):
        from datetime import datetime as _dt
        text = self._edit.text().strip()
        try:
            parsed = _dt.strptime(text, _PY_FMT)
            self._dt = QDateTime(
                parsed.year, parsed.month, parsed.day,
                parsed.hour, parsed.minute, 0,
            )
            self._edit.setStyleSheet("")
        except ValueError:
            self._edit.setStyleSheet("border: 1px solid #e74c3c;")

    def _sync_edit(self):
        self._edit.setStyleSheet("")
        self._edit.setText(self._dt.toString(_FMT))

    def dateTime(self) -> QDateTime:
        self._try_parse_edit()
        return self._dt

    def setDateTime(self, dt: QDateTime):
        self._dt = dt
        self._sync_edit()
