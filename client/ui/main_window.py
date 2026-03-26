import requests
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QMessageBox,
    QLabel, QHeaderView, QStatusBar, QTabWidget,
)
from PyQt6.QtCore import Qt, QTimer
import api_client
from ui.record_form import RecordFormDialog
from ui.settings_dialog import SettingsDialog
from ui.tags_widget import TagsWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Registrator")
        self.setMinimumSize(800, 500)
        self._records: list[dict] = []
        self._build_ui()
        self._check_connection()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Tabs
        tabs = QTabWidget()
        root.addWidget(tabs)

        # --- Вкладка 1: Записи ---
        records_tab = QWidget()
        records_layout = QVBoxLayout(records_tab)

        # Toolbar
        toolbar = QHBoxLayout()
        self.btn_add = QPushButton("+ Добавить")
        self.btn_edit = QPushButton("Редактировать")
        self.btn_delete = QPushButton("Удалить")
        self.btn_refresh = QPushButton("Обновить")
        self.btn_settings = QPushButton("Настройки")

        self.btn_edit.setEnabled(False)
        self.btn_delete.setEnabled(False)

        toolbar.addWidget(self.btn_add)
        toolbar.addWidget(self.btn_edit)
        toolbar.addWidget(self.btn_delete)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.btn_settings)
        records_layout.addLayout(toolbar)

        # Table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Заголовок", "Теги", "Дата создания"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        records_layout.addWidget(self.table)

        tabs.addTab(records_tab, "Записи")

        # --- Вкладка 2: OPC UA теги ---
        tabs.addTab(TagsWidget(), "OPC UA теги")

        # Status
        self.status_label = QLabel("Нет подключения")
        self.statusBar().addWidget(self.status_label)

        self.usb_label = QLabel("USB: —")
        self.statusBar().addPermanentWidget(self.usb_label)

        # USB polling timer
        self._usb_timer = QTimer(self)
        self._usb_timer.timeout.connect(self._poll_usb)
        self._usb_timer.start(3000)
        self._poll_usb()

        # Signals
        self.btn_add.clicked.connect(self._on_add)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_refresh.clicked.connect(self._load_records)
        self.btn_settings.clicked.connect(self._on_settings)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(self._on_edit)

    def _check_connection(self):
        if api_client.health_check():
            self.status_label.setText("Подключено к серверу")
            self._load_records()
        else:
            self.status_label.setText("Сервер недоступен — проверь настройки")
            QMessageBox.warning(
                self,
                "Нет подключения",
                "Не удалось подключиться к серверу.\n"
                "Открой Настройки и укажи правильный IP-адрес.",
            )

    def _load_records(self):
        try:
            self._records = api_client.get_records()
            self._fill_table()
            self.status_label.setText(f"Записей: {len(self._records)}")
        except requests.RequestException as e:
            self.status_label.setText("Ошибка загрузки")
            QMessageBox.critical(self, "Ошибка", str(e))

    def _fill_table(self):
        self.table.setRowCount(0)
        for rec in self._records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(rec["id"])))
            self.table.setItem(row, 1, QTableWidgetItem(rec["title"]))
            self.table.setItem(row, 2, QTableWidgetItem(rec["tags"]))
            created = rec["created_at"][:19].replace("T", " ")
            self.table.setItem(row, 3, QTableWidgetItem(created))

    def _selected_record(self) -> dict | None:
        rows = self.table.selectedItems()
        if not rows:
            return None
        row = self.table.currentRow()
        return self._records[row] if row < len(self._records) else None

    def _on_selection_changed(self):
        has = bool(self.table.selectedItems())
        self.btn_edit.setEnabled(has)
        self.btn_delete.setEnabled(has)

    def _on_add(self):
        dlg = RecordFormDialog(self)
        if dlg.exec():
            try:
                api_client.create_record(**dlg.get_data())
                self._load_records()
            except requests.RequestException as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def _on_edit(self):
        rec = self._selected_record()
        if not rec:
            return
        dlg = RecordFormDialog(self, record=rec)
        if dlg.exec():
            try:
                data = dlg.get_data()
                api_client.update_record(rec["id"], **data)
                self._load_records()
            except requests.RequestException as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def _on_delete(self):
        rec = self._selected_record()
        if not rec:
            return
        answer = QMessageBox.question(
            self,
            "Удалить?",
            f"Удалить запись «{rec['title']}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            try:
                api_client.delete_record(rec["id"])
                self._load_records()
            except requests.RequestException as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def _poll_usb(self):
        try:
            devices = api_client.get_usb_devices()
        except Exception:
            self.usb_label.setText("USB: —")
            return
        if not devices:
            self.usb_label.setText("USB: не подключена")
        else:
            names = ", ".join(
                f"{d.get('vendor', '')} {d.get('model', '')} ({d.get('node', '')})".strip()
                for d in devices
            )
            self.usb_label.setText(f"USB: {names}")

    def _on_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            self._check_connection()
