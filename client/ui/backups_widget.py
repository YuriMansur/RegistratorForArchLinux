"""Вкладка скачивания бэкапов через SFTP."""
from pathlib import Path

import paramiko
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt, QObject
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QDialog,
)

from config import load_config

_SSH_KEY  = str(Path.home() / ".ssh" / "registrator_key")
_SSH_USER = "user"
_SSH_PORT = 22

_DB_BACKUPS_DIR  = "/home/user/registrator_backups"
_SYS_BACKUPS_DIR = "/home/user/system_backups"


class _ListWorker(QThread):
    done  = pyqtSignal(list, list)  # db_files, sys_files
    error = pyqtSignal(str)

    def __init__(self, host: str):
        super().__init__()
        self._host = host

    def run(self):
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(self._host, port=_SSH_PORT, username=_SSH_USER,
                           key_filename=_SSH_KEY, timeout=10)
            sftp = client.open_sftp()

            def _list(path):
                try:
                    attrs = sftp.listdir_attr(path)
                    return sorted(
                        [{"name": a.filename, "size": a.st_size, "path": f"{path}/{a.filename}"}
                         for a in attrs],
                        key=lambda x: x["name"], reverse=True
                    )
                except Exception:
                    return []

            db_files  = _list(_DB_BACKUPS_DIR)
            sys_files = _list(_SYS_BACKUPS_DIR)
            sftp.close()
            client.close()
            self.done.emit(db_files, sys_files)
        except Exception as e:
            self.error.emit(str(e))


class _DownloadWorker(QThread):
    progress = pyqtSignal(float)
    total    = pyqtSignal(float)
    done     = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, host: str, remote: str, local: str):
        super().__init__()
        self._host   = host
        self._remote = remote
        self._local  = local

    def run(self):
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(self._host, port=_SSH_PORT, username=_SSH_USER,
                           key_filename=_SSH_KEY, timeout=10)
            sftp = client.open_sftp()
            size = sftp.stat(self._remote).st_size
            self.total.emit(size / 1024 / 1024)

            def _cb(transferred, _total):
                self.progress.emit(transferred / 1024 / 1024)

            sftp.get(self._remote, self._local, callback=_cb)
            sftp.close()
            client.close()
            self.done.emit(self._local)
        except Exception as e:
            self.error.emit(str(e))


def _fmt_size(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / 1024**3:.1f} GB"
    return f"{size_bytes / 1024**2:.1f} MB"


class _ProgressDialog(QDialog):
    def __init__(self, host: str, remote: str, local: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Скачивание")
        self.setMinimumWidth(420)
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

        self._worker = _DownloadWorker(host, remote, local)
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
        label = f"Скачивание... {received_mb:.1f} / {self._total_mb:.1f} MB" if self._total_mb > 0 \
            else f"Скачивание... {received_mb:.1f} MB"
        self._status.setText(label)

    def _on_done(self, path: str):
        self._progress.setValue(self._progress.maximum())
        QMessageBox.information(self, "Готово", f"Файл сохранён:\n{path}")
        self.accept()

    def _on_error(self, msg: str):
        QMessageBox.warning(self, "Ошибка", f"Не удалось скачать:\n{msg}")
        self.reject()


class BackupsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._db_files:  list[dict] = []
        self._sys_files: list[dict] = []
        self._list_worker: _ListWorker | None = None
        self._setup_ui()
        self._refresh()
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._refresh)
        self._auto_timer.start(30_000)  # обновление каждые 30 секунд

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Заголовок + кнопка обновить + кнопка скачать
        top = QHBoxLayout()
        top.addWidget(QLabel("Бэкапы на сервере"))
        top.addStretch()
        self._btn_download = QPushButton("⬇ Скачать")
        self._btn_download.setStyleSheet(
            "QPushButton { color: #4fc3f7; border: 1px solid #4fc3f7; border-radius: 3px; background: transparent; padding: 2px 10px; font-weight: bold; }"
            "QPushButton:hover { background: rgba(79,195,247,0.15); }"
            "QPushButton:disabled { color: #555; border-color: #555; }"
        )
        self._btn_download.clicked.connect(self._download)
        top.addWidget(self._btn_download)
        root.addLayout(top)

        # БД бэкапы
        root.addWidget(QLabel("🗄 Бэкапы БД:"))
        self._db_list = QListWidget()
        self._db_list.setMaximumHeight(180)
        root.addWidget(self._db_list)

        # Системные бэкапы
        root.addWidget(QLabel("💿 Системные бэкапы:"))
        self._sys_list = QListWidget()
        self._sys_list.setMaximumHeight(180)
        root.addWidget(self._sys_list)

        root.addStretch()

        self._status = QLabel("")
        self._status.setStyleSheet("color: #888;")
        root.addWidget(self._status)

    def _refresh(self):
        cfg = load_config()
        host = cfg.get("host", "192.168.10.222")
        self._status.setText("Загрузка списка...")
        self._list_worker = _ListWorker(host)
        self._list_worker.done.connect(self._on_list)
        self._list_worker.error.connect(self._on_list_error)
        self._list_worker.start()

    def _on_list(self, db_files: list, sys_files: list):
        self._db_files  = db_files
        self._sys_files = sys_files
        self._status.setText("")

        self._db_list.clear()
        for f in db_files:
            item = QListWidgetItem(f"  {f['name']}   ({_fmt_size(f['size'])})")
            item.setData(Qt.ItemDataRole.UserRole, f)
            self._db_list.addItem(item)

        self._sys_list.clear()
        for f in sys_files:
            item = QListWidgetItem(f"  {f['name']}   ({_fmt_size(f['size'])})")
            item.setData(Qt.ItemDataRole.UserRole, f)
            self._sys_list.addItem(item)

        if not db_files and not sys_files:
            self._status.setText("Бэкапы не найдены")

    def _on_list_error(self, msg: str):
        self._status.setText(f"Ошибка: {msg}")

    def _download(self):
        # Определяем выбранный элемент из любого из двух списков
        item = self._db_list.currentItem() or self._sys_list.currentItem()
        if not item:
            QMessageBox.information(self, "Выбор", "Выберите файл для скачивания.")
            return

        f = item.data(Qt.ItemDataRole.UserRole)
        ext_filter = "GZ архив (*.gz)" if f["name"].endswith(".gz") else "FSA архив (*.fsa)" if f["name"].endswith(".fsa") else "Все файлы (*)"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить файл", f["name"], ext_filter
        )
        if not save_path:
            return

        cfg = load_config()
        host = cfg.get("host", "192.168.10.222")
        dlg = _ProgressDialog(host, f["path"], save_path, self)
        dlg.exec()
