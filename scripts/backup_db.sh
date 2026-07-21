#!/bin/bash
# SQLite 自动备份 - 保留3份轮换
set -e
DB_DIR="/var/www/hospital-workorder/instance"
BACKUP_DIR="/var/backups/workorders"
DB_NAME="workorders.db"

# 确保备份目录存在
mkdir -p "$BACKUP_DIR"

# 轮换：3→2, 2→1, 1→0
[ -f "$BACKUP_DIR/$DB_NAME.2" ] && mv "$BACKUP_DIR/$DB_NAME.2" "$BACKUP_DIR/$DB_NAME.3"
[ -f "$BACKUP_DIR/$DB_NAME.1" ] && mv "$BACKUP_DIR/$DB_NAME.1" "$BACKUP_DIR/$DB_NAME.2"
[ -f "$BACKUP_DIR/$DB_NAME.0" ] && mv "$BACKUP_DIR/$DB_NAME.0" "$BACKUP_DIR/$DB_NAME.1"

# 使用 SQLite 在线备份（不会锁库）
sqlite3 "$DB_DIR/$DB_NAME" ".backup '$BACKUP_DIR/$DB_NAME.0'"

echo "Backup done: $(date -Iseconds) size=$(du -h $BACKUP_DIR/$DB_NAME.0 | cut -f1)"
