from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTabWidget,
)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
import api_client
from ui.settings_dialog import SettingsDialog
from ui.tags_widget import TagsWidget
from ui.history_widget import HistoryController
from ui.trends_widget import TrendsWidget
from ui.db_download_dialog import DbDownloadDialog
from ui.backups_widget import BackupsWidget

# Цвета для индикаторов статуса
_DOT_GREEN  = "background-color: #2ecc71; border-radius: 8px;"
_DOT_RED    = "background-color: #e74c3c; border-radius: 8px;"
_DOT_YELLOW = "background-color: #f39c12; border-radius: 8px;"
_DOT_GRAY   = "background-color: #95a5a6; border-radius: 8px;"

# Функция для создания иконки приложения
def _make_icon() -> QIcon:
    """Создание иконки приложения: рисование круга с буквой "R" в центре для узнаваемого образа приложения"""
    # Создание пикселя для иконки, заполнение его прозрачным цветом и рисование круга с буквой "R" в центре
    px = QPixmap(64, 64)
    # Заполнение пикселя прозрачным цветом, чтобы создать фон для иконки
    px.fill(QColor(0, 0, 0, 0))

    # Рисование круга с буквой "R" в центре пикселя для создания иконки приложения
    p = QPainter(px)
    # Включение сглаживания для более гладкого отображения круга и текста на иконке
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Установка кисти для рисования круга с цветом #2980b9 и отключение контура (pen) для круга
    p.setBrush(QColor("#2980b9"))
    # Отключение контура (pen) для круга, чтобы он был сплошным и не имел обводки
    p.setPen(Qt.PenStyle.NoPen)
    # Рисование круга с координатами (0, 0) и размером 64x64 пикселя, чтобы создать основу для иконки
    p.drawEllipse(0, 0, 64, 64)
    # Установка кисти для рисования текста с белым цветом и шрифтом Arial, размером 32 и жирным начертанием
    p.setPen(QColor("white"))

    # Установка шрифта для рисования текста на иконке: Arial, размер 32, жирное начертание
    font = QFont("Arial", 32, QFont.Weight.Bold)

    # Установка шрифта для рисования текста на иконке, чтобы буква "R" была четкой и хорошо видимой
    p.setFont(font)
    # Рисование буквы "R" в центре пикселя, используя выравнивание по центру, чтобы создать узнаваемую иконку для приложения
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "R")
    # Завершение рисования и возвращение созданной иконки для использования в главном окне приложения
    p.end()
    # Возвращение иконки из пикселя
    return QIcon(px)

