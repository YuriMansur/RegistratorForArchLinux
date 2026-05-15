#!/bin/bash
BACKUP_DIR=/home/user/system_backups
KEEP=3

mkdir -p $BACKUP_DIR
DEST=$BACKUP_DIR/system_$(date +%Y-%m-%d_%H-%M-%S).fsa

echo "Starting system backup → $DEST"
fsarchiver savefs -A -Z 3 -j2 \
    --exclude=/user/system_backups \
    --exclude=/user/registrator.db-wal \
    --exclude=/user/registrator.db-shm \
    $DEST /dev/sda1 /dev/sda2 /dev/sda3

if [ -f "$DEST" ]; then
    echo "Backup done: $DEST ($(du -sh $DEST | cut -f1))"
else
    echo "Backup FAILED"
    exit 1
fi

ls -t $BACKUP_DIR/system_*.fsa 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --
