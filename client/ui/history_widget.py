from datetime import datetime, timezone
import datetime as _dt

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QFileIconProvider, QComboBox, QFileDialog,
    QProgressBar, QDialog,
)
from PyQt6.QtCore import Qt, QTimer, QDateTime, QFileInfo, QObject, QThread, pyqtSignal
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


class _RefreshCombo(QComboBox):
    def __init__(self, refresh_fn, parent=None):
        super().__init__(parent)
        self._refresh_fn = refresh_fn

    def showPopup(self):
        self._refresh_fn()
        super().showPopup()


class _DownloadWorker(QThread):
    progress = pyqtSignal(float)  # MB скачано
    total    = pyqtSignal(float)  # MB всего
    done     = pyqtSignal(bytes)
    error    = pyqtSignal(str)

    def __init__(self, url_path: str):
        super().__init__()
        self._url_path = url_path

    def run(self):
        import requests
        from config import get_base_url
        try:
            with requests.get(f"{get_base_url()}{self._url_path}", stream=True, timeout=(10, None)) as r:
                r.raise_for_status()
                raw_size = r.headers.get("x-file-size") or r.headers.get("content-length") or "0"
                total_bytes = int(raw_size)
                if total_bytes > 0:
                    self.total.emit(total_bytes / 1024 / 1024)
                chunks = []
                received = 0
                last_emitted = 0
                for chunk in r.iter_content(chunk_size=1024 * 512):
                    if chunk:
                        chunks.append(chunk)
                        received += len(chunk)
                        if received - last_emitted >= 1024 * 1024:
                            self.progress.emit(received / 1024 / 1024)
                            last_emitted = received
                self.progress.emit(received / 1024 / 1024)
                self.done.emit(b"".join(chunks))
        except Exception as e:
            self.error.emit(str(e))


class _ExportWatchWorker(QThread):
    found = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, checkout, from_dt=None, to_dt=None):
        super().__init__()
        self._checkout = checkout
        self._from_dt  = from_dt
        self._to_dt    = to_dt
        self._running  = True

    def run(self):
        import time
        # Снимок до запуска
        try:
            snapshot = {f["folder"]: f.get("mtime", 0) for f in api_client.get_exports()}
        except Exception:
            snapshot = {}

        # Запускаем экспорт
        try:
            if isinstance(self._checkout, dict):
                api_client.export_checkout(self._checkout["id"])
            else:
                api_client.export_date_range(self._from_dt, self._to_dt)
        except Exception as e:
            self.error.emit(str(e))
            return

        # Ждём появления/обновления папки
        while self._running:
            time.sleep(2)
            try:
                for f in api_client.get_exports():
                    folder = f["folder"]
                    mtime  = f.get("mtime", 0)
                    if folder not in snapshot or mtime != snapshot.get(folder, 0):
                        self.found.emit(folder)
                        return
            except Exception:
                pass

    def stop(self):
        self._running = False


