"""services/price_cache.py 낡은 시세 방어 — docs-scale/02-market-data.md 3.3절.

**이 절은 설계가 한 번 틀렸다가 자기 정정된 곳이다.** 처음에는 "코인별 시세의 나이"로
판정했는데, Upbit ticker는 체결이 있을 때만 프레임을 보내므로 거래가 뜸한 코인은 스트림이
멀쩡해도 몇 분씩 갱신이 없다 — 그 설계로는 정상 상황에서 주문이 거부된다. 그래서 판정
기준을 "스트림이 살아 있는가"로 바꿨다. 그 정정이 코드에 실제로 반영돼 있는지를 여기서
고정한다. 되돌아가면 거래가 뜸한 코인부터 조용히 거래 불능이 된다.

두 번째 축은 **자금 경로와 표시 경로의 비대칭**이다. 같은 캐시를 읽어도 자금은 거부하고
화면은 마지막 값을 보여줘야 한다 — 한쪽으로 통일하면 둘 중 하나가 반드시 틀린다.
자금 경로가 실수로 `allow_stale=True`를 쓰면 낡은 가격으로 실제 돈이 움직이므로, 호출부를
글자로 훑지 않고 **행동으로** 확인한다.

두 백엔드(memory/redis) 모두에서 같은 단언이 돌도록 썼다 — 테스트 매트릭스가 구성을
바꿔가며 이 파일을 두 번 태운다.
"""

import json
import time
from decimal import Decimal

import pytest

from app.config import settings
from app.database import session_scope
from app.services import price_cache
from app.services.orders import PriceUnavailableError, create_order
from tests.conftest import requires_db

PRICE = 100000.0
FRESH = 1.0  # 갱신된 지 1초 — 어떤 기준으로도 신선하다
LONG_AGO = 9999.0  # 스트림이 확실히 끊긴 것으로 보이는 간격


def _write_heartbeat(seconds_ago: float) -> None:
    """스트림 생존 시각을 임의 시점으로 찍는다 (두 백엔드 공통)."""
    when = time.time() - seconds_ago
    if settings.price_cache_backend == "redis":
        price_cache.get_redis().set(price_cache.FEED_HEARTBEAT_KEY, when)
    else:
        price_cache._memory_last_tick_at = when


def _write_tick(symbol: str, trade_price: float, received_seconds_ago: float) -> None:
    """코인별 시세를 임의의 `received_at`으로 심는다.

    `set_price`는 항상 현재 시각을 찍으므로, "거래가 뜸해 자기 틱은 오래됐다"를 만들려면
    캐시에 직접 써야 한다.
    """
    payload = {
        "symbol": symbol,
        "trade_price": trade_price,
        "received_at": time.time() - received_seconds_ago,
    }
    if settings.price_cache_backend == "redis":
        price_cache.get_redis().set(price_cache._redis_key(symbol), json.dumps(payload))
    else:
        price_cache._memory_cache[symbol] = payload


@pytest.fixture
def feed_clock(test_coin):
    """스트림 생존 시각을 건드리는 테스트용 픽스처.

    **정리가 중요하다** — redis 백엔드에서 생존 시각은 스위트 전체가 공유하는 키 하나다.
    낡은 값을 남기고 나가면 뒤따르는 테스트의 자금 경로가 전부 "시세 없음"으로 거부되기
    시작한다. 이 테스트가 다른 테스트를 깨뜨리지 않도록 반드시 되돌린다.
    """
    yield
    _write_heartbeat(0)
    price_cache.delete_price(test_coin)


# ---------------------------------------------------------------- 자기 정정된 판정 기준


