#!/bin/bash
# SYUTAINβ V25 データベースバックアップ

BACKUP_DIR="data/backup"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')

mkdir -p "$BACKUP_DIR"

echo "=== データベースバックアップ: ${TIMESTAMP} ==="

# PostgreSQL
echo "PostgreSQLバックアップ中..."
pg_dump syutain_beta > "${BACKUP_DIR}/postgresql_${TIMESTAMP}.sql" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "  完了: ${BACKUP_DIR}/postgresql_${TIMESTAMP}.sql"
else
    echo "  失敗"
fi

# SQLite（ALPHAローカル）
for db in data/local_alpha.db data/core.db; do
    if [ -f "$db" ]; then
        base=$(basename "$db" .db)
        cp "$db" "${BACKUP_DIR}/${base}_${TIMESTAMP}.db"
        echo "  完了: ${BACKUP_DIR}/${base}_${TIMESTAMP}.db"
    fi
done

# 古いバックアップを削除（7日以上前）
find "$BACKUP_DIR" -type f -mtime +7 -delete 2>/dev/null

echo "バックアップ完了"