# Главный класс окна приложения
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Установка заголовка окна, иконки и минимального размера,
        # а также вызов методов для построения интерфейса и проверки соединения при инициализации главного окна приложения
        self.setWindowTitle("Registrator")
        # Установка иконки окна, используя функцию _make_icon для создания иконки с буквой "R" в центре синего круга
        self.setWindowIcon(_make_icon())
        # Установка минимального размера окна 800x500 пикселей,
        # чтобы обеспечить достаточное пространство для отображения всех элементов интерфейса
        self.setMinimumSize(800, 500)
        # Вызов метода для построения пользовательского интерфейса главного окна приложения
        self._build_ui()
        # Вызов метода для проверки соединения с сервером при инициализации главного окна,
        # чтобы сразу отобразить статус подключения при запуске приложения
        self._check_connection()

    # Метод для построения пользовательского интерфейса
    def _build_ui(self):
        """Построение пользовательского интерфейса главного окна приложения"""
        # Центральный виджет и основной вертикальный лэйаут
        central = QWidget()
        # Установка центрального виджета для главного окна
        self.setCentralWidget(central)
        # Основной вертикальный лэйаут для размещения всех элементов интерфейса
        root = QVBoxLayout(central)

    # Строка статусов
        status_bar = QHBoxLayout()
        # Индикатор подключения к серверу
        self._conn_dot = QLabel()
        # Установка фиксированного размера для индикатора и начального цвета (красный - нет подключения)
        self._conn_dot.setFixedSize(16, 16)
        # Начальный стиль для индикатора (красный - нет подключения)
        self._conn_dot.setStyleSheet(_DOT_RED)
        # Метка для отображения статуса подключения
        self._conn_label = QLabel("Нет подключения")
        # Добавление индикатора строку статусов
        status_bar.addWidget(self._conn_dot)
        # Добавление метки статуса подключения в строку статусов
        status_bar.addWidget(self._conn_label)
        # Добавление отступа между статусом подключения и статусом USB
        status_bar.addSpacing(24)

    # Индикатор и статус для USB накопителя
        self._usb_dot = QLabel()
        # Установка фиксированного размера для индикатора USB и начального цвета (серый - нет данных)
        self._usb_dot.setFixedSize(16, 16)
        # Начальный стиль для индикатора USB (серый - нет данных)
        self._usb_dot.setStyleSheet(_DOT_GRAY)
        # Метка для отображения статуса USB накопителя
        self._usb_status_label = QLabel("USB Накопитель: —")
        # Добавление индикатора USB в строку статусов
        status_bar.addWidget(self._usb_dot)
        # Добавление метки статуса USB накопителя в строку статусов
        status_bar.addWidget(self._usb_status_label)

        status_bar.addSpacing(24)
        self._exp_label = QLabel("● Ожидание")
        self._exp_label.setStyleSheet("color: #888888; font-weight: bold;")
        status_bar.addWidget(self._exp_label)

        status_bar.addSpacing(24)
        self._disk_label = QLabel("💾 Free: —")
        status_bar.addWidget(self._disk_label)

        status_bar.addSpacing(24)
        self._db_label = QLabel("🗄 DB: —")
        status_bar.addWidget(self._db_label)

        btn_db_dl = QPushButton("🗄⬇")
        btn_db_dl.setFixedHeight(22)
        btn_db_dl.setToolTip("Скачать базу данных")
        btn_db_dl.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 0 6px; color: #4fc3f7; border: 1px solid #4fc3f7; border-radius: 3px; background: transparent; }"
            "QPushButton:hover { background: rgba(79,195,247,0.15); }"
        )
        btn_db_dl.clicked.connect(lambda: (dlg := DbDownloadDialog(self)) and dlg.exec())
        status_bar.addWidget(btn_db_dl)

    # Кнопка настроек подключения
        # Добавление растяжки, чтобы кнопка настроек была прижата к правому краю
        status_bar.addStretch()
        # Кнопка для открытия настроек подключения
        self.btn_settings = QPushButton("⚙")
        self.btn_settings.setFixedSize(28, 28)
        self.btn_settings.setToolTip("Настройки подключения")
        # Добавление кнопки настроек в строку статусов
        status_bar.addWidget(self.btn_settings)
        # Добавление строки статусов в основной лэйаут
        root.addLayout(status_bar)

        # Вкладки
        # Создание контроллера истории, который будет управлять данными БД и экспортами, и передача ссылки на главное окно для взаимодействия
        self._history = HistoryController(self)
        # Создание виджета вкладок и добавление вкладок для тегов, данных БД, экспорта и трендов
        tabs = QTabWidget()
        # Добавление вкладки для OPC UA тегов
        tabs.addTab(TagsWidget(), "Данные реального времени")
        tabs.addTab(TrendsWidget(), "Тренды")
        tabs.addTab(self._history.data_widget, "Данные БД")
        tabs.addTab(self._history.exports_widget, "Экспорты")
        tabs.addTab(BackupsWidget(), "Бэкапы")
        # Добавление виджета вкладок в основной лэйаут
        root.addWidget(tabs)

        # Таймер проверки соединения
        self._conn_timer = QTimer(self)
        # Подключение сигнала таймера к методу проверки соединения
        self._conn_timer.timeout.connect(self._check_connection)
        # Запуск таймера с интервалом 5000 миллисекунд (5 секунд)
        self._conn_timer.start(5000)

        # USB polling timer
        self._usb_timer = QTimer(self)
        # Подключение сигнала таймера к методу опроса USB устройств
        self._usb_timer.timeout.connect(self._poll_usb)
        # Запуск таймера с интервалом 3000 миллисекунд (3 секунды)
        self._usb_timer.start(3000)
        # Немедленный вызов метода опроса USB устройств при запуске приложения,
        # чтобы сразу отобразить статус USB накопителя
        self._poll_usb()

        # Experiment status polling timer
        self._exp_timer = QTimer(self)
        self._exp_timer.timeout.connect(self._poll_experiment)
        self._exp_timer.start(2000)
        self._poll_experiment()

        # Disk space polling timer
        self._disk_timer = QTimer(self)
        self._disk_timer.timeout.connect(self._poll_disk)
        self._disk_timer.start(30000)
        self._poll_disk()

        # Подключение сигнала нажатия кнопки настроек к методу открытия диалогового окна настроек
        self.btn_settings.clicked.connect(self._on_settings)


    #  Метод для проверки соединения с сервером и обновления статуса подключения
    def _check_connection(self):
        """
        Проверка соединения с сервером и обновление статуса подключения: 
        изменение цвета индикатора и текста статуса в зависимости от доступности сервера
        """
        # Если сервер доступен
        if api_client.health_check():
            # Установить зеленый цвет индикатора
            self._conn_dot.setStyleSheet(_DOT_GREEN)
            # Обновление текста статуса подключения на "Подключено к серверу"
            self._conn_label.setText("Подключено к серверу")
        else: # Если сервер недоступен
            # Установить красный цвет индикатора
            self._conn_dot.setStyleSheet(_DOT_RED)
            # Обновление текста статуса подключения на "Сервер недоступен"
            self._conn_label.setText("Сервер недоступен")

    # Метод для опроса USB устройств и обновления статуса USB накопителя
    def _poll_experiment(self):
        try:
            tags = api_client.get_tags()
        except Exception:
            return
        tag_map = {t["tag_name"]: t["value"] for t in tags}
        def _bool(name):
            return str(tag_map.get(name, "False")).lower() in ("true", "1")
        in_process = _bool("inProcess")
        ended      = _bool("End")
        if in_process:
            self._exp_label.setText("● Идёт испытание")
            self._exp_label.setStyleSheet("color: #2ecc71; font-weight: bold;")
        elif ended:
            self._exp_label.setText("● Испытание окончено")
            self._exp_label.setStyleSheet("color: #e67e22; font-weight: bold;")
        else:
            self._exp_label.setText("● Ожидание испытания")
            self._exp_label.setStyleSheet("color: #888888; font-weight: bold;")

    def _poll_usb(self):
        """
        Опрос USB устройств и обновление статуса USB накопителя:
        получение данных с сервера и отображение информации о подключенных устройствах и статусе экспорта
        """
        # Попытка получения данных о USB устройствах и статусе экспорта с сервера через API клиента
        try:
            # Получение списка подключенных USB устройств и статуса экспорта с сервера через API клиента
            devices = api_client.get_usb_devices()
            # Получение статуса экспорта USB накопителя с сервера через API клиента
            export_status = api_client.get_usb_export_status()
        # Если при получении данных произошла ошибка (например, сервер недоступен), установить серый цвет индикатора и текст статуса на "—"
        except Exception:
            # Установить серый цвет индикатора USB, чтобы показать, что данные недоступны
            self._usb_dot.setStyleSheet(_DOT_GRAY)
            # Обновление текста статуса USB накопителя на "USB Накопитель: —", чтобы показать, что данные недоступны
            self._usb_status_label.setText("USB Накопитель: —")
            return

        # Словари для отображения текста статуса и цвета индикатора в зависимости от статуса экспорта
        _STATUS_LABELS = {
            "idle":    "",
            "waiting": " | Ожидает монтирования...",
            "writing": " | Записывает...",
            "done":    " | Готов",
            "error":   " | Ошибка записи",
        }
        # Словарь для отображения цвета индикатора в зависимости от статуса экспорта
        _STATUS_DOTS = {
            "idle":    _DOT_GREEN,
            "waiting": _DOT_YELLOW,
            "writing": _DOT_YELLOW,
            "done":    _DOT_GREEN,
            "error":   _DOT_RED,
        }
        # Получение текста статуса для отображения в зависимости от статуса экспорта, используя словарь _STATUS_LABELS
        status_text = _STATUS_LABELS.get(export_status, "")

        # Если нет подключенных устройств, установить серый цвет индикатора и текст статуса на "USB Накопитель: Не подключен"
        if not devices:
            # Установить серый цвет индикатора USB, чтобы показать, что нет подключенных устройств
            self._usb_dot.setStyleSheet(_DOT_GRAY)
            # Обновление текста статуса USB накопителя на "USB Накопитель: Не подключен", чтобы показать, что нет подключенных устройств
            self._usb_status_label.setText("USB Накопитель: Не подключен")
        else: 
            # Если есть подключенные устройства, создать строку с именами устройств и обновить цвет индикатора 
            # и текст статуса в зависимости от статуса экспорта
            names = ", ".join(
                f"{d.get('vendor', '')} {d.get('model', '')} ({d.get('node', '')})".strip()
                for d in devices
            )
            # Установить цвет индикатора USB в зависимости от статуса экспорта, используя словарь _STATUS_DOTS
            self._usb_dot.setStyleSheet(_STATUS_DOTS.get(export_status, _DOT_GREEN))
            # Обновление текста статуса USB накопителя на "USB Накопитель: {имена устройств}{текст статуса}",
            # чтобы показать информацию о подключенных устройствах и статусе экспорта
            self._usb_status_label.setText(f"USB Накопитель: {names}{status_text}")


    def _poll_disk(self):
        status = api_client.get_disk_status()
        if status is None:
            self._disk_label.setText("💾 Свободно: —")
            self._disk_label.setStyleSheet("")
            self._db_label.setText("🗄 ДБ: —")
            self._db_label.setStyleSheet("")
            return
        free = status["free_gb"]
        db_mb = status.get("db_mb", 0)
        self._disk_label.setText(f"💾 Свободно: {free} GB")
        if free > 20:
            self._disk_label.setStyleSheet("color: #2ecc71;")
        elif free > 10:
            self._disk_label.setStyleSheet("color: #f39c12;")
        else:
            self._disk_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        if db_mb >= 1024:
            db_text = f"🗄 ДБ: {round(db_mb / 1024, 1)} GB"
        else:
            db_text = f"🗄 ДБ: {db_mb} MB"
        if db_mb >= 102400:       # > 100 GB
            db_color = "#e74c3c"
        elif db_mb >= 40960:      # 40–100 GB
            db_color = "#f39c12"
        else:                     # < 40 GB
            db_color = "#2ecc71"
        self._db_label.setText(db_text)
        self._db_label.setStyleSheet(f"color: {db_color};")

    # Метод для обработки нажатия кнопки настроек подключения
    def _on_settings(self):
        """
        Обработка нажатия кнопки настроек подключения: открытие диалогового окна настроек
        и проверка соединения после его закрытия
        """
        # Создание и отображение диалогового окна настроек подключения
        dlg = SettingsDialog(self)
        # Вызов exec() для отображения диалогового окна и ожидания его закрытия
        dlg.exec()
        # После закрытия диалогового окна настроек, вызов метода проверки соединения для обновления статуса подключения
        self._check_connection()
