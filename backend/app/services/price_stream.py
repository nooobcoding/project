"""02-dashboard 시세 스트림 — Upbit 공개 시세 WebSocket을 상시 구독해 메모리 캐시를 유지한다.

00-overview.md 3장의 "시세 캐시" 그 자체다. 클라이언트 접속 여부와 무관하게 항상
갱신되어야 하므로(체결 엔진·자동매매 손절/익절이 이 캐시를 쓰게 될 09/07의 전제),
main.py의 lifespan에서 앱 기동과 함께 백그라운드 태스크로 시작한다. `/ws/prices`는
이 캐시의 소비자일 뿐 Upbit 구독 대상을 결정하지 않는다.
"""

import asyncio
import json
import logging
import uuid
from typing import Iterable

import websockets
from fastapi import WebSocket
from sqlalchemy import select

from app.database import session_scope
from app.models import Coin

logger = logging.getLogger(__name__)

UPBIT_TICKER_WS_URL = "wss://api.upbit.com/websocket/v1"
RECONNECT_DELAY_SECONDS = 5
RESUBSCRIBE_INTERVAL_SECONDS = 300  # coins 동기화 잡 반영 주기 (00-overview.md 3장)

_price_cache: dict[str, dict] = {}
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
        "change": message["change"],
        "signed_change_rate": message["signed_change_rate"],
        "prev_closing_price": message["prev_closing_price"],
        "timestamp": message["timestamp"],
    }


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
            _price_cache[symbol] = tick
            await _fan_out(symbol, tick)


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


def get_cached_price(symbol: str) -> dict | None:
    return _price_cache.get(symbol)
