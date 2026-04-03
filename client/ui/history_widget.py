from datetime import datetime, timezone
import datetime as _dt

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QFileIconProvider, QComboBox, QFileDialog,
)
from PyQt6.QtCore import Qt, QTimer, QDateTime, QFileInfo, QObject
import api_client
from ui.datetime_picker import DateTimePicker


def _utc_to_local(utc_str: str) -> str:
    try:
        dt = datetime.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return utc_str


def _iso_to_local_qdt(utc_str: str) -> QDateTime:
    try:
        dt = datetime.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        return QDateTime(local.year, local.month, local.day,
                         local.hour, local.minute, local.second)
    except Exception:
        return QDateTime.currentDateTime()


def _pivot_rows(rows: list[dict]) -> tuple[list[str], list[list[str]]]:
    tags: list[str] = []
    times: list[str] = []
    data: dict[str, dict[str, str]] = {}

    for r in rows:
        tag = r.get("tag_name", "")
        val = r.get("value", "")
        t   = _utc_to_local(r.get("recorded_at", ""))
        if tag and tag not in tags:
            tags.append(tag)
        if t not in data:
            data[t] = {}
            times.append(t)
        data[t][tag] = val

    return tags, [[t] + [data[t].get(tag, "") for tag in tags] for t in times]


def _fill_pivoted(table: QTableWidget, rows: list[dict]) -> None:
    tags, pivoted = _pivot_rows(rows)
    cols = ["Время"] + tags

    v_scroll = table.verticalScrollBar().value()
    h_scroll = table.horizontalScrollBar().value()

    cur_headers = [table.horizontalHeaderItem(c).text()
                   for c in range(table.columnCount())
                   if table.horizontalHeaderItem(c)]
    if cur_headers != cols:
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setColumnWidth(0, 160)
        for c in range(1, len(cols)):
            table.setColumnWidth(c, 140)
        table.horizontalHeader().setStretchLastSection(True)

    table.setRowCount(len(pivoted))
    for i, row in enumerate(pivoted):
        for j, val in enumerate(row):
            table.setItem(i, j, QTableWidgetItem(val))

    table.verticalScrollBar().setValue(v_scroll)
    table.horizontalScrollBar().setValue(h_scroll)


def _make_table() -> QTableWidget:
    t = QTableWidget()
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.verticalHeader().setVisible(False)
    return t


