r"""
build_app.py — сборка клиентского приложения в .exe через PyInstaller (one-folder).

Шаги:
  1) генерирует app_icon.ico из того же дизайна, что иконка окна (синий круг + «R»);
  2) запускает PyInstaller: оконный режим, имя Registrator, эта иконка.

Запуск:
    client\.venv\Scripts\python.exe client\build_app.py
Результат:
    client\dist\Registrator\Registrator.exe   (папку переносить целиком)
"""
# subprocess — вызов PyInstaller.
import subprocess
# sys — путь к текущему python (для `-m PyInstaller`).
import sys
# Path — пути к файлам сборки.
from pathlib import Path

# Папка client/ — корень сборки (тут main.py и пакеты ui/, config.py и т.д.).
HERE = Path(__file__).resolve().parent
# Куда положить сгенерированную иконку.
ICON = HERE / "app_icon.ico"


def make_icon() -> None:
    """Сгенерировать app_icon.ico тем же рисунком, что иконка окна
    (см. _make_icon в ui/main_window.py): синий круг #2980b9 + белая жирная «R».
    Рисуем через Pillow (без Qt/QApplication — работает headless, при сборке).
    Делаем многоразмерный .ico (16…256) — чёткий и в трее, и на ярлыке."""
    from PIL import Image, ImageDraw, ImageFont

    SIZE = 256
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))  # прозрачный фон
    d = ImageDraw.Draw(img)
    # Синий круг #2980b9 на всю площадь.
    d.ellipse([0, 0, SIZE - 1, SIZE - 1], fill=(0x29, 0x80, 0xB9, 255))

    # Жирный Arial (как в иконке окна). Фоллбеки на случай отсутствия шрифта.
    font = None
    for name in ("arialbd.ttf", "Arialbd.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(name, int(SIZE * 0.6))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    # Центрируем букву «R» по реальным границам глифа.
    text = "R"
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(((SIZE - tw) / 2 - box[0], (SIZE - th) / 2 - box[1]),
           text, fill="white", font=font)

    img.save(ICON, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                          (64, 64), (128, 128), (256, 256)])
    print(f"[icon] {ICON}")


def build() -> None:
    """Запустить PyInstaller. one-folder, оконный режим, с нашей иконкой."""
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",            # не спрашивать про перезапись dist/
        "--clean",                # чистая сборка (без старого кэша)
        "--windowed",             # GUI: без чёрного окна консоли
        "--name", "Registrator",
        "--icon", str(ICON),
        "--distpath", str(HERE / "dist"),
        "--workpath", str(HERE / "build"),
        "--specpath", str(HERE),
        str(HERE / "main.py"),
    ]
    # cwd=client/ — чтобы PyInstaller видел пакеты ui/, config.py, api_client.py, signals.py.
    subprocess.run(args, cwd=str(HERE), check=True)
    print(f"\n[done] {HERE / 'dist' / 'Registrator' / 'Registrator.exe'}")


if __name__ == "__main__":
    make_icon()
    build()
