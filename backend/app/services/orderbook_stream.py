"""03-manual-trading Control 계층 — 호가(orderbook) 온디맨드 프록시.

price_stream.py의 상시 캐시와 달리, 호가는 데이터량이 커서 상시 구독 대상에
포함하지 않고 사용자가 보고 있는 심볼만 그때그때 Upbit에 구독한다
(00-overview.md 3장, 03-manual-trading.md 6장). 프론트 연결 1개당 Upbit 연결 1개를
새로 맺는 단순한 1:1 프록시다.
"""

import json
import logging
import uuid

import websockets
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

UPBIT_WS_URL = "wss://api.upbit.com/websocket/v1"


def _build_subscribe_frame(market_code: str) -> str:
    return json.dumps(
        [
            {"ticket": str(uuid.uuid4())},
            {"type": "orderbook", "codes": [market_code]},
            {"format": "DEFAULT"},
        ]
    )


async def proxy_orderbook(websocket: WebSocket, market_code: str) -> None:
    """Upbit 호가 WS를 구독해 들어오는 메시지를 그대로 클라이언트에 중계한다."""
    try:
        async with websockets.connect(UPBIT_WS_URL) as upstream:
            await upstream.send(_build_subscribe_frame(market_code))
            while True:
                raw = await upstream.recv()
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                await websocket.send_json(json.loads(raw))
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("호가 프록시 연결 실패 (market_code=%s)", market_code)
