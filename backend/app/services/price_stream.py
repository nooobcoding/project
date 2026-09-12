"""`market-data` 역할 — Upbit 공개 시세 WebSocket을 상시 구독해 시세 캐시를 갱신한다.

00-overview.md 3장의 "시세 캐시" 갱신 주체다. 클라이언트 접속 여부와 무관하게 항상
갱신되어야 하므로(체결 엔진·자동매매 손절/익절이 이 캐시를 쓰는 09/07의 전제),
main.py의 lifespan에서 앱 기동과 함께 백그라운드 태스크로 시작한다. `/ws/prices`는
이 캐시의 소비자일 뿐 Upbit 구독 대상을 결정하지 않는다.

확장판에서 이 모듈이 맡는 경계 (docs-scale/02-market-data.md 3장):

- **캐시 저장소는 services/price_cache.py** — 여기서는 쓰기만 하고 읽기는 그쪽이 맡는다.
- **프론트 전달은 services/tick_bus.py** — 같은 프로세스에 직접 넣을지 `ticks:{symbol}`로
  발행할지는 그쪽이 정한다.
- **정확히 1개만 활성이어야 한다** — 여러 프로세스가 Upbit WS에 붙어도 기능은 깨지지 않지만
  같은 틱이 여러 번 발행되어 매칭이 중복으로 돈다. 그래서 advisory lock 리더 선출을 거친
  프로세스만 스트림을 돌린다 (`run_market_data`, 같은 문서 3.2절).
- **체결 엔진 훅은 아직 여기 남아 있다** — 5단계에서 `matcher` 역할이 `ticks:{symbol}`을
  구독하는 형태로 떼어낸다 (같은 문서 4장).
"""

import asyncio
import json
import logging
import uuid
from contextlib import suppress
from decimal import Decimal
from typing import Iterable

import websockets
from sqlalchemy import select

from app.config import settings
from app.database import session_scope
from app.models import Coin
from app.services import leader, matcher, price_cache, tick_bus

logger = logging.getLogger(__name__)

UPBIT_TICKER_WS_URL = "wss://api.upbit.com/websocket/v1"
RECONNECT_DELAY_SECONDS = 5
RESUBSCRIBE_INTERVAL_SECONDS = 300  # coins 동기화 잡 반영 주기 (00-overview.md 3장)
LEADER_RETRY_INTERVAL_SECONDS = 10
# 리더십 재확인 주기. 짧게 잡을수록 "락을 잃은 줄 모르고 계속 스트리밍하는" 창이 줄지만,
# 그 창에 생기는 피해는 틱 중복 발행뿐이라(자금 경로가 아니다) 30초면 충분하다.
LEADERSHIP_CHECK_INTERVAL_SECONDS = 30


def _active_market_codes() -> dict[str, str]:
    """활성 KRW 마켓의 {market_code: symbol} 매핑을 조회한다."""
    with session_scope() as db:
        coins = db.scalars(select(Coin).where(Coin.is_active)).all()
        return {coin.market_code: coin.symbol for coin in coins}


def _build_subscribe_frame(market_codes: Iterable[str]) -> str:
    return json.dumps(
        [
            {"ticket": str(uuid.uuid4())},
            {"type": "ticker", "codes": list(market_codes)},
            {"format": "DEFAULT"},
        ]
    )


def _to_tick(message: dict, symbol: str) -> dict:
    return {
        "symbol": symbol,
        "trade_price": message["trade_price"],
        "trade_volume": message["trade_volume"],  # 진행 중인 캔들의 거래량 누적용 (02-dashboard 차트)
        "change": message["change"],
        "signed_change_rate": message["signed_change_rate"],
        "prev_closing_price": message["prev_closing_price"],
        "high_price": message["high_price"],  # 03-manual-trading 당일 고가 표시용
        "low_price": message["low_price"],  # 03-manual-trading 당일 저가 표시용
        "acc_trade_volume_24h": message["acc_trade_volume_24h"],  # 03-manual-trading 24H 거래량 표시용
        "timestamp": message["timestamp"],
    }


def _matches_inline() -> bool:
    """체결을 이 루프 안에서 직접 할지 판단한다.

    `redis` 백엔드에서는 `matcher` 역할이 `ticks:{symbol}`을 구독해서 처리하므로 여기서
    또 부르면 같은 틱이 두 번 매칭된다(조건부 UPDATE가 중복 체결은 막지만 DB 왕복이 두 배가
    된다). `memory` 백엔드는 pub/sub 자체가 없어 구독자가 있을 수 없으므로, 지금까지처럼
    이 루프가 직접 부르는 것이 유일한 경로다 (02-market-data.md 4.1절).
    """
    return settings.price_cache_backend == "memory"


