"""02-dashboard 시세 스트림 — Upbit 공개 시세 WebSocket을 상시 구독해 시세 캐시를 갱신한다.

00-overview.md 3장의 "시세 캐시" 갱신 주체다. 클라이언트 접속 여부와 무관하게 항상
갱신되어야 하므로(체결 엔진·자동매매 손절/익절이 이 캐시를 쓰는 09/07의 전제),
main.py의 lifespan에서 앱 기동과 함께 백그라운드 태스크로 시작한다. `/ws/prices`는
이 캐시의 소비자일 뿐 Upbit 구독 대상을 결정하지 않는다.

캐시 저장소 자체는 services/price_cache.py로 분리돼 있다 (확장판 02-market-data.md 5장)
— 이 모듈은 그 캐시에 쓰기만 하고, 읽기(get_cached_price)는 그쪽 모듈이 맡는다.
"""

import asyncio
import json
import logging
import uuid
from decimal import Decimal
from typing import Iterable

import websockets
from fastapi import WebSocket
from sqlalchemy import select

from app.database import session_scope
from app.models import Coin
from app.services import matcher, price_cache

logger = logging.getLogger(__name__)

UPBIT_TICKER_WS_URL = "wss://api.upbit.com/websocket/v1"
RECONNECT_DELAY_SECONDS = 5
RESUBSCRIBE_INTERVAL_SECONDS = 300  # coins 동기화 잡 반영 주기 (00-overview.md 3장)

_subscribers: dict[WebSocket, tuple[set[str], "asyncio.Queue[dict]"]] = {}


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


async def _fan_out(symbol: str, tick: dict) -> None:
    for symbols, queue in list(_subscribers.values()):
        if symbol in symbols:
            await queue.put(tick)


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
            # memory 백엔드는 dict 대입이라 즉시 반환하지만, redis 백엔드는 소켓 I/O라
            # 이 상시 루프를 막을 수 있다 — to_thread로 감싼다 (아래 매칭 훅과 동일 원칙).
            await asyncio.to_thread(price_cache.set_price, symbol, tick)
            await _fan_out(symbol, tick)
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


async def register(websocket: WebSocket, symbols: set[str]) -> "asyncio.Queue[dict]":
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers[websocket] = (symbols, queue)
    return queue


def unregister(websocket: WebSocket) -> None:
    _subscribers.pop(websocket, None)
