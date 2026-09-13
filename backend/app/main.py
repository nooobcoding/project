"""FastAPI 앱 진입점.

헬스체크·인증(01-auth)·대시보드(02-dashboard) 라우터, coins 동기화 잡
(00-overview.md 7장 로드맵 0번)과 시세 스트림(services/price_stream.py) 기동 훅을
갖는다. 기능별 라우터는 routers/ 아래에 추가되는 대로 여기서 include_router로
연결한다 (docs/02-coding-conventions.md 6장 프로젝트 구조 참고).
"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

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
from app.services import (
    candle_prefill,
    leader,
    pending_symbols,
    price_cache,
    shard_coverage,
    tick_bus,
)
from app.services.coin_sync import sync_coins
from app.services.matcher_runner import run_matcher
from app.services.price_stream import run_market_data
from app.strategy_engine.worker import (
    TICK_INTERVAL_SECONDS,
    release_shards as release_worker_shards,
    run_tick,
)

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Asia/Seoul")


# pending_symbols 재구성 주기. 이 시간이 곧 "SADD를 놓쳤을 때 그 주문이 체결되지 않는
# 최대 시간"이다 (02-market-data.md 4.2절).
PENDING_SYMBOLS_REBUILD_SECONDS = 300
SHARD_COVERAGE_CHECK_SECONDS = 60


# `scheduler` 역할은 정확히 1개만 활성이어야 한다 (00-architecture.md 2장 표). 6단계에서
# Upbit REST 호출이 이 역할로 일원화되면서 그 요구가 실제 비용이 됐다 — scheduler 프로세스가
# 둘이면 캔들 미리 채우기가 두 배로 돌아 토큰 버킷을 그만큼 헛되이 태운다.
_scheduler_leader = leader.LeaderLock("scheduler")
_was_leader: bool | None = None


def _check_shard_coverage() -> None:
    """matcher(심볼)·worker(유저) 샤드를 둘 다 본다. 한쪽 조회가 실패해도 다른 쪽은 봐야
    하므로 `check_*` 안에서 각자 예외를 삼킨다 (services/shard_coverage.py)."""
    shard_coverage.check_matcher_shards()
    shard_coverage.check_worker_shards()


def _leading() -> bool:
    """이 프로세스가 `scheduler` 리더인지. 전환될 때만 로그를 남긴다 — 잡 주기가 20초라
    매번 남기면 리더가 아닌 프로세스의 로그가 그 한 줄로 덮인다."""
    global _was_leader
    leading = _scheduler_leader.hold()
    if leading != _was_leader:
        logger.info(
            "scheduler 리더 %s — 주기 잡을 %s",
            "획득" if leading else "상실",
            "실행한다" if leading else "건너뛴다",
        )
        _was_leader = leading
    return leading


def _scheduler_job(name: str, run):
    """리더일 때만 도는 `scheduler` 잡으로 감싼다.

    예외를 삼키는 것은 여기 한 곳으로 모은다 — 잡 하나가 예외로 끝나면 APScheduler가 그
    잡을 다시 부르지 않을 뿐 아니라, DB/Upbit 장애가 서버 전체를 멈추게 두어서는 안 된다
    (00-overview.md 6장 1항 상시 실행 원칙).
    """

    def wrapped() -> None:
        if not _leading():
            return
        try:
            run()
        except Exception:
            logger.exception("%s 실패", name)

    wrapped.__name__ = f"scheduler_job_{name}"
    return wrapped


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

    `matcher`도 `redis`일 때만 별도 기동 경로를 갖는다 — 틱을 구독해 자기 샤드의 체결을
    처리한다. `memory`일 때는 pub/sub이 없어 구독할 것이 없으므로 지금까지처럼 시세 수신
    루프가 직접 체결을 호출한다 (services/price_stream.py `_matches_inline`).

    `scheduler`의 잡들은 전부 **리더로 선출된 프로세스에서만** 돈다 (`_scheduler_job`).
    6단계에서 Upbit REST 호출이 이 역할로 일원화됐기 때문이다 (04-async-jobs.md 3장).
    """
    roles = settings.process_roles

    if "market-data" not in roles:
        price_cache.warn_if_unfed("PROCESS_ROLES에 market-data가 없다")

    if "scheduler" in roles:
        coin_sync_job = _scheduler_job("coins 동기화", sync_coins)
        coin_sync_job()
        scheduler.add_job(coin_sync_job, CronTrigger(hour=4, minute=0))
        # 캔들 미리 채우기는 워커 tick에서 Upbit REST를 빼낸 대가다 — 이 잡이 밀리면 워커가
        # 평가를 건너뛴다 (04-async-jobs.md 3.3절). 첫 tick이 빈 캐시를 보고 통째로 스킵하는
        # 구간을 줄이려면 기동 직후 1회를 돌려야 하는데, **여기서 직접 부르면 안 된다** —
        # 활성 조합 수만큼의 HTTP(+토큰 대기)가 lifespan을 막아 그동안 서버가 요청을 받지
        # 못한다. `next_run_time`으로 스케줄러 스레드에서 즉시 돌린다.
        scheduler.add_job(
            _scheduler_job("캔들 미리 채우기", candle_prefill.run_prefill),
            IntervalTrigger(seconds=candle_prefill.PREFILL_INTERVAL_SECONDS),
            next_run_time=datetime.now(timezone.utc),
            max_instances=1,
            coalesce=True,
        )
        # pending_symbols는 힌트일 뿐이라 SADD 누락·Redis 유실로 새면 그 심볼의 주문이
        # 영영 체결되지 않는다. 주기적 재구성이 그 유일한 복구 경로다 (02-market-data.md
        # 4.2절). 커버리지 검사는 아무도 점유하지 않은 샤드를 잡는다 (06 3.4절).
        scheduler.add_job(
            _scheduler_job("pending_symbols 재구성", pending_symbols.rebuild),
            IntervalTrigger(seconds=PENDING_SYMBOLS_REBUILD_SECONDS),
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            _scheduler_job("샤드 커버리지 검사", _check_shard_coverage),
            IntervalTrigger(seconds=SHARD_COVERAGE_CHECK_SECONDS),
            max_instances=1,
            coalesce=True,
        )

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
    if "matcher" in roles and settings.price_cache_backend == "redis":
        background_tasks.append(asyncio.create_task(run_matcher()))

    yield

    for task in background_tasks:
        task.cancel()
    for task in background_tasks:
        with suppress(asyncio.CancelledError):
            await task
    scheduler.shutdown()
    # 락을 명시적으로 풀어 다음 프로세스의 승격을 앞당긴다. 안 풀어도 세션이 끊기면 자동으로
    # 풀리지만, 그때까지 scheduler 샤드는 아무도 캔들을 안 채우고 worker 샤드는 그 유저들의
    # 자동매매가 통째로 멈춘 상태다.
    _scheduler_leader.release()
    if "worker" in roles:
        release_worker_shards()


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
