from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker


def _set_wal(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")


# Async engine — используется в FastAPI эндпоинтах
_DB_PATH = "/home/user/registrator.db"

async_engine = create_async_engine(
    f"sqlite+aiosqlite:///{_DB_PATH}",
    echo=False,
    connect_args={"timeout": 30},
)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit = False, class_ = AsyncSession)

# Выставляем WAL и на async engine — иначе при первом подключении через aiosqlite
# прагма не будет установлена, если sync engine ещё не успел подключиться.
event.listen(async_engine.sync_engine, "connect", _set_wal)

# Sync engine — используется в фоновых задачах (session_exporter, usb_exporter)
# и для создания таблиц при старте
sync_engine = create_engine(
    f"sqlite:///{_DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)
event.listen(sync_engine, "connect", _set_wal)
SessionLocal = sessionmaker(autocommit = False, autoflush = False, bind = sync_engine)


class Base(DeclarativeBase):
    pass


async def get_db():
    """Dependency: async сессия БД для FastAPI эндпоинтов."""
    async with AsyncSessionLocal() as session:
        yield session
