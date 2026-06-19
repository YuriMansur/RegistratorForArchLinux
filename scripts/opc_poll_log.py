"""
opc_poll_log.py — журналирование опроса OPC-тегов с сервера-регистратора.

Периодически дёргает GET /tags/live (живые значения из памяти сервера, которые
наполняет OPC UA воркер) и пишет каждую выборку в консоль и в лог-файл с меткой
времени. Удобно наблюдать за опросом ПЛК и ловить «залипшие»/пропавшие теги и
обрывы связи.

Запуск:
    python opc_poll_log.py [host] [интервал_сек]
Примеры:
    python opc_poll_log.py                      # 192.168.10.222, раз в 1с
    python opc_poll_log.py 192.168.100.100      # через второй порт сервера
    python opc_poll_log.py 192.168.10.222 0.5   # каждые 0.5с
Остановка — Ctrl+C.
"""
# sys — чтение CLI-аргументов и код возврата.
import sys
# time — пауза между опросами.
import time
# datetime — метки времени в логе и имя лог-файла.
from datetime import datetime
# Path — путь к папке логов рядом со скриптом.
from pathlib import Path

# requests — HTTP-клиент к серверу (тот же, что в client/).
import requests

# Хост сервера. По умолчанию основной адрес (.10); для второго порта передать
# 192.168.100.100 первым аргументом.
HOST = sys.argv[1] if len(sys.argv) >= 2 and sys.argv[1].strip() else "192.168.10.222"
# Интервал опроса в секундах (второй аргумент). По умолчанию 1с.
try:
    INTERVAL = float(sys.argv[2]) if len(sys.argv) >= 3 and sys.argv[2].strip() else 1.0
except ValueError:
    INTERVAL = 1.0

# Порт FastAPI-сервера и эндпоинт живых тегов.
PORT = 8000
URL = f"http://{HOST}:{PORT}/tags/live"
# Таймаут одного запроса, сек — чтобы скрипт не зависал при недоступном сервере.
TIMEOUT = 3

# Папка и файл лога: scripts/logs/opc_poll_<дата>.log рядом со скриптом.
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / f"opc_poll_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"


def _emit(line: str, fh) -> None:
    """Вывести строку в консоль и дописать её в лог-файл (с флашем — чтобы лог
    был актуален, даже если скрипт прервут)."""
    print(line, flush=True)
    fh.write(line + "\n")
    fh.flush()


def main() -> int:
    # Шапка лога: что и куда опрашиваем.
    with open(LOG_PATH, "w", encoding="utf-8") as fh:
        _emit(f"# OPC poll log | {URL} | интервал {INTERVAL}s | "
              f"старт {datetime.now():%Y-%m-%d %H:%M:%S}", fh)
        _emit(f"# файл лога: {LOG_PATH}", fh)
        _emit(f"# остановка — Ctrl+C", fh)

        # Текущее состояние связи — чтобы логировать «потеряна/восстановлена» один раз,
        # а не на каждой итерации.
        was_ok: bool | None = None

        while True:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                r = requests.get(URL, timeout=TIMEOUT)
                r.raise_for_status()
                tags = r.json()
                # Связь только что восстановилась — отметим в логе.
                if was_ok is False:
                    _emit(f"{ts} | === СВЯЗЬ ВОССТАНОВЛЕНА ===", fh)
                was_ok = True

                if not tags:
                    _emit(f"{ts} | (нет живых тегов — OPC ещё не отдал данные)", fh)
                else:
                    # Стабильный порядок по имени тега; значение печатаем как есть
                    # (массивы вида "[1.0, 2.0]" тоже корректно лягут строкой).
                    parts = "  ".join(
                        f"{t['tag_name']}={t['value']}"
                        for t in sorted(tags, key=lambda x: x["tag_name"])
                    )
                    _emit(f"{ts} | {parts}", fh)

            except requests.RequestException as e:
                # Обрыв/таймаут — логируем один раз на переходе в «потеряна».
                if was_ok is not False:
                    _emit(f"{ts} | !!! СВЯЗЬ ПОТЕРЯНА: {e}", fh)
                was_ok = False

            # Пауза до следующего опроса.
            time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Тихий выход по Ctrl+C — без трейсбека.
        print("\nОстановлено пользователем.")