def test_thin_traded_coin_is_not_rejected_while_stream_is_alive(feed_clock, test_coin):
    """거래가 뜸해 자기 틱은 오래됐어도, 스트림이 살아 있으면 시세를 줘야 한다.

    이것이 3.3절이 자기 정정한 핵심이다 — 코인별 나이로 판정하던 옛 설계에서는 정상 상황의
    주문이 거부됐다.
    """
    _write_tick(test_coin, PRICE, received_seconds_ago=settings.price_max_age_seconds * 10)
    _write_heartbeat(FRESH)

    cached = price_cache.get_cached_price(test_coin)

    assert cached is not None, "스트림이 살아 있는데 거래가 뜸하다는 이유로 거부됐다"
    assert cached["trade_price"] == PRICE


def test_stale_feed_hides_even_a_freshly_received_tick(feed_clock, test_coin):
    """반대 방향 — 그 코인의 틱이 방금 들어왔어도 스트림 자체가 멈췄으면 접는다."""
    _write_tick(test_coin, PRICE, received_seconds_ago=FRESH)
    _write_heartbeat(LONG_AGO)

    assert price_cache.get_cached_price(test_coin) is None


def test_feed_never_fed_is_treated_as_stale(feed_clock, test_coin):
    """틱을 한 번도 못 받은 프로세스(생존 시각 0)는 "시세 없음"이어야 한다.

    0을 "아주 오래 전"이 아니라 "제한 없음"으로 읽으면 빈 캐시가 신선한 것으로 통과한다.
    """
    _write_tick(test_coin, PRICE, received_seconds_ago=FRESH)
    if settings.price_cache_backend == "redis":
        price_cache.get_redis().delete(price_cache.FEED_HEARTBEAT_KEY)
    else:
        price_cache._memory_last_tick_at = 0.0

    assert price_cache.get_cached_price(test_coin) is None


def test_feed_exactly_at_max_age_is_still_fresh(feed_clock, test_coin):
    """경계값 — 정확히 상한 나이면 아직 신선하다 (초과일 때만 접는다)."""
    _write_tick(test_coin, PRICE, received_seconds_ago=FRESH)
    _write_heartbeat(settings.price_max_age_seconds - 1)

    assert price_cache.get_cached_price(test_coin) is not None


# ---------------------------------------------------------------- 표시 경로 완화


def test_allow_stale_returns_last_value_when_feed_is_down(feed_clock, test_coin):
    """표시 경로는 스트림이 멈춰도 마지막 값을 본다 — 모르는 것을 숫자로 지어내지 않기 위해서다."""
    _write_tick(test_coin, PRICE, received_seconds_ago=FRESH)
    _write_heartbeat(LONG_AGO)

    assert price_cache.get_cached_price(test_coin) is None
    relaxed = price_cache.get_cached_price(test_coin, allow_stale=True)
    assert relaxed is not None and relaxed["trade_price"] == PRICE


def test_missing_symbol_is_none_even_with_allow_stale(feed_clock, test_coin):
    """완화는 "낡아도 준다"이지 "없어도 준다"가 아니다."""
    price_cache.delete_price(test_coin)
    _write_heartbeat(FRESH)

    assert price_cache.get_cached_price(test_coin, allow_stale=True) is None


# ---------------------------------------------------------------- 묶음 조회


def test_batch_read_drops_only_missing_symbols(feed_clock, test_coin):
    """여러 심볼을 읽을 때, 값이 없는 심볼만 빠지고 나머지는 정상적으로 나와야 한다."""
    _write_tick(test_coin, PRICE, received_seconds_ago=FRESH)
    _write_heartbeat(FRESH)

    result = price_cache.get_cached_prices([test_coin, "NOSUCHCOIN"])

    assert set(result) == {test_coin}


def test_batch_read_of_empty_list_is_empty(feed_clock):
    assert price_cache.get_cached_prices([]) == {}


def test_stale_feed_empties_the_whole_batch(feed_clock, test_coin):
    """스트림이 멈추면 묶음 조회도 통째로 비어야 한다 — 일부만 남으면 자금 경로가 통과한다."""
    _write_tick(test_coin, PRICE, received_seconds_ago=FRESH)
    _write_heartbeat(LONG_AGO)

    assert price_cache.get_cached_prices([test_coin]) == {}


