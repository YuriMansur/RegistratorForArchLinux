import requests
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QPushButton, QSpinBox, QHeaderView,
)
from PyQt6.QtCore import QTimer
import api_client


class TagsWidget(QWidget):
    """Виджет отображения последних значений OPC UA тегов с авто-обновлением."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._start_polling()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Теги OPC UA — последние значения"))
        toolbar.addStretch()
        toolbar.addWidget(QLabel("Обновление каждые:"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 60)
        self.interval_spin.setValue(2)
        self.interval_spin.setSuffix(" сек")
        self.interval_spin.valueChanged.connect(self._restart_polling)
        toolbar.addWidget(self.interval_spin)
        self.btn_refresh = QPushButton("Обновить")
        self.btn_refresh.clicked.connect(self._load)
        toolbar.addWidget(self.btn_refresh)
        layout.addLayout(toolbar)

        # Table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Тег (Node ID)", "Имя", "Значение", "Обновлено"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self.status_label = QLabel("Ожидание данных...")
        layout.addWidget(self.status_label)

    def _start_polling(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._load)
        self._timer.start(self.interval_spin.value() * 1000)
        self._load()

    def _restart_polling(self):
        self._timer.start(self.interval_spin.value() * 1000)

    def _load(self):
        try:
            tags = api_client.get_tags()
            self._fill(tags)
            self.status_label.setText(f"Тегов: {len(tags)}")
        except requests.RequestException as e:
            self.status_label.setText(f"Ошибка: {e}")

    def _fill(self, tags: list[dict]):
        self.table.setRowCount(0)
        for tag in tags:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(tag["tag_id"]))
            self.table.setItem(row, 1, QTableWidgetItem(tag["tag_name"]))
            self.table.setItem(row, 2, QTableWidgetItem(tag["value"]))
            updated = tag["updated_at"][:19].replace("T", " ")
            self.table.setItem(row, 3, QTableWidgetItem(updated))
