from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
import api_client


def _utc_to_local(utc_str: str) -> str:
    try:
        dt = datetime.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return utc_str


_COLUMNS = ["#", "Тег", "Значение", "Время"]


class HistoryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(5000)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        self._count_label = QLabel("")
        btn_refresh = QPushButton("Обновить")
        btn_refresh.clicked.connect(self._refresh)
        toolbar.addWidget(self._count_label)
        toolbar.addStretch()
        toolbar.addWidget(btn_refresh)
        layout.addLayout(toolbar)

        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 60)
        self._table.setColumnWidth(1, 200)
        self._table.setColumnWidth(2, 250)
        layout.addWidget(self._table)

    def _refresh(self):
        try:
            rows = api_client.get_history(limit=1000)
        except Exception:
            return

        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            num = QTableWidgetItem(str(len(rows) - i))
            num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(i, 0, num)
            self._table.setItem(i, 1, QTableWidgetItem(row.get("tag_name", "")))
            self._table.setItem(i, 2, QTableWidgetItem(row.get("value", "")))
            self._table.setItem(i, 3, QTableWidgetItem(
                _utc_to_local(row.get("recorded_at", ""))
            ))

        self._count_label.setText(f"Записей: {len(rows)}")
