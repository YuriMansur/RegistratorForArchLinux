# sys — для передачи аргументов командной строки в QApplication и завершения процесса.
import sys
# QApplication — главный объект Qt-приложения, управляет event loop и виджетами.
from PyQt6.QtWidgets import QApplication
# QSurfaceFormat — настройки рендеринга OpenGL для графиков pyqtgraph.
from PyQt6.QtGui import QSurfaceFormat
# MainWindow — главное окно приложения с вкладками и статусной строкой.
from ui.main_window import MainWindow

if __name__ == "__main__":
    # Настраиваем OpenGL до создания QApplication — после уже нельзя изменить.
    fmt = QSurfaceFormat()
    # OpenGL — аппаратное ускорение для плавной отрисовки графиков pyqtgraph.
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    # SwapInterval=0 — отключаем VSync, графики обновляются без задержки монитора.
    fmt.setSwapInterval(0)
    # Core Profile — современный OpenGL без устаревшего API.
    QSurfaceFormat.setDefaultFormat(fmt)

    # Создаём объект приложения Qt — должен быть создан до любых виджетов.
    app = QApplication(sys.argv)
    # Fusion — кроссплатформенный стиль, хорошо выглядит на Windows с тёмной темой.
    app.setStyle("Fusion")
    # Создаём главное окно — инициализирует все вкладки и таймеры.
    window = MainWindow()
    # Начальный размер окна — достаточно для отображения всех вкладок без прокрутки.
    window.resize(1200, 650)
    # Показываем окно на экране.
    window.show()
    # Запускаем event loop Qt — блокирует выполнение до закрытия окна.
    # sys.exit() передаёт код возврата из app.exec() в операционную систему.
    sys.exit(app.exec())
