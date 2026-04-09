from datetime import timezone
import datetime as _dt

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QColorDialog, QFrame, QComboBox,
    QLabel, QScrollArea,
)
from PyQt6.QtCore import Qt, QDateTime, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QColor

import api_client
from ui.datetime_picker import DateTimePicker

pg.setConfigOptions(antialias=True, useOpenGL=True)


class _LiveWorker(QThread):
    result = pyqtSignal(list, float)  # (tags, timestamp)

    def run(self):
        try:
            tags = api_client.get_tags()
            now = _dt.datetime.now().timestamp()
            self.result.emit(tags, now)
        except Exception:
            pass


_STREAM_CHUNK = 5000   # кол-во строк между обновлениями графика


class _LoadWorker(QThread):
    chunk = pyqtSignal(list)   # промежуточное обновление
    done  = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, from_dt, to_dt, tags):
        super().__init__()
        self._from_dt = from_dt
        self._to_dt   = to_dt
        self._tags    = tags

    def run(self):
        import json as _json
        try:
            rows = api_client.stream_history_range(self._from_dt, self._to_dt, self._tags)
            buf = []
            for row in rows:
                buf.append(row)
                if len(buf) >= _STREAM_CHUNK:
                    self.chunk.emit(buf)
                    buf = []
            if buf:
                self.chunk.emit(buf)
            self.done.emit()
        except Exception as e:
            self.error.emit(str(e))

_COLORS = [
    "#4fc3f7", "#81c784", "#ffb74d", "#e57373",
    "#ce93d8", "#4dd0e1", "#fff176", "#a5d6a7",
    "#f48fb1", "#80cbc4", "#bcaaa4", "#ffe082",
]

_PANEL_STYLE = """
    QFrame#chPanel {
        background-color: #2b2b2b;
        border-right: 1px solid #444444;
    }
    QFrame#archPanel {
        background-color: #2b2b2b;
        border-bottom: 1px solid #444444;
    }
    QWidget#chContainer {
        background-color: #2b2b2b;
    }
    QScrollArea {
        background-color: #2b2b2b;
        border: none;
    }
    QLabel {
        color: #cccccc;
        background: transparent;
    }
    QPushButton {
        color: #cccccc;
        background-color: #3a3a3a;
        border: 1px solid #555555;
        border-radius: 3px;
        padding: 1px 6px;
    }
    QPushButton:hover {
        background-color: #484848;
    }
    QSpinBox {
        background: #3a3a3a;
        color: #cccccc;
        border: 1px solid #555555;
        border-radius: 3px;
        padding: 1px 2px;
        min-height: 20px;
    }
    QSpinBox::up-button, QSpinBox::down-button {
        background: #4a4a4a;
        border: none;
        width: 12px;
    }
    QCheckBox {
        color: #cccccc;
        background: transparent;
        spacing: 4px;
    }
    QCheckBox::indicator {
        width: 13px;
        height: 13px;
        border: 1px solid #666666;
        border-radius: 2px;
        background: #3a3a3a;
    }
    QCheckBox::indicator:checked {
        background: #666666;
        border-color: #888888;
    }
    QSlider::groove:horizontal {
        background: #4a4a4a;
        height: 4px;
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        background: #888888;
        width: 12px;
        height: 12px;
        margin: -4px 0;
        border-radius: 6px;
        border: none;
    }
    QSlider::handle:horizontal:hover {
        background: #aaaaaa;
    }
    QScrollBar:vertical {
        background: #2b2b2b;
        width: 8px;
        border: none;
    }
    QScrollBar::handle:vertical {
        background: #555555;
        border-radius: 4px;
        min-height: 20px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
"""


