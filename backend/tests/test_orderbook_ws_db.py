"""호가 웹소켓이 열려 있는 동안 DB 커넥션을 쥐지 않는다 (routers/orderbook.py).

예전에는 `Depends(get_session)`으로 받은 세션이 웹소켓이 닫힐 때까지 살아, 호가창 탭 하나가
커넥션 하나를 계속 묶었다. 풀(5+10)이면 탭 15개로 HTTP 요청 전체가 멈춘다.
"""

import threading

import pytest

from app.database import get_engine
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
def held_open(monkeypatch):
    """Upbit에 붙지 않고, 테스트가 놓아줄 때까지 웹소켓을 열어 둔다."""
    from app.routers import orderbook

    release = threading.Event()

    async def fake_proxy(websocket, market_code):
        await websocket.send_text(market_code)
        while not release.is_set():
            import asyncio

            await asyncio.sleep(0.01)

    monkeypatch.setattr(orderbook, "proxy_orderbook", fake_proxy)
    yield release
    release.set()


def test_open_orderbook_socket_holds_no_db_connection(client, test_coin, held_open):
    pool = get_engine().pool
    before = pool.checkedout()

    with client.websocket_connect(f"/ws/orderbook/{test_coin}") as socket:
        assert socket.receive_text() == f"KRW-{test_coin}"  # 조회는 됐다
        assert pool.checkedout() == before, "웹소켓이 열려 있는 동안 커넥션을 쥐고 있다"
        held_open.set()


def test_unknown_symbol_is_rejected(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws/orderbook/NOPE404") as socket:
            socket.receive_text()
    assert closed.value.code == 4404