def _run_matcher_safely(symbol: str, trade_price) -> None:
    """체결 엔진 훅 (09-execution-engine.md 2장). DB 장애가 상시 시세 스트림을
    끊지 않도록 예외를 삼키고 로그만 남긴다 (main.py의 coin 동기화 잡과 동일 원칙)."""
    try:
        matcher.run_matching_for_symbol(symbol, Decimal(str(trade_price)))
    except Exception:
        logger.exception("체결 엔진 처리 실패 (symbol=%s)", symbol)


async def _stream_once() -> None:
    """연결 1회 수명 주기. RESUBSCRIBE_INTERVAL_SECONDS마다 스스로 종료해 상위 루프가
    최신 coins 목록으로 재연결하도록 한다 (상장폐지/신규상장 반영)."""
    market_to_symbol = _active_market_codes()
    async with websockets.connect(UPBIT_TICKER_WS_URL) as ws:
        await ws.send(_build_subscribe_frame(market_to_symbol.keys()))
        loop = asyncio.get_event_loop()
        deadline = loop.time() + RESUBSCRIBE_INTERVAL_SECONDS

        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            message = json.loads(raw)
            symbol = market_to_symbol.get(message.get("code"))
            if symbol is None:
                continue
            tick = _to_tick(message, symbol)
            await price_cache.store_tick(symbol, tick)
            await tick_bus.publish(symbol, tick)
            if _matches_inline():
                # 체결 엔진 훅 — 동기 DB 작업이 이 상시 루프를 막지 않도록 별도 스레드에서 수행
                await asyncio.to_thread(_run_matcher_safely, symbol, tick["trade_price"])


async def run_price_stream() -> None:
    """Upbit ticker WS에 상시 연결해 시세 캐시를 갱신한다. 실패해도 무한 재시도한다
    (00-overview.md 6장 1항 — 서버 상시 실행 원칙)."""
    while True:
        try:
            await _stream_once()
        except asyncio.TimeoutError:
            continue  # 수신 없이 재구독 주기 도달 — 최신 coins 목록으로 즉시 재연결
        except Exception:
            logger.exception("Upbit 시세 스트림 연결 실패, %s초 후 재연결", RECONNECT_DELAY_SECONDS)
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)


async def run_market_data() -> None:
    """`market-data` 역할 진입점 — 리더로 선출된 프로세스만 스트림을 돌린다.

    리더를 못 잡은 프로세스는 대기하다가 주기적으로 다시 시도한다. 리더가 죽으면 세션이
    끊기며 락이 풀리므로 대기 중이던 프로세스가 다음 주기에 승격한다. 승격 전까지는 시세가
    갱신되지 않는데, 그 공백은 `price_cache`의 stale 방어가 "시세 없음"으로 막는다
    (02-market-data.md 3.3절 — 낡은 가격으로 손절·시장가 체결이 나가는 것보다 멈추는 게 낫다).
    """
    lock = leader.LeaderLock("market-data")
    while True:
        if not await asyncio.to_thread(lock.try_acquire):
            # 리더가 아니면 이 프로세스의 memory 캐시는 아무도 안 채운다.
            price_cache.warn_if_unfed("market-data 리더가 아니다")
            await asyncio.sleep(LEADER_RETRY_INTERVAL_SECONDS)
            continue

        logger.info("market-data 리더로 선출됐다 — Upbit 시세 스트림을 시작한다")
        stream_task = asyncio.create_task(run_price_stream())
        watchdog_task = asyncio.create_task(_watch_leadership(lock))
        try:
            # 스트림이 먼저 끝나면 스트림 자체가 죽은 것이고, 감시가 먼저 끝나면 리더십을
            # 잃은 것이다. 어느 쪽이든 리더 자리를 놓고 처음부터 다시 시작한다.
            await asyncio.wait(
                {stream_task, watchdog_task}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (stream_task, watchdog_task):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await asyncio.to_thread(lock.release)
        logger.warning("market-data 리더십이 끝났다 — 스트림을 멈추고 재선출을 기다린다")


async def _watch_leadership(lock: leader.LeaderLock) -> None:
    """리더십을 잃으면 반환한다 (03-worker-orchestration.md 2.2절 소유 재확인)."""
    while True:
        await asyncio.sleep(LEADERSHIP_CHECK_INTERVAL_SECONDS)
        if not await asyncio.to_thread(lock.is_held):
            return
