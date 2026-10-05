"""HTTP 요청 입장 제한 — 동시에 처리 중인 요청 수를 DB 커넥션 수 이하로 묶는다.

**왜 필요한가 (부하 측정에서 발견, docs-scale/08-capacity.md).** 원래 단일 프로세스 구성이
동시 사용자 25명에서 무너졌다 — p95가 정확히 30초(풀 대기 한도)였고 절반이 실패했다.
CPU도 DB도 한가했다. 원인은 요청 하나가 **두 단계로 나뉘어 스레드를 탄다**는 데 있다:

  1. 인증 의존성(`get_current_user`)이 스레드에서 돌며 세션의 커넥션을 잡고 **스레드만 반납한다**
     (세션은 요청 끝까지 산다 — pg_stat_activity에 `idle in transaction`으로 쌓여 있었다)
  2. 엔드포인트 본문이 다시 스레드 슬롯(프로세스당 40개)을 기다린다

동시 요청이 커넥션 수를 넘으면 스레드 40개가 전부 "커넥션 대기"로 차고, 커넥션은 전부
"스레드 대기" 중인 요청들이 쥔다. 서로를 기다리며 풀 대기 한도(30초)가 끝날 때까지 멈춘다.

처리 중인 요청 수가 커넥션 수를 넘지 않으면 요청은 커넥션을 반드시 바로 얻으므로 스레드가
풀에서 기다릴 일이 없고, 그 고리가 생기지 않는다. 넘치는 요청은 이벤트 루프에서 기다린다 —
스레드도 커넥션도 쥐지 않은 채로. 풀 크기를 키우는 것으로는 안 된다: 처리 중 요청 수에는
상한이 없어서 확률만 낮출 뿐이다.

웹소켓은 세지 않는다 — 연결 내내 열려 있어 세면 금방 입장이 막히고, DB를 붙잡지 않게
만들어 두었다 (routers/orderbook.py).
"""

import asyncio
import json

from app.config import settings

# 같은 프로세스에서 api 말고 다른 역할(워커 tick·matcher·스케줄러 잡·시세 루프)도 같은 풀을
# 쓴다. 그 몫을 남겨 두지 않으면 요청이 풀을 다 채운 순간 그쪽이 풀에서 기다린다.
BACKGROUND_RESERVE = 5

BUSY_MESSAGE = "요청이 많아 처리하지 못했습니다. 잠시 후 다시 시도해주세요."


def default_limit() -> int:
    """설정이 없으면 풀 용량에서 다른 역할 몫을 뺀 값."""
    if settings.http_max_in_flight > 0:
        return settings.http_max_in_flight
    capacity = settings.db_pool_size + settings.db_max_overflow
    reserve = 0 if set(settings.process_roles) == {"api"} else BACKGROUND_RESERVE
    return max(1, capacity - reserve)


class AdmissionMiddleware:
    """순수 ASGI 미들웨어 — 응답을 스트리밍하는 엔드포인트(CSV 내보내기)도 끝날 때까지 센다."""

    def __init__(self, app, limit: int | None = None, wait_seconds: float | None = None) -> None:
        self.app = app
        self.limit = limit if limit is not None else default_limit()
        self.wait_seconds = (
            wait_seconds if wait_seconds is not None else settings.http_admission_wait_seconds
        )
        self._semaphore: asyncio.Semaphore | None = None

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 세마포어는 이벤트 루프에 묶이므로 첫 요청 때 만든다 (모듈 임포트 시점에는 루프가 없다)
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.limit)

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.wait_seconds)
        except TimeoutError:
            # 줄이 너무 길면 기다리게 두지 않고 바로 돌려보낸다 — 클라이언트 타임아웃까지
            # 붙잡혀 있다가 실패하는 것보다 빨리 실패하는 편이 낫다
            await _send_busy(send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            self._semaphore.release()


async def _send_busy(send) -> None:
    body = json.dumps({"detail": BUSY_MESSAGE}, ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 503,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"retry-after", b"1"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
