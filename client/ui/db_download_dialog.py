"""Скачивание БД напрямую через SFTP (paramiko)."""
from pathlib import Path
from datetime import datetime

import paramiko
from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel,
    QProgressBar, QFileDialog, QMessageBox,
)

from config import load_config

_SSH_KEY  = str(Path.home() / ".ssh" / "registrator_key")
_SSH_USER = "user"
_SSH_PORT = 22
_DB_PATH  = "/home/user/registrator.db"


class _SftpWorker(QThread):
    progress = pyqtSignal(float)
    total    = pyqtSignal(float)
    done     = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, host: str, dest: str):
        super().__init__()
        self._host = host
        self._dest = dest

    def run(self):
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(self._host, port=_SSH_PORT, username=_SSH_USER,
                           key_filename=_SSH_KEY, timeout=10)
            sftp = client.open_sftp()
            size = sftp.stat(_DB_PATH).st_size
            self.total.emit(size / 1024 / 1024)

            def _cb(transferred, total):
                self.progress.emit(transferred / 1024 / 1024)

            sftp.get(_DB_PATH, self._dest, callback=_cb)
            sftp.close()
            client.close()
            self.done.emit(self._dest)
        except Exception as e:
            self.error.emit(str(e))


class _ProgressDialog(QDialog):
    def __init__(self, host: str, save_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Скачать БД")
        self.setMinimumWidth(400)
        self._total_mb = 0.0

        layout = QVBoxLayout(self)
        self._status = QLabel("Подключение...")
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setStyleSheet("""
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
        layout.addWidget(self._progress)

        self._worker = _SftpWorker(host, save_path)
        self._worker.total.connect(self._on_total)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        QTimer.singleShot(0, self._worker.start)

    def _on_total(self, total_mb: float):
        self._total_mb = total_mb
        self._progress.setRange(0, int(total_mb * 10))
        self._status.setText(f"Скачивание... 0.0 / {total_mb:.1f} MB")

    def _on_progress(self, received_mb: float):
        self._progress.setValue(int(received_mb * 10))
        if self._total_mb > 0:
            self._status.setText(f"Скачивание... {received_mb:.1f} / {self._total_mb:.1f} MB")
        else:
            self._status.setText(f"Скачивание... {received_mb:.1f} MB")

    def _on_done(self, path: str):
        self._progress.setValue(self._progress.maximum())
        QMessageBox.information(self, "Готово", f"БД сохранена:\n{path}")
        self.accept()

    def _on_error(self, msg: str):
        QMessageBox.warning(self, "Ошибка", f"Не удалось скачать:\n{msg}")
        self.reject()


def DbDownloadDialog(parent=None):
    """Открывает файловый диалог, затем диалог прогресса."""
    default_name = f"registrator_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.db"
    save_path, _ = QFileDialog.getSaveFileName(
        parent, "Сохранить БД", default_name, "SQLite DB (*.db)"
    )
    if not save_path:
        return None
    cfg = load_config()
    host = cfg.get("host", "192.168.10.222")
    return _ProgressDialog(host, save_path, parent)
