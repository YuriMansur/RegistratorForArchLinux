"""
Точка входа серверного приложения Registrator.

Архитектура:
  - FastAPI — HTTP REST API для Windows-клиента
  - OPC UA (ServerManager) — чтение данных с ПЛК по протоколу OPC UA
  - SQLite (SQLAlchemy) — хранение тегов, истории испытаний
  - USB Monitor — автоматический экспорт данных на флешку при вставке

Запуск:
  uvicorn main:app --host 0.0.0.0 --port 8000
"""

import uvicorn
import logging
import logging.handlers
import pathlib
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# SQLAlchemy engine и базовый класс моделей
from db.database import sync_engine, Base

# Без этого импорта Base.metadata.create_all() не создаст таблицы.
import db.models  # noqa: F401

# Все HTTP-эндпоинты в одном роутере
from routers.api import router

# Менеджер OPC UA соединений с ПЛК
from protocol_backend.protocol_client.client_manager import ServerManager

# USB: мониторинг вставки/извлечения и экспорт данных
from usb import usb_monitor, usb_exporter

# Фоновый мониторинг дискового пространства с авто-очисткой
from services.disk_monitor import disk_monitor_loop


# Создаём все таблицы БД при старте если они ещё не существуют.
# При изменении схемы моделей — таблицы нужно пересоздавать вручную.
Base.metadata.create_all(bind=sync_engine)

# Настройка файлового лога для OPC UA — ротация 5 МБ, хранить 5 файлов
_log_dir = pathlib.Path(__file__).parent / "logs"
_log_dir.mkdir(exist_ok=True)
_file_handler = logging.handlers.RotatingFileHandler(
    _log_dir / "opcua.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger("protocol_backend").setLevel(logging.DEBUG)
logging.getLogger("protocol_backend").addHandler(_file_handler)

# Глобальная ссылка на менеджер серверов — нужна для graceful shutdown
_server_manager: ServerManager | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Управляет жизненным циклом приложения.
    Код до yield — startup, код после yield — shutdown.
    """
    global _server_manager

    # ── Startup ───────────────────────────────────────────────────────────────

    # Чистим БД от осадочных тегов прежних пресетов конфига (если стенд переключали).
    # Делаем до старта OPC UA, чтобы клиент сразу получал только актуальный набор.
    from db.maintenance import prune_unconfigured_tags
    prune_unconfigured_tags()

    # Создаём ServerManager: конфигурирует OPC UA соединения и колбэки,
    # затем подключается ко всем серверам из конфига _SERVERS
    _server_manager = ServerManager()
    _server_manager.start()

    # Назначаем колбэки USB-монитора:
    #   on_inserted → запускает экспорт checkout-папок на флешку
    #   on_removed  → размонтирует /mnt/usb
    usb_monitor.on_inserted = usb_exporter.export_on_insert
    usb_monitor.on_removed  = usb_exporter.on_usb_removed

    # Запускаем мониторинг USB через pyudev в отдельном daemon-потоке
    usb_monitor.start()

    # Запускаем фоновый мониторинг дискового пространства
    import asyncio
    _disk_task = asyncio.create_task(disk_monitor_loop())

    yield

    _disk_task.cancel()  # ── приложение работает ──────────────────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────────

    # Останавливаем USB-монитор
    usb_monitor.stop()

    # Отключаемся от всех OPC UA серверов, отменяем таймеры переподключения
    if _server_manager:
        _server_manager.stop()


# Создаём FastAPI приложение с кастомным lifespan
app = FastAPI(
    title       = "Registrator API",
    version     = "1.0.0",
    lifespan    = lifespan,
)

# CORS — разрешаем запросы от Windows-клиента (любой origin, т.к. локальная сеть)
app.add_middleware(
    CORSMiddleware,
    allow_origins = ["*"],
    allow_methods = ["*"],
    allow_headers = ["*"],
)

# Подключаем все роутеры (tags, history, tests, usb, records)
app.include_router(router)


@app.get("/health")
def health():
    """Пинг — проверка доступности сервера со стороны клиента."""
    return {"status": "ok"}

  # Прямой запуск: python main.py
if __name__ == "__main__":
    # В production запускается через systemd → uvicorn main:app
    uvicorn.run(
        "main:app",
        host    = "0.0.0.0",
        port    = 8000,
        reload  = False,
    )