# ---------------------------------------------------------------- Redis 장애·손상


@pytest.mark.redis
def test_corrupted_payload_is_treated_as_missing(feed_clock, test_coin):
    """값이 깨져 있으면 예외가 아니라 "시세 없음"으로 접힌다 (호출부가 500을 받으면 안 된다)."""
    if settings.price_cache_backend != "redis":
        pytest.skip("redis 백엔드 전용")

    price_cache.get_redis().set(price_cache._redis_key(test_coin), "{망가진 json")
    _write_heartbeat(FRESH)

    assert price_cache.get_cached_price(test_coin) is None


@pytest.mark.redis
def test_redis_failure_is_treated_as_missing_not_raised(monkeypatch, feed_clock, test_coin):
    """Redis가 아예 안 붙어도 예외를 올리지 않고 "시세 없음"으로 접는다."""
    if settings.price_cache_backend != "redis":
        pytest.skip("redis 백엔드 전용")

    def _boom():
        raise ConnectionError("redis 연결 실패")

    monkeypatch.setattr(price_cache, "get_redis", _boom)

    assert price_cache.get_cached_price(test_coin) is None
    assert price_cache.get_cached_prices([test_coin]) == {}

    # feed_clock의 정리도 redis를 쓰므로, 픽스처 해제 순서에 기대지 않고 여기서 되돌린다.
    monkeypatch.undo()


@pytest.mark.redis
def test_write_failure_does_not_raise(monkeypatch, feed_clock, test_coin):
    """쓰기 실패도 조용히 접고 다음 틱에 재시도한다 — 시세 루프가 죽으면 안 된다."""
    if settings.price_cache_backend != "redis":
        pytest.skip("redis 백엔드 전용")

    def _boom():
        raise ConnectionError("redis 연결 실패")

    monkeypatch.setattr(price_cache, "get_redis", _boom)

    price_cache.set_price(test_coin, {"symbol": test_coin, "trade_price": PRICE})

    monkeypatch.undo()


# ---------------------------------------------------------------- 자금 경로 vs 표시 경로


@requires_db
def test_stale_feed_rejects_market_order_but_still_shows_portfolio(
    feed_clock, test_user, test_coin, set_price
):
    """같은 낡은 캐시를 두고 자금 경로는 거부하고 표시 경로는 값을 보여줘야 한다.

    호출부가 `allow_stale`을 잘못 고르면 (자금 경로에 True를 쓰면) 낡은 가격으로 실제 돈이
    움직인다. 글자로 훑는 대신 두 경로의 **행동 차이**로 확인한다.
    """
    set_price(Decimal(str(PRICE)))

    # 먼저 보유분을 만들어 둔다 (스트림이 살아 있는 동안).
    with session_scope() as db:
        create_order(
            db,
            user_id=test_user,
            coin_symbol=test_coin,
            side="buy",
            order_type="market",
            quantity=Decimal("0.1"),
            source="manual",
        )

    _write_heartbeat(LONG_AGO)

    # 자금 경로: 시장가 주문이 거부된다.
    with pytest.raises(PriceUnavailableError):
        with session_scope() as db:
            create_order(
                db,
                user_id=test_user,
                coin_symbol=test_coin,
                side="buy",
                order_type="market",
                quantity=Decimal("0.1"),
                source="manual",
            )

    # 표시 경로: 마지막 값으로 평가금액이 계속 나온다.
    from app.services import portfolio

    with session_scope() as db:
        holdings = portfolio.list_holdings(db, test_user)

    assert holdings, "표시 경로가 보유 목록을 비워버렸다"
    row = next(h for h in holdings if h["coin_symbol"] == test_coin)
    assert Decimal(row["current_price"]) == Decimal(str(PRICE)), (
        "표시 경로가 낡은 시세를 버리고 매수평단으로 되돌아갔다"
    )