class _DataLoadWorker(QThread):
    done  = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, from_dt, to_dt):
        super().__init__()
        self._from_dt = from_dt
        self._to_dt   = to_dt

    def run(self):
        try:
            rows = api_client.get_history_range(self._from_dt, self._to_dt)
            self.done.emit(rows)
        except Exception as e:
            self.error.emit(str(e))


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
        self._timer.timeout.connect(self._refresh_checkouts)
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

        self._checkout_combo = _RefreshCombo(self._refresh_checkouts)
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
        self._start_download(f"/exports/{folder_name}/download", save_path, "Архив сохранён")

    def _start_download(self, url_path: str, save_path: str, success_msg: str):
        dlg = QDialog(None)
        dlg.setWindowTitle("Скачивание")
        dlg.setMinimumWidth(400)
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)
        layout = QVBoxLayout(dlg)

        status_label = QLabel("Подготовка...")
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(status_label)

        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setStyleSheet("""
            QProgressBar {
                text-align: center;
                border: 1px solid #555;
                border-radius: 3px;
                background: #2b2b2b;
                color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #2ecc71;
                border-radius: 3px;
            }
        """)
        layout.addWidget(progress)
        dlg.show()

        worker = _DownloadWorker(url_path)
        self._download_worker = worker
        self._download_dialog = dlg
        self._total_mb = 0.0

        def on_total(total_mb: float):
            self._total_mb = total_mb
            progress.setRange(0, int(total_mb * 10))
            status_label.setText(f"Скачивание... 0.0 / {total_mb:.1f} MB")

        def on_progress(received_mb: float):
            progress.setValue(int(received_mb * 10))
            if self._total_mb > 0:
                status_label.setText(f"Скачивание... {received_mb:.1f} / {self._total_mb:.1f} MB")
            else:
                status_label.setText(f"Скачивание... {received_mb:.1f} MB")

        def on_done(data: bytes):
            Path(save_path).write_bytes(data)
            dlg.hide()
            self._download_dialog = None
            self._download_worker = None
            QMessageBox.information(None, "Скачивание завершено",
                                    f"{success_msg}\n\n{save_path}")

        def on_error(msg: str):
            dlg.hide()
            self._download_dialog = None
            self._download_worker = None
            QMessageBox.warning(None, "Ошибка скачивания", msg)

        worker.total.connect(on_total)
        worker.progress.connect(on_progress)
        worker.done.connect(on_done)
        worker.error.connect(on_error)
        worker.start()

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

        self._checkout_combo.setCurrentIndex(restore_idx)
        self._checkout_combo.blockSignals(False)

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

    def _load_data(self, *_):
        local_tz = _dt.datetime.now(_dt.timezone.utc).astimezone().tzinfo
        from_dt = (self._dt_from.dateTime().toPyDateTime()
                   .replace(tzinfo=local_tz).astimezone(_dt.timezone.utc))
        to_dt   = (self._dt_to.dateTime().toPyDateTime()
                   .replace(tzinfo=local_tz).astimezone(_dt.timezone.utc))
        self._data_label.setText("Загрузка...")
        self._btn_load.setEnabled(False)
        self._worker = _DataLoadWorker(from_dt, to_dt)
        self._worker.done.connect(self._on_data_loaded)
        self._worker.error.connect(self._on_data_error)
        self._worker.start()

    def _on_data_loaded(self, rows: list):
        self._data_label.setText(f"{len(rows)} записей за период")
        self._btn_load.setEnabled(True)
        _fill_pivoted(self._data_table, rows)

    def _on_data_error(self, msg: str):
        self._data_label.setText(f"Ошибка: {msg}")
        self._btn_load.setEnabled(True)

    def _export_selected(self):
        checkout = self._checkout_combo.currentData()
        from_dt = to_dt = None
        if not isinstance(checkout, dict):
            local_tz = _dt.datetime.now(_dt.timezone.utc).astimezone().tzinfo
            from_dt = (self._dt_from.dateTime().toPyDateTime()
                       .replace(tzinfo=local_tz).astimezone(_dt.timezone.utc))
            to_dt   = (self._dt_to.dateTime().toPyDateTime()
                       .replace(tzinfo=local_tz).astimezone(_dt.timezone.utc))

        dlg = QDialog(None)
        dlg.setWindowTitle("Экспорт")
        dlg.setMinimumWidth(350)
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)
        layout = QVBoxLayout(dlg)
        lbl = QLabel("Генерация XLSX / DOCX / PNG...")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setStyleSheet("""
            QProgressBar { text-align: center; border: 1px solid #555; border-radius: 3px; background: #2b2b2b; }
            QProgressBar::chunk { background-color: #2ecc71; border-radius: 3px; }
        """)
        layout.addWidget(bar)
        dlg.show()

        worker = _ExportWatchWorker(checkout, from_dt, to_dt)
        self._export_worker = worker
        self._export_dialog = dlg

        def _on_found(name):
            dlg.hide()
            self._export_dialog = None
            self._export_worker = None
            QMessageBox.information(None, "Экспорт завершён", f"Файлы сохранены в папку:\n{name}")

        def _on_error(msg):
            dlg.hide()
            self._export_dialog = None
            self._export_worker = None
            QMessageBox.warning(None, "Ошибка экспорта", f"Не удалось запустить экспорт:\n{msg}")

        worker.found.connect(_on_found)
        worker.error.connect(_on_error)
        worker.start()

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
