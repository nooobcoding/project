"""FastAPI 앱 진입점.

헬스체크·인증(01-auth) 라우터와 coins 동기화 잡(00-overview.md 7장 로드맵 0번)
기동 훅을 갖는다. 기능별 라우터는 routers/ 아래에 추가되는 대로 여기서
include_router로 연결한다 (docs/02-coding-conventions.md 6장 프로젝트 구조 참고).
"""

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.routers import auth
from app.services.coin_sync import sync_coins

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Asia/Seoul")


def _run_coin_sync_job() -> None:
    """coins 동기화 실행부. DB/Upbit 장애 시에도 서버·스케줄러는 계속 동작해야 한다."""
    try:
        sync_coins()
    except Exception:
        logger.exception("coins 동기화 실패")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """기동 시 1회 동기화 후, 매일 04:00(KST) 동기화를 스케줄링한다."""
    _run_coin_sync_job()
    scheduler.add_job(_run_coin_sync_job, CronTrigger(hour=4, minute=0))
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="코인 자동매매 프로그램 API", lifespan=lifespan)
app.include_router(auth.router)


@app.get("/health")
def health_check() -> dict[str, str]:
    """서버 생존 확인용 헬스체크 엔드포인트."""
    return {"status": "ok"}
