"""
Фоновая задача мониторинга дискового пространства.

Каждые 60 секунд проверяет свободное место на /home.
Если свободно < LOW_SPACE_GB — удаляет самые старые файлы из папок бэкапов:
  1. /home/user/system_backups/ (сначала, т.к. .fsa файлы крупнее)
  2. /home/user/db_backups/
"""

import asyncio
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_HOME        = Path("/home/user")
_SYS_BACKUPS = _HOME / "system_backups"
_DB_BACKUPS  = _HOME / "registrator_backups"

LOW_SPACE_GB  = 10.0   # порог: меньше этого — начинаем чистить
CHECK_INTERVAL = 60    # секунд между проверками


def _free_gb() -> float:
    return shutil.disk_usage(_HOME).free / 1024**3


def _oldest_file(directory: Path, pattern: str = "*") -> Path | None:
    files = sorted(directory.glob(pattern), key=lambda f: f.stat().st_mtime)
    return files[0] if files else None


async def disk_monitor_loop() -> None:
    """Запускается как asyncio фоновая задача при старте сервера."""
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            free = _free_gb()
            if free >= LOW_SPACE_GB:
                continue

            logger.warning("Мало места на диске: %.1f GB свободно. Начинаем очистку.", free)

            # Сначала удаляем системные бэкапы (они крупнее)
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
