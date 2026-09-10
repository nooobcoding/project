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
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    account,
    auth,
    backtest,
    candles,
    coins,
    dashboard,
    notification_settings,
    notifications,
    orderbook,
    orders,
    prices,
    strategy_slots,
    wallet,
)
from app.services.coin_sync import sync_coins
from app.services.price_stream import run_price_stream
from app.strategy_engine.worker import TICK_INTERVAL_SECONDS, run_tick

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
    """기동 시 1회 coins 동기화 후 매일 04:00(KST) 동기화를 스케줄링하고, 자동매매 워커와
    시세 스트림(price_stream)을 상시 백그라운드로 시작한다."""
    _run_coin_sync_job()
    scheduler.add_job(_run_coin_sync_job, CronTrigger(hour=4, minute=0))
    # max_instances=1은 필수다 — tick이 겹치면 같은 확정봉을 두 슬롯 순회가 동시에 평가해
    # 중복 주문이 나갈 수 있다. coalesce=True는 밀린 실행을 1회로 합쳐 재개 직후 폭주를 막는다
    # (07-auto-trading.md 4장).
    scheduler.add_job(
        run_tick,
        IntervalTrigger(seconds=TICK_INTERVAL_SECONDS),
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    price_stream_task = asyncio.create_task(run_price_stream())
    yield
    price_stream_task.cancel()
    with suppress(asyncio.CancelledError):
        await price_stream_task
    scheduler.shutdown()


app = FastAPI(title="코인 자동매매 프로그램 API", lifespan=lifespan)

# 허용 origin은 배포 환경마다 다르므로 설정값(CORS_ALLOWED_ORIGINS)에서 가져온다 (app/config.py)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(prices.router)
app.include_router(candles.router)
app.include_router(coins.router)
app.include_router(orders.router)
app.include_router(orderbook.router)
app.include_router(account.router)
app.include_router(notification_settings.router)
app.include_router(notifications.router)
app.include_router(wallet.router)
app.include_router(strategy_slots.router)
app.include_router(backtest.router)


@app.get("/health")
def health_check() -> dict[str, str]:
    """서버 생존 확인용 헬스체크 엔드포인트."""
    return {"status": "ok"}
