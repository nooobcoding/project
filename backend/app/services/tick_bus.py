"""틱 전달 — 수신한 시세 틱을 프론트(`/ws/prices`) 구독자에게 보낸다.

지금까지는 시세 수신 루프가 같은 프로세스의 WebSocket 구독자에게 직접 넣어줬다. 확장판
4단계부터는 `market-data`와 `api`가 다른 프로세스일 수 있으므로 전달 경로가 둘로 갈린다
(docs-scale/02-market-data.md 6장).

| PRICE_CACHE_BACKEND | 전달 경로 |
|---|---|
| `memory` | 이 프로세스의 구독자에게 직접 — 지금까지와 동일 |
| `redis` | `ticks:{symbol}`로 발행 → **각 api 프로세스가** 구독해 자기 클라이언트에게 전달 |

`register()`/`unregister()`의 계약은 그대로다 — 라우터는 어느 경로로 오는지 몰라도 된다.
클라이언트가 어느 api 프로세스에 붙을지 모르므로, 구독 심볼 집합은 붙어 있는 클라이언트에
맞춰 구독 루프가 주기적으로 맞춰 나간다.

**호가(orderbook_stream.py)는 여기 해당 없다** — 이미 사용자가 보고 있는 심볼만 온디맨드로
구독하는 클라이언트 범위 상태라, 프로세스별로 각자 구독해도 정상 동작한다 (같은 문서 6장).
"""

import asyncio
import contextlib
import json
import logging

from fastapi import WebSocket

from app.config import settings
from app.services.redis_client import create_async_redis, get_redis

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "ticks:"
# 구독 심볼 집합을 다시 맞추는 주기. 클라이언트가 접속한 뒤 이 시간 안에 구독이 붙는다.
# 접속 직후 현재가는 라우터가 캐시에서 한 번 직접 보내주므로(routers/prices.py) 이 지연이
# 화면의 첫 표시를 늦추지는 않는다.
_SUBSCRIPTION_POLL_SECONDS = 0.5
_RECONNECT_DELAY_SECONDS = 5

_subscribers: dict[WebSocket, tuple[set[str], "asyncio.Queue[dict]"]] = {}


def _channel(symbol: str) -> str:
    return f"{CHANNEL_PREFIX}{symbol}"


def _symbol_of(channel: str) -> str:
    return channel.removeprefix(CHANNEL_PREFIX)


async def register(websocket: WebSocket, symbols: set[str]) -> "asyncio.Queue[dict]":
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers[websocket] = (symbols, queue)
    return queue


def unregister(websocket: WebSocket) -> None:
    _subscribers.pop(websocket, None)


def watched_symbols() -> set[str]:
    """이 프로세스에 붙은 클라이언트들이 보고 있는 심볼 전체."""
    return {symbol for symbols, _ in _subscribers.values() for symbol in symbols}


async def publish(symbol: str, tick: dict) -> None:
    """틱 하나를 프론트로 흘려보낸다. `market-data` 역할(price_stream.py)이 호출한다."""
    if settings.price_cache_backend == "redis":
        # redis 발행은 동기 소켓 I/O다 — 시세 수신 루프를 막지 않도록 스레드로 넘긴다.
        await asyncio.to_thread(_publish_to_redis, symbol, tick)
    else:
        await deliver_local(symbol, tick)


def _publish_to_redis(symbol: str, tick: dict) -> None:
    try:
        get_redis().publish(_channel(symbol), json.dumps(tick))
    except Exception:
        # 틱 발행 실패는 화면 갱신이 한 번 빠지는 것뿐이다(자금 경로는 시세 캐시를 읽는다).
        # 다음 틱에 다시 발행되므로 로그만 남기고 넘어간다.
        logger.warning("틱 발행 실패 (symbol=%s)", symbol)


async def deliver_local(symbol: str, tick: dict) -> None:
    """이 프로세스에 붙은 구독자에게 전달한다. 이벤트 루프에서만 호출할 것 —
    `asyncio.Queue`는 스레드 안전하지 않다."""
    for symbols, queue in list(_subscribers.values()):
        if symbol in symbols:
            await queue.put(tick)


async def run_tick_subscriber() -> None:
    """`api` 역할 — `ticks:{symbol}`을 구독해 자기 클라이언트에게 팬아웃한다.

    구독 대상은 붙어 있는 클라이언트에 따라 계속 바뀌므로, 이 루프 하나가 pubsub 객체를
    독점하면서 매 주기 "구독해야 할 집합"과 현재 구독을 맞춘다. `listen()` 대신
    `get_message()`로 도는 이유가 이것이다 — 다른 태스크가 같은 pubsub에 구독을 추가하는
    구조를 만들지 않기 위해서다.
    """
    while True:
        client = create_async_redis()
        pubsub = client.pubsub()
        subscribed: set[str] = set()
        try:
            while True:
                subscribed = await _sync_subscriptions(pubsub, subscribed)
                if not subscribed:
                    # 구독이 하나도 없으면 pubsub 연결 자체가 없다 — 붙은 클라이언트가
                    # 생길 때까지 폴링만 한다.
                    await asyncio.sleep(_SUBSCRIPTION_POLL_SECONDS)
                    continue
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=_SUBSCRIPTION_POLL_SECONDS
                )
                if message is not None:
                    await _deliver_message(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("틱 구독 실패, %s초 후 재연결", _RECONNECT_DELAY_SECONDS)
            await asyncio.sleep(_RECONNECT_DELAY_SECONDS)
        finally:
            with contextlib.suppress(Exception):
                await pubsub.aclose()
            with contextlib.suppress(Exception):
                await client.aclose()


async def _sync_subscriptions(pubsub, subscribed: set[str]) -> set[str]:
    """현재 구독을 클라이언트들이 보고 있는 심볼 집합에 맞춘다."""
    desired = watched_symbols()
    added = desired - subscribed
    removed = subscribed - desired
    if added:
        await pubsub.subscribe(*(_channel(symbol) for symbol in added))
    if removed:
        await pubsub.unsubscribe(*(_channel(symbol) for symbol in removed))
    return desired


async def _deliver_message(message: dict) -> None:
    try:
        tick = json.loads(message["data"])
    except (TypeError, ValueError):
        logger.warning("틱 메시지 파싱 실패 (channel=%s)", message.get("channel"))
        return
    await deliver_local(_symbol_of(message["channel"]), tick)
