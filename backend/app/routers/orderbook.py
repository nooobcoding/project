"""03-manual-trading Boundary 계층 — /ws/orderbook/{symbol}.

호가는 온디맨드로만 구독한다 (services/orderbook_stream.py, 00-overview.md 3장).
/ws/prices(02-dashboard)와 동일하게 인증 없이 연결을 받는다.

**DB 세션을 의존성으로 받지 않는다.** 예전에는 `Depends(get_session)`이었는데, 의존성 세션은
엔드포인트가 끝날 때 닫히고 이 엔드포인트는 호가창이 열려 있는 **내내** 끝나지 않는다. 마켓
코드 한 번 조회하려고 잡은 커넥션을 탭이 닫힐 때까지 쥐고 있어서, 호가창 15개면 풀(5+10)이
통째로 묶였다. 조회만 짧은 세션으로 하고 바로 돌려준다.
"""

import asyncio

from fastapi import APIRouter, WebSocket

from app.database import session_scope
from app.services.coins import CoinNotFoundError, get_market_code
from app.services.orderbook_stream import proxy_orderbook

router = APIRouter(tags=["orderbook"])


def _lookup_market_code(symbol: str) -> str:
    with session_scope() as db:
        return get_market_code(db, symbol)


@router.websocket("/ws/orderbook/{symbol}")
async def stream_orderbook(symbol: str, websocket: WebSocket) -> None:
    try:
        # 동기 DB 조회를 이벤트 루프에서 직접 하지 않는다 — 그동안 다른 웹소켓·요청이 멈춘다
        market_code = await asyncio.to_thread(_lookup_market_code, symbol.upper())
    except CoinNotFoundError:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    await proxy_orderbook(websocket, market_code)
