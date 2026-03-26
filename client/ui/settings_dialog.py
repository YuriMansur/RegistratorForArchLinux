from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QSpinBox,
    QDialogButtonBox, QVBoxLayout, QLabel,
)
from config import load_config, save_config


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки подключения")
        self.setMinimumWidth(320)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Укажи IP-адрес Linux-сервера в локальной сети:"))

        form = QFormLayout()
        self.host_edit = QLineEdit()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        form.addRow("IP-адрес:", self.host_edit)
        form.addRow("Порт:", self.port_spin)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self):
        cfg = load_config()
        self.host_edit.setText(cfg["host"])
        self.port_spin.setValue(cfg["port"])

    def _save(self):
        save_config(self.host_edit.text().strip(), self.port_spin.value())
        self.accept()
