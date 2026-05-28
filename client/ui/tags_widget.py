import ast
from datetime import datetime, timezone
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt6.QtCore import QTimer, QThread, pyqtSignal
import api_client
import signals


class _TagsWorker(QThread):
    done = pyqtSignal(list)

    def run(self):
        try:
            tags = api_client.get_live_tags()
            if not tags:
                tags = api_client.get_tags()
            self.done.emit(tags)
        except Exception:
            self.done.emit([])


def _utc_to_local(utc_str: str) -> str:
    dt = datetime.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")

_POLL_INTERVAL_MS = 500
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
        self.table.setHorizontalHeaderLabels(["Сигнал", "Значение", "Обновлено"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self.status_label = QLabel("Ожидание данных...")
        layout.addWidget(self.status_label)

    def _start_polling(self):
        self._worker: _TagsWorker | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._load)
        self._timer.start(_POLL_INTERVAL_MS)
        self._load()

    def _load(self):
        # Не запускаем новый запрос если предыдущий ещё не завершился
        if self._worker and self._worker.isRunning():
            return
        self._worker = _TagsWorker()
        self._worker.done.connect(self._on_tags)
        self._worker.start()

    def _on_tags(self, tags: list):
        if not tags:
            self.status_label.setText("Нет данных")
            return
        self._fill(tags)
        visible = [t for t in tags if t["tag_name"] not in _SKIP_TAGS]
        self.status_label.setText(f"Тегов: {len(visible)}")

    def _build_rows(self, tags: list[dict]) -> list[tuple[str, str, str]]:
        """Собрать плоский список (display, value, ts) из тегов."""
        ts = ""
        for tag in tags:
            if tag["tag_name"] not in _SKIP_TAGS and tag.get("updated_at"):
                ts = _utc_to_local(tag["updated_at"][:19])
                break

        rows = []
        for tag in tags:
            name = tag["tag_name"]
            if name in _SKIP_TAGS:
                continue
            value_str = tag["value"]
            if value_str.startswith("["):
                try:
                    items = ast.literal_eval(value_str)
                    for i, item in enumerate(items):
                        rows.append((signals.get_display(f"{name}[{i}]"), str(item), ts))
                    continue
                except Exception:
                    pass
            rows.append((signals.get_display(name), value_str, ts))
        return rows

    def _fill(self, tags: list[dict]):
        rows = self._build_rows(tags)

        if self.table.rowCount() == len(rows):
            # Число строк не изменилось — обновляем текст на месте, без мерцания.
            for r, (display, value, ts) in enumerate(rows):
                self.table.item(r, 0).setText(display)
                self.table.item(r, 1).setText(value)
                self.table.item(r, 2).setText(ts)
        else:
            # Состав тегов изменился — перестраиваем таблицу.
            self.table.setRowCount(0)
            for display, value, ts in rows:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(display))
                self.table.setItem(row, 1, QTableWidgetItem(value))
                self.table.setItem(row, 2, QTableWidgetItem(ts))
