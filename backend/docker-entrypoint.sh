#!/bin/sh
# postgres 서비스가 뜰 때까지 대기 후 마이그레이션을 적용하고 앱을 기동한다.
set -e

echo "postgres 연결 대기 중..."
until python -c "
from sqlalchemy import create_engine
from app.config import settings
create_engine(settings.database_url).connect().close()
" 2>/dev/null; do
  sleep 1
done

# 여러 프로세스 구성(docker-compose.scale.yml)에서는 컨테이너가 동시에 뜬다. 전부 마이그레이션을
# 돌리면 빈 DB에서 서로 경합하므로, 한 서비스(api)만 돌리고 나머지는 RUN_MIGRATIONS=0으로 건너뛴다.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "alembic upgrade head 실행..."
  alembic upgrade head
fi

exec "$@"
