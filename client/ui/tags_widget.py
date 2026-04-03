import requests
from datetime import datetime, timezone
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt6.QtCore import QTimer
import api_client


def _utc_to_local(utc_str: str) -> str:
    dt = datetime.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")

_POLL_INTERVAL_MS = 1000
_SKIP_TAGS = {"inProcess", "End"}


class TagsWidget(QWidget):
    """Виджет отображения последних значений OPC UA тегов с авто-обновлением."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._start_polling()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Последние данные"))

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Имя", "Значение", "Обновлено"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self.status_label = QLabel("Ожидание данных...")
        layout.addWidget(self.status_label)

    def _start_polling(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._load)
        self._timer.start(_POLL_INTERVAL_MS)
        self._load()

    def _load(self):
        try:
            tags = api_client.get_tags()
            self._fill(tags)
            visible = [t for t in tags if t["tag_name"] not in _SKIP_TAGS]
            self.status_label.setText(f"Тегов: {len(visible)}")
        except requests.RequestException as e:
            self.status_label.setText(f"Ошибка: {e}")

    def _fill(self, tags: list[dict]):
        self.table.setRowCount(0)
        for tag in tags:
            if tag["tag_name"] in _SKIP_TAGS:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(tag["tag_name"]))
            self.table.setItem(row, 1, QTableWidgetItem(tag["value"]))
            updated = _utc_to_local(tag["updated_at"][:19])
            self.table.setItem(row, 2, QTableWidgetItem(updated))
