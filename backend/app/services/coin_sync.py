"""coins 마스터 동기화 잡 (00-overview.md 7장 로드맵 0번, 01-erd.md `coins`).

Upbit `/v1/market/all`에서 KRW 마켓 목록을 가져와 coins 테이블을 갱신한다.
앱 기동 시 1회 + 매일 1회(main.py의 스케줄러) 실행된다.
"""

from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.database import session_scope
from app.models import Coin
from app.services import rate_limit

UPBIT_MARKET_ALL_URL = "https://api.upbit.com/v1/market/all"


def fetch_krw_markets() -> list[dict]:
    """Upbit 전체 마켓 목록에서 KRW 마켓만 필터링해 반환한다.

    하루 한 번뿐이지만 토큰 버킷을 거친다 — Upbit 레이트리밋은 엔드포인트가 아니라 IP
    단위라, 예외를 하나 두면 "총량을 아는 주체가 하나"라는 6단계의 전제가 깨진다
    (04-async-jobs.md 3.1절 표).
    """
    with rate_limit.priority("high"):
        rate_limit.acquire()
    response = httpx.get(UPBIT_MARKET_ALL_URL, params={"isDetails": "false"}, timeout=10.0)
    if response.status_code == 429:
        rate_limit.note_throttled()
    response.raise_for_status()
    markets = response.json()
    return [market for market in markets if market["market"].startswith("KRW-")]


def sync_coins() -> None:
    """coins 테이블을 최신 Upbit KRW 마켓 목록으로 갱신한다.

    신규 마켓은 삽입하고 기존 마켓은 이름·활성 상태를 갱신한다. 응답에 더 이상
    없는 기존 심볼은 상장폐지로 간주해 is_active=False로 전환한다 (01-erd.md `coins`).
    """
    krw_markets = fetch_krw_markets()
    fetched_symbols = {market["market"].removeprefix("KRW-") for market in krw_markets}
    now = datetime.now(timezone.utc)

    with session_scope() as db:
        existing_coins = {coin.symbol: coin for coin in db.scalars(select(Coin))}

        for market in krw_markets:
            symbol = market["market"].removeprefix("KRW-")
            coin = existing_coins.get(symbol)
            if coin is None:
                coin = Coin(symbol=symbol)
                db.add(coin)
            coin.market_code = market["market"]
            coin.korean_name = market["korean_name"]
            coin.english_name = market["english_name"]
            coin.is_active = True
            coin.updated_at = now

        for symbol, coin in existing_coins.items():
            if symbol not in fetched_symbols and coin.is_active:
                coin.is_active = False
                coin.updated_at = now
