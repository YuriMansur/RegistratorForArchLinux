from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QTextEdit,
    QDialogButtonBox, QVBoxLayout, QLabel,
)


class RecordFormDialog(QDialog):
    """Диалог для создания или редактирования записи."""

    def __init__(self, parent=None, record: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Редактировать запись" if record else "Новая запись")
        self.setMinimumWidth(400)
        self._build_ui()
        if record:
            self._fill(record)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.title_edit = QLineEdit()
        self.desc_edit = QTextEdit()
        self.desc_edit.setFixedHeight(100)
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("через запятую: тег1, тег2")

        form.addRow("Заголовок *:", self.title_edit)
        form.addRow("Описание:", self.desc_edit)
        form.addRow("Теги:", self.tags_edit)
        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red")
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _fill(self, record: dict):
        self.title_edit.setText(record.get("title", ""))
        self.desc_edit.setPlainText(record.get("description", ""))
        self.tags_edit.setText(record.get("tags", ""))

    def _validate(self):
        if not self.title_edit.text().strip():
            self.error_label.setText("Заголовок обязателен")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "title": self.title_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "tags": self.tags_edit.text().strip(),
        }
