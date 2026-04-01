from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QSpinBox,
    QDialogButtonBox, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton,
)
from config import load_config, save_config

_ADMIN_LOGIN    = "root"
_ADMIN_PASSWORD = "111111"


class _AuthDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Авторизация")
        self.setMinimumWidth(280)
        layout             = QVBoxLayout(self)
        form               = QFormLayout()
        self.login_edit    = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Логин:",  self.login_edit)
        form.addRow("Пароль:", self.password_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox()
        buttons.addButton("Войти",  QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def ask_admin_password(parent=None) -> bool:
    dlg = _AuthDialog(parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False
    if dlg.login_edit.text() != _ADMIN_LOGIN or dlg.password_edit.text() != _ADMIN_PASSWORD:
        QMessageBox.warning(parent, "Ошибка", "Неверный логин или пароль.")
        return False
    return True


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки подключения")
        self.setMinimumWidth(360)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Подключение к серверу:"))

        form = QFormLayout()
        self.host_edit = QLineEdit()
        self.host_edit.setReadOnly(True)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setReadOnly(True)
        self.port_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        form.addRow("IP-адрес:", self.host_edit)
        form.addRow("Порт:",     self.port_spin)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.btn_edit = QPushButton("Изменить")
        self.btn_edit.clicked.connect(self._on_edit)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_edit)
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self):
        cfg = load_config()
        self.host_edit.setText(cfg["host"])
        self.port_spin.setValue(cfg["port"])

    def _on_edit(self):
        if not ask_admin_password(self):
            return
        self.host_edit.setReadOnly(False)
        self.port_spin.setReadOnly(False)
        self.port_spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        self.btn_edit.setText("Сохранить")
        self.btn_edit.clicked.disconnect()
        self.btn_edit.clicked.connect(self._on_save)

    def _on_save(self):
        save_config(self.host_edit.text().strip(), self.port_spin.value())
        self.host_edit.setReadOnly(True)
        self.port_spin.setReadOnly(True)
        self.port_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.btn_edit.setText("Изменить")
        self.btn_edit.clicked.disconnect()
        self.btn_edit.clicked.connect(self._on_edit)
        QMessageBox.information(self, "Сохранено", "Настройки подключения обновлены.")
