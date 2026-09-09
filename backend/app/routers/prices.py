"""02-dashboard Boundary 계층 — /ws/prices.

시세 캐시(services/price_stream.py)의 소비자일 뿐이다. 백엔드의 Upbit 구독 자체는
이 엔드포인트의 접속 여부와 무관하게 항상 유지된다 (00-overview.md 3장).
"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import price_stream

router = APIRouter(tags=["prices"])


@router.websocket("/ws/prices")
async def stream_prices(websocket: WebSocket) -> None:
    symbols = {
        symbol.strip().upper()
        for symbol in websocket.query_params.get("symbols", "").split(",")
        if symbol.strip()
    }
    await websocket.accept()

    for symbol in symbols:
        cached = price_stream.get_cached_price(symbol)
        if cached is not None:
            await websocket.send_json(cached)

    queue = await price_stream.register(websocket, symbols)
    try:
        while True:
            receive_task = asyncio.ensure_future(websocket.receive_text())
            queue_task = asyncio.ensure_future(queue.get())
            done, pending = await asyncio.wait(
                {receive_task, queue_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if queue_task in done:
                await websocket.send_json(queue_task.result())
            if receive_task in done:
                receive_task.result()  # 클라이언트 메시지는 무시. 연결 종료 시 여기서 WebSocketDisconnect 발생
    except WebSocketDisconnect:
        pass
    finally:
        price_stream.unregister(websocket)
