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

echo "alembic upgrade head 실행..."
alembic upgrade head

exec "$@"