def _utc_to_local(utc_str: str) -> str:
    try:
        dt = _dt.datetime.fromisoformat(utc_str).replace(tzinfo=_dt.timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return utc_str


def _iso_to_local_qdt(utc_str: str) -> QDateTime:
    try:
        dt = _dt.datetime.fromisoformat(utc_str).replace(tzinfo=_dt.timezone.utc)
        local = dt.astimezone()
        return QDateTime(local.year, local.month, local.day,
                         local.hour, local.minute, local.second)
    except Exception:
        return QDateTime.currentDateTime()


def _ch_qcolor(ch: dict) -> QColor:
    return QColor(ch['color'])


_TOGGLE_STYLE = (
    "QPushButton { color:#ffffff; background:#2b2b2b; border:2px solid #888; "
    "border-radius:2px; font-size:12px; font-family:'Segoe UI Symbol'; padding:0px; }"
    "QPushButton:checked { border:2px solid #ffffff; }"
)

_CTRL_BTN_STYLE = (
    "QPushButton { color:#ffffff; background:#505050; border:2px solid #dddddd; "
    "border-radius:2px; font-size:12px; font-family:'Segoe UI Symbol'; padding:0px; }"
    "QPushButton:checked { background:#707070; border:2px solid #ffffff; }"
    "QPushButton:hover { background:#606060; border:2px solid #ffffff; }"
)


class _TimeAxisItem(pg.AxisItem):
    """Ось X с человекочитаемым временем."""

    def tickStrings(self, values, scale, spacing):
        result = []
        for v in values:
            try:
                dt = _dt.datetime.fromtimestamp(v)
                if spacing >= 86400:
                    result.append(dt.strftime("%d.%m\n%H:%M"))
                elif spacing >= 3600:
                    result.append(dt.strftime("%H:%M"))
                elif spacing >= 1:
                    result.append(dt.strftime("%H:%M:%S"))
                else:
                    ms = dt.microsecond // 1000
                    result.append(dt.strftime("%H:%M:%S.") + f"{ms:03d}")
            except (OSError, ValueError, OverflowError):
                result.append("")
        return result


class _CheckoutCombo(QComboBox):
    """QComboBox, который обновляет список испытаний перед открытием попапа."""
    def __init__(self, refresh_fn, parent=None):
        super().__init__(parent)
        self._refresh_fn = refresh_fn

    def showPopup(self):
        self._refresh_fn()
        super().showPopup()


class TrendsWidget(QWidget):
    _PRESET_ON  = (
        "QPushButton { background-color: #1a8fe3; color: white; "
        "font-weight: bold; border-radius: 3px; border: none; }"
    )
    _PRESET_OFF = ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._channels: dict = {}   # tag_name → channel dict
        self._live_data: dict[str, tuple[list, list]] = {}
        self._live_buffer: dict[str, tuple[list, list]] = {}  # фоновый буфер, копится всегда
        self._live_paused = False
        self._live_worker: _LiveWorker | None = None
        self._live_timer = QTimer(self)
        self._live_timer.timeout.connect(self._live_tick)
        self._buf_worker: _LiveWorker | None = None
        self._buf_timer = QTimer(self)
        self._buf_timer.timeout.connect(self._buf_tick)
        self._buf_timer.start(2000)
        self._setup_ui()
        self._load_tags()
        self._load_checkouts()


    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # ── Панель архивного диапазона ────────────────────────────────────────
        arch_frame = QFrame()
        arch_frame.setObjectName("archPanel")
        arch_frame.setStyleSheet(_PANEL_STYLE)
        arch_layout = QHBoxLayout(arch_frame)
        arch_layout.setContentsMargins(8, 4, 8, 4)
        arch_layout.setSpacing(8)

        # Испытание
        arch_layout.addWidget(QLabel("Испытание:"))
        self._checkout_combo = _CheckoutCombo(self._load_checkouts)
        self._checkout_combo.setEditable(True)
        self._checkout_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._checkout_combo.setMinimumWidth(220)
        self._checkout_combo.setMaximumWidth(320)
        completer = self._checkout_combo.completer()
        if completer:
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._checkout_combo.currentIndexChanged.connect(self._on_checkout_changed)
        arch_layout.addWidget(self._checkout_combo)

        arch_layout.addSpacing(8)

        self._preset_buttons: list[QPushButton] = []

        arch_layout.addSpacing(4)

        # Поля С / По
        arch_layout.addWidget(QLabel("С:"))
        self._dt_from = DateTimePicker()
        self._dt_from.setDateTime(QDateTime.currentDateTime().addSecs(-3600))
        arch_layout.addWidget(self._dt_from)

        arch_layout.addWidget(QLabel("По:"))
        self._dt_to = DateTimePicker()
        self._dt_to.setDateTime(QDateTime.currentDateTime())
        arch_layout.addWidget(self._dt_to)

        self.btn_load = QPushButton("Построить")
        self.btn_load.clicked.connect(self._load_archive)
        arch_layout.addWidget(self.btn_load)

        _mode_btn_style = (
            "QPushButton { color: #aaaaaa; background: #2b2b2b; border: 1px solid #555; border-radius: 3px; padding: 2px 10px; font-weight: bold; }"
            "QPushButton:checked { color: #ffffff; background: #1e7e34; border: 1px solid #28a745; }"
            "QPushButton:hover { background: #3a3a3a; }"
            "QPushButton:checked:hover { background: #218838; }"
        )
        self._btn_archive = QPushButton("Архив")
        self._btn_archive.setCheckable(True)
        self._btn_archive.setChecked(True)
        self._btn_archive.setStyleSheet(_mode_btn_style)
        self._btn_archive.clicked.connect(lambda: self._set_mode(False))
        arch_layout.addWidget(self._btn_archive)

        self._btn_live = QPushButton("● Live")
        self._btn_live.setCheckable(True)
        self._btn_live.setStyleSheet(_mode_btn_style)
        self._btn_live.clicked.connect(lambda: self._set_mode(True))
        arch_layout.addWidget(self._btn_live)

        arch_layout.addStretch()
        root.addWidget(arch_frame)

    # Основной ряд: панель каналов слева + график справа
        main_row = QHBoxLayout()
        main_row.setSpacing(0)
        root.addLayout(main_row, 1)

    # Панель каналов
        ch_frame = QFrame()
        self._ch_frame = ch_frame
        # Установка имени объекта для панели каналов
        ch_frame.setObjectName("chPanel")
        # Применение стиля к панели каналов
        ch_frame.setStyleSheet(_PANEL_STYLE)
        # Установка политики размера для панели каналов
        # Создание вертикального лэйаута
        ch_outer = QVBoxLayout(ch_frame)
        # Установка отступов для вертикального лэйаута панели каналов
        ch_outer.setContentsMargins(3, 2, 3, 2)
        # Установка расстояния между элементами внутри вертикального лэйаута
        ch_outer.setSpacing(1)

    # Строка управления над списком
        ctrl_row = QHBoxLayout()
        # Стиль строки управления под списком каналов
        ctrl_row.setSpacing(2)
        # Установка отступов для строки управления
        ctrl_row.setContentsMargins(0, 0, 0, 0)
        # Создание кнопок строки управления
        btn_points = QPushButton("Показать точки")
        btn_points.setCheckable(True)
        btn_points.toggled.connect(self._set_all_points)
        btn_points.toggled.connect(lambda checked: btn_points.setText("Скрыть точки" if checked else "Показать точки"))
        ctrl_row.addWidget(btn_points)
        # Добавление растяжителя в строку управления для выравнивания кнопок по левому краю и заполнения оставшегося пространства 
        ctrl_row.addStretch()
        # Добавление строки управления над списком каналов в основной вертикальный лэйаут панели каналов
        ch_outer.addLayout(ctrl_row)
        # Добавление панели каналов в основной ряд интерфейса с фиксированной шириной
        main_row.addWidget(ch_frame)

    # Заголовок панели каналов
        self._ch_scroll = QScrollArea()
        self._ch_scroll.setWidgetResizable(True)
        self._ch_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._ch_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._ch_scroll.setStyleSheet("""
            QScrollBar:vertical {
                width: 6px;
                background: transparent;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 0, 0, 0);
                border-radius: 3px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(120, 120, 120, 200);
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
                height: 0px;
                width: 0px;
            }
        """)

    # Контейнер для каналов внутри области прокрутки
        self._ch_container = QWidget()
        self._ch_container.setObjectName("chContainer")
        self._ch_container.setStyleSheet("QWidget#chContainer { background-color: #2b2b2b; }")
        self._ch_layout = QVBoxLayout(self._ch_container)
        self._ch_layout.setContentsMargins(0, 0, 0, 0)
        self._ch_layout.setSpacing(0)
        self._ch_layout.addStretch()

        self._ch_scroll.setWidget(self._ch_container)
        ch_outer.addWidget(self._ch_scroll)



        # График
        self._time_axis = _TimeAxisItem(orientation="bottom")
        self._plot = pg.PlotWidget(axisItems={"bottom": self._time_axis})
        self._plot.setMenuEnabled(False)
        self._plot.setBackground("#1e1e1e")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.getAxis("bottom").setPen(pg.mkPen("#555555"))
        self._plot.getAxis("left").setPen(pg.mkPen("#555555"))
        self._plot.getAxis("bottom").setTextPen(pg.mkPen("#cccccc"))
        self._plot.getAxis("left").setTextPen(pg.mkPen("#cccccc"))

        # Получение кнопки автомасштаба из графика для её скрытия
        auto_btn = self._plot.getPlotItem().autoBtn
        # Скрыть кнопку автомасштаба
        auto_btn.hide()
        # Патч для предотвращения появления кнопки автомасштаба при наведении курсора на область графика
        auto_btn.show = lambda: None

        # Добавление легенды к графику для отображения названий каналов и их цветов
        self._legend = self._plot.addLegend(offset = (10, 10))
        # Добавление графика в основной ряд интерфейса с коэффициентом растяжения
        main_row.addWidget(self._plot, 1)

        # Перекрестие
        dash = pg.mkPen(color="#888888", width=1, style=Qt.PenStyle.DashLine)
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=dash)
        self._hline = pg.InfiniteLine(angle=0,  movable=False, pen=dash)
        self._vline.setVisible(False)
        self._hline.setVisible(False)
        self._plot.addItem(self._vline, ignoreBounds=True)
        self._plot.addItem(self._hline, ignoreBounds=True)

        # Маркер по клику
        self._click_marker = pg.ScatterPlotItem(
            size    = 10,
            pen     = pg.mkPen("#cc0000", width = 2),
            brush   = pg.mkBrush(255, 80, 80, 200),
        )
        self._click_label = pg.TextItem(
            anchor=(0, 1), color="#cc0000",
            fill=pg.mkBrush(255, 230, 230, 220),
        )
        self._click_marker.setZValue(30)
        self._click_label.setZValue(30)
        self._click_marker.setVisible(False)
        self._click_label.setVisible(False)
        self._plot.addItem(self._click_marker, ignoreBounds=True)
        self._plot.addItem(self._click_label,  ignoreBounds=True)

        self._plot.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self._plot.scene().sigMouseClicked.connect(self._on_mouse_clicked)

        # колесо = масштаб Y, Ctrl+колесо = масштаб X
        _vb = self._plot.getViewBox()
        def _wheel(ev, axis=None):
            if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
                pg.ViewBox.wheelEvent(_vb, ev, axis=0)
            else:
                pg.ViewBox.wheelEvent(_vb, ev, axis=1)
        _vb.wheelEvent = _wheel

        # пауза live-скролла пока зажата мышь
        _orig_press   = self._plot.mousePressEvent
        _orig_release = self._plot.mouseReleaseEvent
        def _plot_press(ev):
            self._live_paused = True
            _orig_press(ev)
        def _plot_release(ev):
            self._live_paused = False
            _orig_release(ev)
        self._plot.mousePressEvent   = _plot_press
        self._plot.mouseReleaseEvent = _plot_release

    # ── Каналы ────────────────────────────────────────────────────────────────

    _SKIP_TAGS = {"inProcess", "End"}

    def _load_tags(self):
        try:
            tags = api_client.get_tags()
        except Exception:
            return
        color_idx = len(self._channels)
        for t in tags:
            name = t.get("tag_name", "")
            if not name or name in self._SKIP_TAGS or name in self._channels:
                continue
            self._add_channel(name, _COLORS[color_idx % len(_COLORS)])
            color_idx += 1

    def _load_checkouts(self):
        try:
            checkouts = api_client.get_checkouts()
        except Exception:
            return
        self._checkout_combo.blockSignals(True)
        prev_id = self._checkout_combo.currentData()
        self._checkout_combo.clear()
        self._checkout_combo.addItem("— Произвольный диапазон —", userData=None)
        restore_idx = 0
        for i, c in enumerate(checkouts):
            cid = c.get("id")
            started = _utc_to_local(c.get("started_at", ""))
            ended   = c.get("ended_at")
            label = f"#{cid}  {started}"
            if not ended:
                label += "  (активно)"
            self._checkout_combo.addItem(label, userData=c)
            if cid == (prev_id.get("id") if isinstance(prev_id, dict) else None):
                restore_idx = i + 1
        self._checkout_combo.setCurrentIndex(restore_idx)
        self._checkout_combo.blockSignals(False)
        self._on_checkout_changed(restore_idx)

    def _on_checkout_changed(self, _):
        checkout = self._checkout_combo.currentData()
        if checkout is None:
            # Ручной диапазон — разблокировать пикеры
            self._dt_from.setEnabled(True)
            self._dt_to.setEnabled(True)
            for b in self._preset_buttons:
                b.setEnabled(True)
            return
        # Заполнить диапазон из испытания
        started = checkout.get("started_at", "")
        ended   = checkout.get("ended_at")
        if started:
            from_qdt = _iso_to_local_qdt(started)
            self._dt_from.setDateTime(from_qdt)
        if ended:
            to_qdt = _iso_to_local_qdt(ended)
        else:
            to_qdt = QDateTime.currentDateTime()
        self._dt_to.setDateTime(to_qdt)
        self._dt_from.setEnabled(False)
        self._dt_to.setEnabled(False)
        for b in self._preset_buttons:
            b.setEnabled(False)
            b.setStyleSheet(self._PRESET_OFF)

    def _add_channel(self, name: str, color: str):
        curve = self._plot.plot(
            [], [],
            pen=pg.mkPen(color=QColor(color), width=2),
            name=name,
        )
        curve.setClipToView(True)
        self._channels[name] = {
            'curve':      curve,
            'color':      color,
            'width':      2,
            'points':     False,
            'visible':    True,
            'toggle_btn': None,
            'color_btn':  None,
        }
        row = self._make_channel_row(name)
        count = self._ch_layout.count()
        self._ch_layout.insertWidget(count - 1, row)
        self._update_panel_width()

    def _update_panel_width(self):
        max_w = 0
        layout = self._ch_layout
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget():
                max_w = max(max_w, item.widget().sizeHint().width())
        if max_w > 0:
            self._ch_frame.setFixedWidth(max_w + 24)

    def _make_channel_row(self, name: str) -> QWidget:
        ch = self._channels[name]
        row = QWidget()
        row.setFixedHeight(24)
        row.setStyleSheet("background-color: #2b2b2b;")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(3, 0, 3, 0)
        hl.setSpacing(4)

        # Кнопка выбора цвета
        color_btn = QPushButton()
        # Установка фиксированного размера для кнопки цвета канала
        color_btn.setFixedSize(16, 16)
        # Подсказка для кнопки цвета канала, чтобы пользователи понимали её назначение
        color_btn.setToolTip("Цвет линии")
        # Стиль кнопки цвета канала: фон соответствует цвету канала, скругленные углы и рамка для лучшей видимости
        color_btn.setStyleSheet(f"background-color:{ch['color']}; border-radius:2px; border:1px solid #555;")
        # При клике открывать диалог выбора цвета, передавая имя канала для идентификации
        color_btn.clicked.connect(lambda _ = False, n = name: self._pick_color(n))
        # Сохранить кнопку цвета в данных канала для обновления стиля при смене цвета
        ch['color_btn'] = color_btn

        # Название
        # 
        lbl = QLabel(name)
        lbl.setStyleSheet("color:#cccccc; font-size:12px; background:transparent;")
        lbl.setToolTip(name)

  
        hl.addWidget(color_btn)
        hl.addWidget(lbl, 1)

        return row

    def _toggle_visible(self, name: str, visible: bool):
        ch = self._channels.get(name)
        if ch is None:
            return
        ch['visible'] = visible
        ch['curve'].setVisible(visible)
        try:
            if visible:
                self._legend.addItem(ch['curve'], name)
            else:
                self._legend.removeItem(ch['curve'])
        except Exception:
            pass


    # Смена цвета канала: открытие диалога выбора цвета, обновление цвета линии, кнопки и легенды
    def _pick_color(self, name: str):
        ch = self._channels.get(name)
        if ch is None:
            return
        color = QColorDialog.getColor(QColor(ch['color']), self)
        if not color.isValid():
            return
        ch['color'] = color.name()
        ch['color_btn'].setStyleSheet(
            f"background-color:{ch['color']}; border-radius:2px; border:1px solid #555;")
        ch['curve'].setPen(pg.mkPen(color=_ch_qcolor(ch), width=ch['width']))
        try:
            self._legend.removeItem(ch['curve'])
            if ch['visible']:
                self._legend.addItem(ch['curve'], name)
        except Exception:
            pass

    def _set_width(self, name: str, width: int):
        ch = self._channels.get(name)
        if ch is None:
            return
        ch['width'] = width
        ch['curve'].setPen(pg.mkPen(color=_ch_qcolor(ch), width=width))

    def _set_points(self, name: str, checked: bool):
        ch = self._channels.get(name)
        if ch is None:
            return
        ch['points'] = checked
        ch['curve'].setSymbol('o' if checked else None)
        ch['curve'].setSymbolSize(5)
        ch['curve'].setSymbolBrush(pg.mkBrush(ch['color']) if checked else None)
        ch['curve'].setSymbolPen(pg.mkPen(None))

    def _select_all(self):
        for ch in self._channels.values():
            if not ch['visible'] and ch['toggle_btn'] is not None:
                ch['toggle_btn'].setChecked(True)

    def _select_none(self):
        for ch in self._channels.values():
            if ch['visible'] and ch['toggle_btn'] is not None:
                ch['toggle_btn'].setChecked(False)

    def _set_all_points(self, checked: bool):
        for name in self._channels:
            self._set_points(name, checked)

    # ── Live ──────────────────────────────────────────────────────────────────

    def _set_mode(self, live: bool):
        self._btn_live.setChecked(live)
        self._btn_archive.setChecked(not live)
        if live:
            self._load_tags()
            # Инициализируем live_data из накопленного буфера
            self._live_data = {
                name: (list(ts), list(vs))
                for name, (ts, vs) in self._live_buffer.items()
            }
            for name, ch in self._channels.items():
                if name in self._live_data:
                    ch['curve'].setData(*self._live_data[name])
                else:
                    ch['curve'].setData([], [])
            self._checkout_combo.setEnabled(False)
            self._dt_from.setEnabled(False)
            self._dt_to.setEnabled(False)
            for b in self._preset_buttons:
                b.setEnabled(False)
            self.btn_load.setEnabled(False)
            self._live_timer.start(2000)
            self._live_tick()
        else:
            self._live_timer.stop()
            self._checkout_combo.setEnabled(True)
            self.btn_load.setEnabled(True)
            self._on_checkout_changed(self._checkout_combo.currentIndex())
            # Восстанавливаем архивные данные
            archive = getattr(self, "_series", {})
            for name, ch in self._channels.items():
                if name in archive:
                    ch['curve'].setData(*archive[name])
                else:
                    ch['curve'].setData([], [])

    def _live_tick(self):
        if self._live_worker and self._live_worker.isRunning():
            return  # предыдущий запрос ещё не завершён
        self._live_worker = _LiveWorker(self)
        self._live_worker.result.connect(self._live_update)
        self._live_worker.start()

    def _live_update(self, tags: list, now: float):
        tag_map = {t["tag_name"]: t["value"] for t in tags}
        for name, ch in self._channels.items():
            if not ch['visible'] or name not in tag_map:
                continue
            try:
                val = float(tag_map[name])
            except (ValueError, TypeError):
                continue
            buf = self._live_data.setdefault(name, ([], []))
            buf[0].append(now)
            buf[1].append(val)
            ch['curve'].setData(buf[0], buf[1])
        if not self._live_paused:
            vb = self._plot.getViewBox()
            window = vb.viewRange()[0][1] - vb.viewRange()[0][0]
            if window < 10:
                window = 60
            self._plot.setXRange(now - window, now, padding=0)

    # ── Фоновый буфер (копится всегда, даже в режиме Архив) ──────────────────

    _BUF_MAX = 3000  # максимум точек на тег в буфере

    def _buf_tick(self):
        if self._buf_worker and self._buf_worker.isRunning():
            return
        self._buf_worker = _LiveWorker(self)
        self._buf_worker.result.connect(self._buf_update)
        self._buf_worker.start()

    def _buf_update(self, tags: list, now: float):
        tag_map = {t["tag_name"]: t["value"] for t in tags}
        for name in self._channels:
            if name not in tag_map:
                continue
            try:
                val = float(tag_map[name])
            except (ValueError, TypeError):
                continue
            buf = self._live_buffer.setdefault(name, ([], []))
            buf[0].append(now)
            buf[1].append(val)
            # Ограничиваем размер буфера
            if len(buf[0]) > self._BUF_MAX:
                del buf[0][0]
                del buf[1][0]

    # ── Архив ─────────────────────────────────────────────────────────────────

    def _select_preset(self, secs: int, active_btn: QPushButton):
        now = QDateTime.currentDateTime()
        self._dt_from.blockSignals(True)
        self._dt_to.blockSignals(True)
        self._dt_from.setDateTime(now.addSecs(-secs))
        self._dt_to.setDateTime(now)
        self._dt_from.blockSignals(False)
        self._dt_to.blockSignals(False)
        for b in self._preset_buttons:
            b.setStyleSheet(self._PRESET_ON if b is active_btn else self._PRESET_OFF)

    def _load_archive(self):
        self._load_tags()
        local_tz = _dt.datetime.now(_dt.timezone.utc).astimezone().tzinfo
        from_dt = (self._dt_from.dateTime().toPyDateTime()
                   .replace(tzinfo=local_tz).astimezone(timezone.utc))
        to_dt   = (self._dt_to.dateTime().toPyDateTime()
                   .replace(tzinfo=local_tz).astimezone(timezone.utc))

        visible_tags = [name for name, ch in self._channels.items() if ch['visible']]
        if not visible_tags:
            return

        self.btn_load.setEnabled(False)
        self.btn_load.setText("Загрузка...")
        # Сброс накопленных серий перед новой загрузкой
        self._series: dict[str, tuple[list, list]] = {}
        for ch in self._channels.values():
            ch['curve'].setData([], [])

        self._worker = _LoadWorker(from_dt, to_dt, visible_tags)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.done.connect(self._on_data_loaded)
        self._worker.error.connect(self._on_load_error)
        self._worker.finished.connect(lambda: (
            self.btn_load.setEnabled(True),
            self.btn_load.setText("Построить"),
        ))
        self._worker.start()

    def _parse_rows(self, rows: list):
        for r in rows:
            name = r.get("tag_name", "")
            if name not in self._channels:
                continue
            try:
                val = float(r.get("value", ""))
            except (ValueError, TypeError):
                continue
            t = (
                _dt.datetime.fromisoformat(r["recorded_at"])
                .replace(tzinfo=timezone.utc)
                .astimezone()
                .timestamp()
            )
            if name not in self._series:
                self._series[name] = ([], [])
            self._series[name][0].append(t)
            self._series[name][1].append(val)

    def _on_chunk(self, rows: list):
        self._parse_rows(rows)

    def _on_data_loaded(self):
        for name, ch in self._channels.items():
            if name in self._series:
                ch['curve'].setData(*self._series[name])
            else:
                ch['curve'].setData([], [])
        self._plot.getViewBox().autoRange()

    def _on_load_error(self, msg: str):
        print(f"[trends] ошибка загрузки: {msg}")
        self.btn_load.setEnabled(True)
        self.btn_load.setText("Построить")

    # ── Перекрестие и маркер по клику ─────────────────────────────────────────

    def _on_mouse_moved(self, pos):
        vb = self._plot.getViewBox()
        if not self._plot.sceneBoundingRect().contains(pos):
            self._vline.setVisible(False)
            self._hline.setVisible(False)
            return
        mp = vb.mapSceneToView(pos)
        self._vline.setPos(mp.x())
        self._hline.setPos(mp.y())
        self._vline.setVisible(True)
        self._hline.setVisible(True)

    def _on_mouse_clicked(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        pos = ev.scenePos()
        vb  = self._plot.getViewBox()
        if not self._plot.sceneBoundingRect().contains(pos):
            return
        mp = vb.mapSceneToView(pos)
        click_x = mp.x()

        # Ищем ближайшую точку по X среди видимых каналов
        best_dist = float('inf')
        best_x = click_x
        best_y = mp.y()
        best_name = ""

        for name, ch in self._channels.items():
            if not ch['visible']:
                continue
            data = ch['curve'].getData()
            if data is None or data[0] is None or len(data[0]) == 0:
                continue
            xs = np.asarray(data[0])
            ys = np.asarray(data[1])
            idx = int(np.argmin(np.abs(xs - click_x)))
            dist = abs(float(xs[idx]) - click_x)
            if dist < best_dist:
                best_dist = dist
                best_x = float(xs[idx])
                best_y = float(ys[idx])
                best_name = name

        if best_name:
            dt_str = _dt.datetime.fromtimestamp(best_x).strftime("%d.%m %H:%M:%S")
            label  = f"{best_name}\n{dt_str}  {best_y:.4g}"
            self._click_marker.setData([best_x], [best_y])
            self._click_label.setPos(best_x, best_y)
            self._click_label.setText(label)
            self._click_marker.setVisible(True)
            self._click_label.setVisible(True)
        else:
            self._click_marker.setVisible(False)
            self._click_label.setVisible(False)
