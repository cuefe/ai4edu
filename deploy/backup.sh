#!/usr/bin/env bash
# 备份数据库和上传的文件（资料原文件、拍照作答），保留最近 14 天。
#
# 每天凌晨执行（crontab -e 加一行）：
#   30 3 * * * /opt/ai4edu/deploy/backup.sh >> /var/log/ai4edu-backup.log 2>&1
#
# 恢复数据库（先停 api、worker，避免写入）：
#   docker compose stop api worker
#   docker compose exec -T db pg_restore -U postgres -d ai4edu --clean --if-exists < db-时间.dump
#   docker compose start api worker
# 恢复文件：
#   docker compose run --rm --no-deps -v /备份目录:/backup api tar xzf /backup/files-时间.tar.gz -C /data/files
#
# 备份和服务器在同一块盘上，盘坏了一起丢：建议再定期拷到别处（对象存储或另一台机器）。
set -euo pipefail

cd "$(dirname "$0")"
DEST="${BACKUP_DIR:-/var/backups/ai4edu}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M)"
mkdir -p "$DEST"

# 数据库：pg_dump 自定义格式（压缩、可以按表恢复）。先写临时文件，成功后再改名，避免留下半截的备份
docker compose exec -T db pg_dump -U postgres -d ai4edu -Fc > "$DEST/db-$STAMP.dump.part"
mv "$DEST/db-$STAMP.dump.part" "$DEST/db-$STAMP.dump"

# 上传的文件：借 api 镜像打包文件卷
docker compose run --rm --no-deps -v "$DEST:/backup" api \
  tar czf "/backup/files-$STAMP.tar.gz.part" -C /data/files .
mv "$DEST/files-$STAMP.tar.gz.part" "$DEST/files-$STAMP.tar.gz"

find "$DEST" -maxdepth 1 \( -name 'db-*.dump' -o -name 'files-*.tar.gz' \) -mtime +"$KEEP_DAYS" -delete
echo "$(date '+%F %T') 备份完成：$(du -h "$DEST/db-$STAMP.dump" | cut -f1) 数据库，$(du -h "$DEST/files-$STAMP.tar.gz" | cut -f1) 文件"
