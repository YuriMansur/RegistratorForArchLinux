from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QMessageBox, QLabel, QTabWidget,
)
from PyQt6.QtCore import QTimer
import api_client
from ui.settings_dialog import SettingsDialog, ask_admin_password
from ui.tags_widget import TagsWidget
from ui.history_widget import HistoryWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Registrator")
        self.setMinimumSize(800, 500)
        self._build_ui()
        self._check_connection()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Toolbar
        toolbar = QHBoxLayout()
        self.btn_settings = QPushButton("Настройки")
        toolbar.addStretch()
        toolbar.addWidget(self.btn_settings)
        root.addLayout(toolbar)

        # Вкладки
        tabs = QTabWidget()
        tabs.addTab(TagsWidget(), "OPC UA теги")
        tabs.addTab(HistoryWidget(), "История БД")
        root.addWidget(tabs)

        # Status bar
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
        self.btn_settings.clicked.connect(self._on_settings)

    def _check_connection(self):
        if api_client.health_check():
            self.status_label.setText("Подключено к серверу")
        else:
            self.status_label.setText("Сервер недоступен — проверь настройки")
            QMessageBox.warning(
                self,
                "Нет подключения",
                "Не удалось подключиться к серверу.\n"
                "Открой Настройки и укажи правильный IP-адрес.",
            )

    def _poll_usb(self):
        try:
            devices = api_client.get_usb_devices()
            export_status = api_client.get_usb_export_status()
        except Exception:
            self.usb_label.setText("USB: —")
            return

        _STATUS_LABELS = {
            "idle":    "",
            "waiting": " | ожидание монтирования...",
            "writing": " | Запись...",
            "done":    " | Готово",
            "error":   " | Ошибка записи",
        }
        status_text = _STATUS_LABELS.get(export_status, "")

        if not devices:
            self.usb_label.setText("USB: не подключена")
        else:
            names = ", ".join(
                f"{d.get('vendor', '')} {d.get('model', '')} ({d.get('node', '')})".strip()
                for d in devices
            )
            self.usb_label.setText(f"USB: {names}{status_text}")

    def _on_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()
        self._check_connection()
