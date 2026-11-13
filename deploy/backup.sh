#!/bin/bash
# 운영 DB 백업 — pg_dump를 압축해 ~/backups에 남기고 오래된 것은 지운다 (docs/deploy.md 5장).
# 서버 crontab에서 하루 한 번 돈다:
#   0 4 * * * /home/ubuntu/coin/deploy/backup.sh >> /home/ubuntu/backups/backup.log 2>&1
#
# 같은 서버 디스크에 남기므로 컨테이너·볼륨 사고는 막지만 서버 자체를 잃으면 같이 잃는다.
# 전시 전처럼 중요한 시점에는 내 PC로 내려받아 둔다(scp).
# pipefail: 없으면 pg_dump가 실패해도 gzip이 성공해 파이프 전체가 성공으로 끝나고,
# 빈(깨진) 백업이 정상 파일처럼 남는다.
set -euo pipefail

KEEP_DAYS="${KEEP_DAYS:-7}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
ENV_FILE="${ENV_FILE:-.env.prod}"
cd "$(dirname "$0")/.."

mkdir -p "$BACKUP_DIR"
out="$BACKUP_DIR/coin-$(date +%Y%m%d-%H%M%S).sql.gz"

# -T: cron에는 터미널이 없다. 비밀번호·DB 이름은 postgres 컨테이너의 환경변수를 그대로 쓴다.
# 실패한 덤프가 정상 파일처럼 남지 않도록 임시 이름으로 쓴 뒤 옮긴다.
trap 'rm -f "$out.tmp"' EXIT
docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE" exec -T postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' | gzip > "$out.tmp"
mv "$out.tmp" "$out"

find "$BACKUP_DIR" -name 'coin-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "$(date '+%F %T') 백업 완료: $out ($(du -h "$out" | cut -f1))"
