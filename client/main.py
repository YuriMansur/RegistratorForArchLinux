import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QSurfaceFormat
from ui.main_window import MainWindow

if __name__ == "__main__":
    # Настройка формата поверхности для отключения VSync и максимальной производительности при отрисовке графиков.
    fmt = QSurfaceFormat()
    # Используем OpenGL для рендеринга, чтобы обеспечить аппаратное ускорение и более плавную отрисовку графиков.
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    # Отключаем VSync, чтобы графики обновлялись максимально быстро, без задержек, связанных с синхронизацией кадров.
    fmt.setSwapInterval(0)
    # Устанавливаем профиль Core для лучшей совместимости и производительности.
    QSurfaceFormat.setDefaultFormat(fmt)

    # Запуск приложения
    app = QApplication(sys.argv)
    # Установка стиля Fusion
    app.setStyle("Fusion")
    # Создание и отображение главного окна
    window = MainWindow()
    # Установка начального размера окна
    window.resize(1200, 650)
    # Отображение окна
    window.show()
    # Запуск главного цикла приложения
    sys.exit(app.exec())
