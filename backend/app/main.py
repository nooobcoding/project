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
    portfolio,
    prices,
    strategy_slots,
    wallet,
)
from app.services import tick_bus
from app.services.coin_sync import sync_coins
from app.services.price_stream import run_market_data
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
    """PROCESS_ROLES에 켜진 역할만 기동한다 (확장판 00-architecture.md 2.1절, 07-roadmap.md
    1·4단계). 기본값은 전 역할 활성이라 로컬 개발은 지금까지와 동일하게 coins 동기화·자동매매
    워커·시세 스트림이 전부 한 프로세스에서 상시 돈다.

    `market-data`는 켜져 있어도 advisory lock 리더로 선출된 프로세스만 실제로 Upbit에
    붙는다 (services/price_stream.py). `api`는 `PRICE_CACHE_BACKEND=redis`일 때만 별도
    기동 경로를 갖는다 — 다른 프로세스가 발행한 틱을 구독해 자기 WebSocket 클라이언트에게
    전달해야 하기 때문이다. `memory`일 때는 같은 프로세스의 스트림이 직접 넣어주므로 구독할
    것이 없다 (services/tick_bus.py).

    `matcher`는 아직 독립된 기동 경로가 없다 — 5단계까지 market-data의 시세 수신 루프 안에
    묶여 있다 (00-architecture.md 1장 ③).
    """
    roles = settings.process_roles

    if "market-data" not in roles and settings.price_cache_backend == "memory":
        # memory 캐시는 프로세스 안에만 있다 — 이 프로세스에는 시세를 쓰는 주체가 없으므로
        # 모든 시세 조회가 영영 "시세 없음"이 된다. 역할을 나눴으면 redis로 가야 한다.
        # 조용히 실패하면 "주문이 자꾸 거부된다"로만 보이므로 기동 시점에 못 박아둔다
        # (06-observability.md 5장 조용한 실패 금지).
        logger.warning(
            "PROCESS_ROLES에 market-data가 없는데 PRICE_CACHE_BACKEND=memory다 — "
            "이 프로세스는 시세를 전혀 못 읽는다. 역할을 나눴다면 PRICE_CACHE_BACKEND=redis로 설정할 것."
        )

    if "scheduler" in roles:
        _run_coin_sync_job()
        scheduler.add_job(_run_coin_sync_job, CronTrigger(hour=4, minute=0))

    if "worker" in roles:
        # max_instances=1은 필수다 — tick이 겹치면 같은 확정봉을 두 슬롯 순회가 동시에
        # 평가해 중복 주문이 나갈 수 있다. coalesce=True는 밀린 실행을 1회로 합쳐 재개
        # 직후 폭주를 막는다 (07-auto-trading.md 4장).
        scheduler.add_job(
            run_tick,
            IntervalTrigger(seconds=TICK_INTERVAL_SECONDS),
            max_instances=1,
            coalesce=True,
        )

    scheduler.start()

    background_tasks = []
    if "market-data" in roles:
        background_tasks.append(asyncio.create_task(run_market_data()))
    if "api" in roles and settings.price_cache_backend == "redis":
        background_tasks.append(asyncio.create_task(tick_bus.run_tick_subscriber()))

    yield

    for task in background_tasks:
        task.cancel()
    for task in background_tasks:
        with suppress(asyncio.CancelledError):
            await task
    scheduler.shutdown()


app = FastAPI(title="코인 자동매매 프로그램 API", lifespan=lifespan)

# 허용 origin은 배포 환경마다 다르므로 설정값(CORS_ALLOWED_ORIGINS)에서 가져온다 (app/config.py)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # 기본값은 CORS-safelisted 응답 헤더만 노출한다 — Content-Disposition은 그 목록에
    # 없어 명시하지 않으면 브라우저 JS가 못 읽는다(08-portfolio CSV 내보내기가 파일명을
    # 이 헤더에서 파싱한다, api/portfolio.ts downloadPortfolioTradesCsv).
    expose_headers=["Content-Disposition"],
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
app.include_router(portfolio.router)


@app.get("/health")
def health_check() -> dict[str, str]:
    """서버 생존 확인용 헬스체크 엔드포인트."""
    return {"status": "ok"}
