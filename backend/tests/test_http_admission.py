"""HTTP 입장 제한 (app/http_admission.py).

부하 측정에서 원래 구성이 동시 사용자 25명에 무너진 원인을 작은 모형으로 재현한다:
커넥션 2개짜리 "풀", 그 커넥션을 요청 끝까지 쥐는 동기 의존성, 동기 엔드포인트, 그리고 스레드
수(40)보다 많은 동시 요청. 입장 제한이 없으면 스레드가 전부 커넥션을 기다리고 커넥션은 전부
스레드를 기다리는 요청들이 쥐어 멈춘다.
"""

import asyncio
import threading
import time

import httpx
import pytest
from fastapi import Depends, FastAPI

from app.http_admission import BUSY_MESSAGE, AdmissionMiddleware

POOL_SIZE = 2
CONCURRENT_REQUESTS = 60  # anyio 기본 스레드 수(40)보다 많아야 고리가 생긴다
POOL_TIMEOUT = 3.0


def _model_app(with_admission: bool) -> FastAPI:
    pool = threading.BoundedSemaphore(POOL_SIZE)

    def get_connection():
        # SQLAlchemy 세션처럼: 스레드에서 커넥션을 잡고, 요청이 끝날 때까지 놓지 않는다
        if not pool.acquire(timeout=POOL_TIMEOUT):
            raise TimeoutError("QueuePool limit reached")
        try:
            yield
        finally:
            pool.release()

    def current_user(_=Depends(get_connection)):
        return "user"

    app = FastAPI()

    @app.get("/work")
    def work(_user=Depends(current_user), _conn=Depends(get_connection)):
        time.sleep(0.005)
        return {"ok": True}

    if with_admission:
        app.add_middleware(AdmissionMiddleware, limit=POOL_SIZE, wait_seconds=30)
    return app


async def _blast(app: FastAPI) -> tuple[int, float]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
        started = time.monotonic()
        responses = await asyncio.gather(*(client.get("/work") for _ in range(CONCURRENT_REQUESTS)))
        return sum(r.status_code == 200 for r in responses), time.monotonic() - started


@pytest.mark.slow
def test_without_admission_the_model_stalls_until_pool_timeout():
    """대조군 — 이 모형이 실제로 그 고리를 만드는지부터 확인한다. 안 멈추면 아래 테스트는 무의미하다."""
    ok, elapsed = asyncio.run(_blast(_model_app(with_admission=False)))

    assert ok < CONCURRENT_REQUESTS or elapsed >= POOL_TIMEOUT, (
        f"입장 제한 없이도 멈추지 않았다 ({ok}건 성공, {elapsed:.1f}초) — 모형이 고리를 재현하지 못한다"
    )


@pytest.mark.slow
def test_with_admission_every_request_completes_quickly():
    ok, elapsed = asyncio.run(_blast(_model_app(with_admission=True)))

    assert ok == CONCURRENT_REQUESTS
    assert elapsed < POOL_TIMEOUT, f"{elapsed:.1f}초 — 풀 대기 한도까지 막혔다"


# ---------------------------------------------------------------- 미들웨어 단위 동작


def _counting_app():
    state = {"current": 0, "peak": 0, "release": asyncio.Event()}

    async def app(scope, receive, send):
        state["current"] += 1
        state["peak"] = max(state["peak"], state["current"])
        await state["release"].wait()
        state["current"] -= 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return app, state


async def _call(middleware, scope_type="http"):
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    await middleware({"type": scope_type}, receive, send)
    return sent


def test_in_flight_requests_never_exceed_the_limit():
    async def scenario():
        app, state = _counting_app()
        middleware = AdmissionMiddleware(app, limit=3, wait_seconds=5)
        tasks = [asyncio.create_task(_call(middleware)) for _ in range(10)]
        await asyncio.sleep(0.05)
        assert state["current"] == 3  # 나머지 7개는 이벤트 루프에서 기다린다
        state["release"].set()
        results = await asyncio.gather(*tasks)
        return state["peak"], results

    peak, results = asyncio.run(scenario())

    assert peak == 3
    assert all(r[0]["status"] == 200 for r in results)


def test_waiting_too_long_returns_503_with_a_message():
    async def scenario():
        app, state = _counting_app()
        middleware = AdmissionMiddleware(app, limit=1, wait_seconds=0.05)
        holder = asyncio.create_task(_call(middleware))
        await asyncio.sleep(0.01)
        rejected = await _call(middleware)
        state["release"].set()
        await holder
        return rejected

    rejected = asyncio.run(scenario())

    assert rejected[0]["status"] == 503
    assert BUSY_MESSAGE.encode() in rejected[1]["body"]


def test_websockets_are_not_counted():
    """웹소켓은 연결 내내 열려 있다 — 세면 호가창 몇 개로 HTTP 입장이 막힌다."""

    async def scenario():
        app, state = _counting_app()
        middleware = AdmissionMiddleware(app, limit=1, wait_seconds=0.05)
        sockets = [asyncio.create_task(_call(middleware, "websocket")) for _ in range(3)]
        await asyncio.sleep(0.01)
        current = state["current"]
        state["release"].set()
        await asyncio.gather(*sockets)
        return current

    assert asyncio.run(scenario()) == 3
