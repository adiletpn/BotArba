"""Ежедневная выгрузка базы (требование ТЗ)."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from app.clock import now_utc

logger = logging.getLogger(__name__)


async def make_backup(db, backup_dir: Path, keep_days: int) -> Path:
    """Снять копию базы и подчистить старые.

    Копия делается через backup API SQLite, а не копированием файла: при
    включённом WAL часть свежих транзакций лежит в -wal, и простой cp дал бы
    копию без них.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_utc().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"botarba-{stamp}.db"

    await db.backup_to(target)
    logger.info("Бэкап создан: %s (%s байт)", target, target.stat().st_size)

    cutoff = now_utc() - timedelta(days=keep_days)
    for old in backup_dir.glob("botarba-*.db"):
        try:
            modified = old.stat().st_mtime
        except OSError:
            continue
        if modified < cutoff.timestamp():
            old.unlink(missing_ok=True)
            logger.info("Старый бэкап удалён: %s", old.name)

    return target
