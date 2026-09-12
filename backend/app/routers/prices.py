"""02-dashboard Boundary 계층 — /ws/prices.

시세 캐시(services/price_cache.py)의 소비자일 뿐이다. 백엔드의 Upbit 구독 자체는
이 엔드포인트의 접속 여부와 무관하게 항상 유지된다 (00-overview.md 3장).

틱이 같은 프로세스의 시세 스트림에서 오는지 다른 프로세스가 발행한 `ticks:{symbol}`에서
오는지는 services/tick_bus.py가 감춘다 — 이 라우터는 몰라도 된다 (확장판 02-market-data.md
6장).
"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import price_cache, tick_bus

router = APIRouter(tags=["prices"])


@router.websocket("/ws/prices")
async def stream_prices(websocket: WebSocket) -> None:
    symbols = {
        symbol.strip().upper()
        for symbol in websocket.query_params.get("symbols", "").split(",")
        if symbol.strip()
    }
    await websocket.accept()

    # 대시보드는 접속 한 번에 상장 심볼 전체를 요청한다 — 심볼마다 조회하면 그 수만큼
    # Redis 왕복과 스레드 전환이 생기므로 한 번에 묶어 읽는다. redis 백엔드에서는 소켓
    # I/O라 이벤트 루프를 막지 않도록 스레드로 감싼다.
    cached_prices = await asyncio.to_thread(price_cache.get_cached_prices, symbols)
    for cached in cached_prices.values():
        await websocket.send_json(cached)

    queue = await tick_bus.register(websocket, symbols)
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
        tick_bus.unregister(websocket)
