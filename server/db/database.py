# create_engine — создаёт синхронный движок SQLAlchemy для работы с SQLite.
# event — позволяет навешивать обработчики на события движка (например "connect").
from sqlalchemy import create_engine, event
# sessionmaker — фабрика синхронных сессий для работы с БД в фоновых потоках.
# DeclarativeBase — базовый класс для ORM-моделей.
from sqlalchemy.orm import sessionmaker, DeclarativeBase
# create_async_engine — асинхронный движок для FastAPI эндпоинтов.
# AsyncSession — асинхронная сессия SQLAlchemy.
# async_sessionmaker — фабрика асинхронных сессий.
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker


def _set_wal(dbapi_conn, _):
    """Активировать WAL-режим и ослабить синхронизацию при каждом новом соединении с БД.

    WAL (Write-Ahead Log) позволяет читателям не блокировать писателя и наоборот.
    synchronous=NORMAL — сброс на диск только в критических точках, что ускоряет запись.
    Вызывается автоматически через event.listen при каждом открытии соединения.
    """
    # Включаем WAL-режим — несколько читателей + один писатель без блокировок.
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    # NORMAL — безопаснее чем OFF, быстрее чем FULL. Данные могут потеряться только при сбое ОС.
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")


# Абсолютный путь к файлу БД на сервере Arch Linux.
_DB_PATH = "/home/user/registrator.db"

# Асинхронный движок — используется в FastAPI эндпоинтах через Depends(get_db).
# aiosqlite — драйвер для работы с SQLite в asyncio без блокировки event loop.
async_engine = create_async_engine(
    f"sqlite+aiosqlite:///{_DB_PATH}",
    echo=False,                        # не логировать SQL-запросы в stdout
    connect_args={"timeout": 30},      # ждать до 30с если БД заблокирована другим процессом
)

# Фабрика асинхронных сессий — создаёт сессии для FastAPI зависимостей.
# expire_on_commit=False — объекты не инвалидируются после commit (важно для async).
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

# Вешаем _set_wal на событие "connect" синхронного движка внутри async_engine.
# Без этого при первом подключении через aiosqlite WAL-прагма не устанавливалась бы,
# если sync_engine ещё не подключился первым.
event.listen(async_engine.sync_engine, "connect", _set_wal)

# Синхронный движок — используется в фоновых потоках вне asyncio event loop:
# session_exporter (генерация xlsx/docx/png), usb_exporter, client_manager.
# check_same_thread=False — разрешить использование одного соединения из разных потоков.
sync_engine = create_engine(
    f"sqlite:///{_DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)

# Вешаем WAL-прагму на синхронный движок — срабатывает при каждом новом подключении.
event.listen(sync_engine, "connect", _set_wal)

# Фабрика синхронных сессий для фоновых потоков.
# autocommit=False — транзакции нужно фиксировать явно через db.commit().
# autoflush=False — не сбрасывать изменения автоматически перед каждым запросом.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей проекта.

    Все модели (Tag, TagHistory, Checkout, TagValue) наследуются от него.
    Base.metadata.create_all() создаёт все таблицы в БД при старте сервера.
    """
    pass


async def get_db():
    """FastAPI Dependency — предоставляет асинхронную сессию БД для одного запроса.

    Используется через Depends(get_db) в роутерах.
    Сессия автоматически закрывается после завершения запроса (async with).
    """
    # Открываем сессию — она будет жить ровно один HTTP-запрос.
    async with AsyncSessionLocal() as session:
        # yield передаёт сессию в роутер, после его завершения сессия закрывается.
        yield session
