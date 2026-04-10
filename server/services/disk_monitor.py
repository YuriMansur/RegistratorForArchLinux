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


async def disk_monitor_loop() -> None:
    """Запускается как asyncio фоновая задача при старте сервера."""
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            # Проверка размера БД
            db_size = _db_gb()
            if db_size > DB_MAX_GB:
                logger.warning("БД превысила %.1f GB (%.2f GB). Удаляем старые записи.", DB_MAX_GB, db_size)
                while _db_gb() > DB_MAX_GB:
                    deleted = await _trim_history()
                    logger.warning("Удалено %d записей из tag_history. Размер БД: %.2f GB", deleted, _db_gb())
                    if deleted == 0:
                        break

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
