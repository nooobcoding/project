"""03-manual-trading Boundary 계층 — /ws/orderbook/{symbol}.

호가는 온디맨드로만 구독한다 (services/orderbook_stream.py, 00-overview.md 3장).
/ws/prices(02-dashboard)와 동일하게 인증 없이 연결을 받는다.
"""

from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy.orm import Session

from app.database import get_session
from app.services.coins import CoinNotFoundError, get_market_code
from app.services.orderbook_stream import proxy_orderbook

router = APIRouter(tags=["orderbook"])


@router.websocket("/ws/orderbook/{symbol}")
async def stream_orderbook(
    symbol: str, websocket: WebSocket, db: Session = Depends(get_session)
) -> None:
    try:
        market_code = get_market_code(db, symbol.upper())
    except CoinNotFoundError:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    await proxy_orderbook(websocket, market_code)