class HistoryController(QObject):
    """Контроллер: управляет данными и таймерами для вкладок архива."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checkouts: list[dict] = []

        self.data_widget    = self._build_data_widget()
        self.exports_widget = self._build_exports_widget()

        self._refresh_checkouts()
        self._refresh_exports()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_exports)
        self._timer.start(5000)

    # ── Построение виджетов ────────────────────────────────────────────────────

    def _build_data_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Строка 1: испытание + диапазон дат + загрузить (стилизованная панель как в трендах)
        _CTRL_STYLE = """
            QFrame { background-color: #2b2b2b; border-bottom: 1px solid #444444; }
            QLabel { color: #cccccc; background: transparent; }
            QPushButton {
                color: #cccccc; background-color: #3a3a3a;
                border: 1px solid #555555; border-radius: 3px; padding: 1px 6px;
            }
            QPushButton:hover { background-color: #484848; }
            QComboBox {
                color: #cccccc; background-color: #3a3a3a;
                border: 1px solid #555555; border-radius: 3px; padding: 1px 4px;
            }
            QLineEdit {
                color: #cccccc; background-color: #3a3a3a;
                border: 1px solid #555555; border-radius: 3px;
                padding: 1px 4px; min-height: 20px;
            }
        """
        ctrl_frame = QFrame()
        ctrl_frame.setStyleSheet(_CTRL_STYLE)
        row1 = QHBoxLayout(ctrl_frame)
        row1.setContentsMargins(8, 4, 8, 4)
        row1.setSpacing(8)

        row1.addWidget(QLabel("Испытание:"))

        self._checkout_combo = QComboBox()
        self._checkout_combo.setEditable(True)
        self._checkout_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._checkout_combo.setMinimumWidth(220)
        completer = self._checkout_combo.completer()
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._checkout_combo.currentIndexChanged.connect(self._on_combo_changed)
        row1.addWidget(self._checkout_combo, stretch=1)

        row1.addWidget(QLabel("С:"))
        self._dt_from = DateTimePicker()
        self._dt_from.setDateTime(QDateTime.currentDateTime().addSecs(-3600))
        row1.addWidget(self._dt_from)

        row1.addWidget(QLabel("По:"))
        self._dt_to = DateTimePicker()
        self._dt_to.setDateTime(QDateTime.currentDateTime())
        row1.addWidget(self._dt_to)

        self._btn_load = QPushButton("Загрузить")
        self._btn_load.clicked.connect(self._load_data)
        row1.addWidget(self._btn_load)

        layout.addWidget(ctrl_frame)

        # Строка 2: экспорт
        row2 = QHBoxLayout()
        self._btn_export = QPushButton("Экспорт docx/xls/png")
        self._btn_export.setEnabled(True)
        self._btn_export.clicked.connect(self._export_selected)
        row2.addWidget(self._btn_export)
        row2.addStretch()
        layout.addLayout(row2)

        self._data_label = QLabel("")
        self._data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._data_label)

        self._data_table = _make_table()
        layout.addWidget(self._data_table)
        return w

    def _build_exports_widget(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(4, 4, 4, 4)
        vl.setSpacing(4)

        hl = QHBoxLayout()
        btn_download = QPushButton("Скачать папку")
        btn_download.clicked.connect(self._download_selected_folder)
        hl.addWidget(btn_download)
        hl.addStretch()
        vl.addLayout(hl)

        self._exports_tree = QTreeWidget()
        self._exports_tree.setHeaderLabel("Файлы экспорта на сервере")
        self._exports_tree.setColumnCount(1)
        vl.addWidget(self._exports_tree)

        self._btn_download_export = btn_download
        return w

    def _download_selected_folder(self):
        item = self._exports_tree.currentItem()
        if item is None:
            return
        if item.parent() is not None:
            item = item.parent()
        folder_name = item.text(0)

        save_path, _ = QFileDialog.getSaveFileName(
            None, "Сохранить архив", f"{folder_name}.zip", "ZIP архив (*.zip)"
        )
        if not save_path:
            return

        try:
            data = api_client.download_export_folder(folder_name)
            Path(save_path).write_bytes(data)
            QMessageBox.information(None, "Скачано", f"Сохранено: {save_path}")
        except Exception as e:
            QMessageBox.warning(None, "Ошибка", f"Не удалось скачать:\n{e}")

    # ── Обновление ────────────────────────────────────────────────────────────

    def _refresh_checkouts(self):
        line_edit = self._checkout_combo.lineEdit()
        if line_edit and line_edit.hasFocus():
            return

        try:
            self._checkouts = api_client.get_checkouts()
        except Exception:
            return

        prev_id = self._checkout_combo.currentData()

        self._checkout_combo.blockSignals(True)
        self._checkout_combo.clear()
        self._checkout_combo.addItem("— Произвольный диапазон —", userData=None)

        restore_idx = 0
        for i, c in enumerate(self._checkouts):
            cid     = c.get("id")
            started = _utc_to_local(c.get("started_at", ""))
            ended   = c.get("ended_at")
            label   = f"#{cid}  {started}" + ("  (активно)" if not ended else "")
            self._checkout_combo.addItem(label, userData=c)
            if isinstance(prev_id, dict) and prev_id.get("id") == cid:
                restore_idx = i + 1

        self._checkout_combo.blockSignals(False)
        self._checkout_combo.setCurrentIndex(restore_idx)
        self._on_combo_changed(restore_idx)

    def _on_combo_changed(self, index: int):
        if index < 0:
            return
        checkout = self._checkout_combo.currentData()
        if checkout is None:
            # Произвольный диапазон — разблокировать пикеры
            self._dt_from.setEnabled(True)
            self._dt_to.setEnabled(True)
        else:
            # Заполнить диапазон из испытания
            started = checkout.get("started_at", "")
            ended   = checkout.get("ended_at")
            if started:
                self._dt_from.setDateTime(_iso_to_local_qdt(started))
            self._dt_to.setDateTime(
                _iso_to_local_qdt(ended) if ended else QDateTime.currentDateTime()
            )
            self._dt_from.setEnabled(False)
            self._dt_to.setEnabled(False)
            self._btn_export.setEnabled(True)

    def _load_data(self):
        """Загрузить данные по кнопке — по диапазону дат."""
        local_tz = _dt.datetime.now(_dt.timezone.utc).astimezone().tzinfo
        from_dt = (self._dt_from.dateTime().toPyDateTime()
                   .replace(tzinfo=local_tz).astimezone(_dt.timezone.utc))
        to_dt   = (self._dt_to.dateTime().toPyDateTime()
                   .replace(tzinfo=local_tz).astimezone(_dt.timezone.utc))
        try:
            rows = api_client.get_history_range(from_dt, to_dt)
            self._data_label.setText(f"{len(rows)} записей за период")
        except Exception as e:
            self._data_label.setText(f"Ошибка: {e}")
            return
        _fill_pivoted(self._data_table, rows)

    def _export_selected(self):
        checkout = self._checkout_combo.currentData()
        try:
            if isinstance(checkout, dict):
                checkout_id = checkout.get("id")
                api_client.export_checkout(checkout_id)
                QMessageBox.information(
                    None, "Экспорт",
                    f"Экспорт испытания #{checkout_id} запущен.\n"
                    f"Файлы сохранятся в папку exports на сервере.",
                )
            else:
                local_tz = _dt.datetime.now(_dt.timezone.utc).astimezone().tzinfo
                from_dt = (self._dt_from.dateTime().toPyDateTime()
                           .replace(tzinfo=local_tz).astimezone(_dt.timezone.utc))
                to_dt   = (self._dt_to.dateTime().toPyDateTime()
                           .replace(tzinfo=local_tz).astimezone(_dt.timezone.utc))
                api_client.export_date_range(from_dt, to_dt)
                QMessageBox.information(
                    None, "Экспорт",
                    f"Экспорт диапазона запущен.\n"
                    f"Файлы сохранятся в папку exports на сервере.",
                )
        except Exception as e:
            QMessageBox.warning(None, "Ошибка", f"Не удалось запустить экспорт:\n{e}")

    def _refresh_exports(self):
        try:
            folders = api_client.get_exports()
        except Exception:
            return

        expanded = set()
        root = self._exports_tree.invisibleRootItem()
        for i in range(root.childCount()):
            it = root.child(i)
            if it.isExpanded():
                expanded.add(it.text(0))

        icon_provider = QFileIconProvider()
        icon_folder = icon_provider.icon(QFileIconProvider.IconType.Folder)

        self._exports_tree.clear()
        for entry in folders:
            folder_item = QTreeWidgetItem([entry["folder"]])
            folder_item.setIcon(0, icon_folder)
            for filename in entry["files"]:
                child = QTreeWidgetItem([filename])
                child.setIcon(0, icon_provider.icon(QFileInfo(filename)))
                folder_item.addChild(child)
            self._exports_tree.addTopLevelItem(folder_item)
            folder_item.setExpanded(entry["folder"] in expanded)
