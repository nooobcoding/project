"""FastAPI 앱 진입점.

헬스체크·인증(01-auth)·대시보드(02-dashboard) 라우터, coins 동기화 잡
(00-overview.md 7장 로드맵 0번)과 시세 스트림(services/price_stream.py) 기동 훅을
갖는다. 기능별 라우터는 routers/ 아래에 추가되는 대로 여기서 include_router로
연결한다 (docs/02-coding-conventions.md 6장 프로젝트 구조 참고).
"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, dashboard, prices
from app.services.coin_sync import sync_coins
from app.services.price_stream import run_price_stream

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
    """기동 시 1회 coins 동기화 후 매일 04:00(KST) 동기화를 스케줄링하고,
    시세 스트림(price_stream)을 상시 백그라운드 태스크로 시작한다."""
    _run_coin_sync_job()
    scheduler.add_job(_run_coin_sync_job, CronTrigger(hour=4, minute=0))
    scheduler.start()
    price_stream_task = asyncio.create_task(run_price_stream())
    yield
    price_stream_task.cancel()
    with suppress(asyncio.CancelledError):
        await price_stream_task
    scheduler.shutdown()


app = FastAPI(title="코인 자동매매 프로그램 API", lifespan=lifespan)

# 프론트엔드 Vite 개발 서버(기본 5173)에서의 요청 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(prices.router)


@app.get("/health")
def health_check() -> dict[str, str]:
    """서버 생존 확인용 헬스체크 엔드포인트."""
    return {"status": "ok"}
