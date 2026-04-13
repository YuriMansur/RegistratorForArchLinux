"""
Фоновая задача мониторинга дискового пространства и размера БД.

Каждые 60 секунд:
  - Если свободно < LOW_SPACE_GB — удаляет старые бэкапы
  - Если БД > DB_MAX_GB — удаляет старые записи tag_history порциями
"""

import asyncio
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_HOME        = Path("/home/user")
_DB_PATH     = _HOME / "registrator.db"
_SYS_BACKUPS = _HOME / "system_backups"
_DB_BACKUPS  = _HOME / "registrator_backups"

LOW_SPACE_GB   = 10.0   # порог свободного места
DB_MAX_GB      = 50.0   # максимальный размер БД
DB_TRIM_ROWS   = 10000  # сколько строк удалять за раз
CHECK_INTERVAL = 60     # секунд между проверками


def _free_gb() -> float:
    return shutil.disk_usage(_HOME).free / 1024**3


def _db_gb() -> float:
    return _DB_PATH.stat().st_size / 1024**3 if _DB_PATH.exists() else 0.0


def _oldest_file(directory: Path, pattern: str = "*") -> Path | None:
    files = sorted(directory.glob(pattern), key=lambda f: f.stat().st_mtime)
    return files[0] if files else None


async def _trim_history() -> int:
    """Удаляет DB_TRIM_ROWS самых старых строк из tag_history. Возвращает кол-во удалённых."""
    from db.database import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(
            f"DELETE FROM tag_history WHERE id IN "
            f"(SELECT id FROM tag_history ORDER BY recorded_at ASC LIMIT {DB_TRIM_ROWS})"
        ))
        await db.commit()
        return result.rowcount


async def _checkpoint_wal() -> None:
    """Принудительный WAL checkpoint с усечением файла.

    Без этого WAL растёт неограниченно — автоматический checkpoint блокируется
    активными читателями (FastAPI запросы). TRUNCATE сбрасывает WAL в основной
    файл и усекает его до нуля, что резко уменьшает размер FSA-бэкапа.
    """
    from db.database import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        row = result.fetchone()
        if row:
            # row = (busy, log, checkpointed)
            # busy=1 означает что кто-то держит читатель и WAL не усечён — нормально
            logger.info(
                "WAL checkpoint: busy=%s, log_pages=%s, checkpointed=%s",
                row[0], row[1], row[2],
            )


async def _vacuum_db() -> None:
    """Incremental vacuum — возвращает свободные страницы ОС после DELETE.

    После удаления строк SQLite помечает страницы как свободные, но НЕ уменьшает
    файл. incremental_vacuum освобождает до 10000 страниц за раз без полной блокировки.
    """
    from db.database import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        # Включаем incremental auto_vacuum если ещё не включён
        await db.execute(text("PRAGMA auto_vacuum = INCREMENTAL"))
        await db.execute(text("PRAGMA incremental_vacuum(10000)"))
        await db.commit()
    logger.info("Incremental vacuum done. DB size: %.2f GB", _db_gb())


# Счётчик итераций — checkpoint запускается реже чем основная проверка
_loop_iteration = 0
# Каждые N итераций (N * CHECK_INTERVAL секунд) запускать WAL checkpoint
_CHECKPOINT_EVERY = 5   # каждые 5 минут при CHECK_INTERVAL=60


async def disk_monitor_loop() -> None:
    """Запускается как asyncio фоновая задача при старте сервера."""
    global _loop_iteration
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            _loop_iteration += 1

            # WAL checkpoint — каждые _CHECKPOINT_EVERY итераций
            if _loop_iteration % _CHECKPOINT_EVERY == 0:
                await _checkpoint_wal()

            # Проверка размера БД
            db_size = _db_gb()
            if db_size > DB_MAX_GB:
                logger.warning("БД превысила %.1f GB (%.2f GB). Удаляем старые записи.", DB_MAX_GB, db_size)
                deleted_total = 0
                # Удаляем строки. Размер файла не уменьшается сразу (SQLite free-list),
                # поэтому ограничиваем цикл числом удалённых строк, а не размером файла.
                for _ in range(100):
                    deleted = await _trim_history()
                    deleted_total += deleted
                    logger.warning("Удалено %d записей. Всего за сессию: %d", deleted, deleted_total)
                    if deleted == 0:
                        break
                # Возвращаем страницы ОС через incremental vacuum
                if deleted_total > 0:
                    await _vacuum_db()
                    await _checkpoint_wal()

            # Проверка свободного места
            free = _free_gb()
            if free >= LOW_SPACE_GB:
                continue

            logger.warning("Мало места на диске: %.1f GB свободно. Начинаем очистку.", free)

            for directory, pattern in [(_SYS_BACKUPS, "*.fsa"), (_DB_BACKUPS, "*")]:
                if not directory.exists():
                    continue
                while _free_gb() < LOW_SPACE_GB:
                    f = _oldest_file(directory, pattern)
                    if f is None:
                        break
                    logger.warning("Удаляю старый бэкап для освобождения места: %s", f)
                    f.unlink()

        except Exception:
            logger.exception("Ошибка в disk_monitor_loop")
