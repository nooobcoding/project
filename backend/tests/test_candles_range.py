"""기간 지정 캔들 조회 검증 (06 계획 Phase C).

실제 Upbit를 부르지 않고 `_fetch_upbit_candles`를 가짜로 바꿔 **몇 번, 어떤 커서로** 호출했는지를
직접 본다 — 이 기능의 핵심 요구가 "캐시에 있으면 외부 호출 0"이기 때문이다. 캐시는 실제
postgres의 `candles` 테이블을 쓴다(`UNIQUE (coin_symbol, interval, opened_at)` 위에서 upsert가
동작하는지가 캐시 정확성의 전제라 SQLite로 대체할 수 없다).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.database import session_scope
from app.services import candles as candles_service
from app.services.candles import (
    CandleRangeTooLongError,
    CoinNotFoundError,
    InvalidCandleRangeError,
    get_candles_in_range,
)

from .conftest import TEST_COIN_SYMBOL, requires_db

pytestmark = requires_db

DAY = timedelta(days=1)
LISTED_AT = datetime(2025, 1, 1, tzinfo=timezone.utc)


class FakeUpbit:
    """Upbit 캔들 REST 대역 — `to` 이전 캔들을 최신순 `count`개 준다 (실제 API와 같은 계약).

    `listed_at` 이전은 데이터가 없으므로 빈 목록을 준다 — 상장 이전 구간을 요청했을 때 실제
    Upbit가 하는 동작이고, 페이지네이션 루프가 여기서 멈추는지 확인하는 데 쓴다.
    """

    def __init__(self, interval: str = "1d", listed_at: datetime = LISTED_AT) -> None:
        self.interval = interval
        self.listed_at = listed_at
        self.calls: list[datetime | None] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def __call__(self, market_code: str, interval: str, count: int, to: datetime | None = None):
        self.calls.append(to)
        step = timedelta(seconds=candles_service._INTERVAL_SECONDS[interval])
        newest = (to - step) if to is not None else candles_service._current_bucket_start(
            interval, datetime.now(timezone.utc)
        )

        raw = []
        opened_at = newest
        while len(raw) < count and opened_at >= self.listed_at:
            raw.append(self._raw(opened_at))
            opened_at -= step
        return raw

    @staticmethod
    def _raw(opened_at: datetime) -> dict:
        # 가격은 날짜에서 결정적으로 만든다 — 어떤 봉이 왔는지 값으로 되짚을 수 있게.
        price = 1000 + opened_at.toordinal() % 100
        return {
            "candle_date_time_utc": opened_at.strftime("%Y-%m-%dT%H:%M:%S"),
            "opening_price": price,
            "high_price": price + 10,
            "low_price": price - 10,
            "trade_price": price,
            "candle_acc_trade_volume": 1.5,
        }


@pytest.fixture
def fake_upbit(monkeypatch, test_coin):
    """가짜 Upbit를 붙이고, 테스트가 끝나면 이 코인의 캔들 캐시를 지운다."""
    fake = FakeUpbit()
    monkeypatch.setattr(candles_service, "_fetch_upbit_candles", fake)
    monkeypatch.setattr(candles_service, "_FETCH_DELAY_SECONDS", 0)  # 레이트리밋 대기 생략

    _clear_candles()
    yield fake
    _clear_candles()


def _clear_candles() -> None:
    with session_scope() as db:
        db.execute(
            text("DELETE FROM candles WHERE coin_symbol = :symbol"), {"symbol": TEST_COIN_SYMBOL}
        )


def fetch(start: datetime, end: datetime, interval: str = "1d"):
    with session_scope() as db:
        return [
            (candle.opened_at, candle.close)
            for candle in get_candles_in_range(db, TEST_COIN_SYMBOL, interval, start, end)
        ]


def seed_cache(*opened_ats: datetime, interval: str = "1d") -> None:
    """Upbit를 거치지 않고 캐시에 직접 캔들을 심는다 (캐시 히트 상황을 만들기 위함)."""
    with session_scope() as db:
        candles_service._upsert_candles(
            db, TEST_COIN_SYMBOL, interval, [FakeUpbit._raw(opened_at) for opened_at in opened_ats]
        )


# ── 기본 조회 ──────────────────────────────────────────────────────────────


def test_fetches_full_range_when_cache_is_empty(fake_upbit):
    start, end = datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 10, tzinfo=timezone.utc)

    result = fetch(start, end)

    assert [opened_at for opened_at, _ in result] == [start + DAY * offset for offset in range(10)]
    assert fake_upbit.call_count == 1


def test_paginates_backward_with_to_cursor(fake_upbit):
    """200봉을 넘는 기간은 여러 페이지로 나눠 받는다 — 커서가 과거로 전진해야 한다."""
    end = datetime(2026, 6, 1, tzinfo=timezone.utc)
    start = end - DAY * 449  # 450봉 = 3페이지 (200 + 200 + 50)

    result = fetch(start, end)

    assert len(result) == 450
    assert fake_upbit.call_count == 3
    # 첫 호출은 end 다음 봉(exclusive 기준), 이후 커서는 계속 과거로 내려간다.
    assert fake_upbit.calls[0] == end + DAY
    assert fake_upbit.calls == sorted(fake_upbit.calls, reverse=True)


def test_stops_when_upbit_has_no_more_data(fake_upbit):
    """상장 이전 구간을 요청하면 빈 응답이 오고 루프가 멈춘다 (무한 루프 방지)."""
    start = LISTED_AT - DAY * 30
    end = LISTED_AT + DAY * 4

    result = fetch(start, end)

    assert [opened_at for opened_at, _ in result] == [LISTED_AT + DAY * offset for offset in range(5)]
    # 마지막 호출에서 빈 응답을 받고 중단 — 무한히 부르지 않는다.
    assert fake_upbit.call_count <= 3


# ── 캐시 ───────────────────────────────────────────────────────────────────


def test_no_external_call_when_range_is_fully_cached(fake_upbit):
    """같은 기간을 다시 백테스트하면 Upbit 호출이 0이다 (이 기능의 핵심 요구)."""
    start, end = datetime(2026, 2, 1, tzinfo=timezone.utc), datetime(2026, 2, 20, tzinfo=timezone.utc)
    first = fetch(start, end)
    assert fake_upbit.call_count == 1

    second = fetch(start, end)

    assert second == first
    assert fake_upbit.call_count == 1  # 늘지 않았다


def test_fetches_only_the_older_missing_part(fake_upbit):
    """캐시에 최근 구간만 있으면(대시보드가 최신 200개를 받아 둔 상태) 앞쪽만 채운다."""
    start, end = datetime(2026, 3, 1, tzinfo=timezone.utc), datetime(2026, 3, 20, tzinfo=timezone.utc)
    cached_from = datetime(2026, 3, 11, tzinfo=timezone.utc)
    seed_cache(*[cached_from + DAY * offset for offset in range(10)])

    result = fetch(start, end)

    assert len(result) == 20
    assert fake_upbit.call_count == 1
    # 캐시가 3/11부터 있으므로 3/10까지만 받아 오면 된다 → `to`는 그 다음 봉.
    assert fake_upbit.calls == [cached_from]


def test_fetches_only_the_newer_missing_part(fake_upbit):
    """캐시가 앞부분만 있으면 뒤쪽만 채운다."""
    start, end = datetime(2026, 4, 1, tzinfo=timezone.utc), datetime(2026, 4, 20, tzinfo=timezone.utc)
    seed_cache(*[start + DAY * offset for offset in range(10)])

    result = fetch(start, end)

    assert len(result) == 20
    assert fake_upbit.calls == [end + DAY]


def test_small_hole_in_cache_is_not_refetched(fake_upbit):
    """중간에 한 봉이 비어 있어도 다시 받지 않는다 — Upbit에 원래 없는 봉이면 헛된 호출이 된다."""
    start, end = datetime(2026, 5, 1, tzinfo=timezone.utc), datetime(2026, 5, 10, tzinfo=timezone.utc)
    every_day = [start + DAY * offset for offset in range(10)]
    seed_cache(*(day for day in every_day if day != start + DAY * 4))  # 5/5만 비움

    result = fetch(start, end)

    assert fake_upbit.call_count == 0
    assert len(result) == 9


def test_large_hole_in_cache_is_refetched(fake_upbit):
    """한 페이지를 넘는 큰 공백은 "아직 안 받아본 구간"으로 보고 채운다.

    1~2월과 11~12월만 백테스트해 둔 캐시에 1~12월을 요청하는 상황이다.
    """
    start = datetime(2025, 6, 1, tzinfo=timezone.utc)
    end = start + DAY * 400
    seed_cache(*[start + DAY * offset for offset in range(10)])
    seed_cache(*[end - DAY * offset for offset in range(10)])

    result = fetch(start, end)

    assert fake_upbit.call_count > 0
    assert len(result) == 401  # 가운데가 전부 채워졌다


# ── 경계값 ─────────────────────────────────────────────────────────────────


def test_both_bounds_are_inclusive(fake_upbit):
    start, end = datetime(2026, 6, 1, tzinfo=timezone.utc), datetime(2026, 6, 5, tzinfo=timezone.utc)

    opened_ats = [opened_at for opened_at, _ in fetch(start, end)]

    assert opened_ats[0] == start
    assert opened_ats[-1] == end


def test_bounds_are_floored_to_the_bucket(fake_upbit):
    """자정이 아닌 시각을 넘겨도 그 시각이 속한 봉이 포함된다 (일봉은 자정 기준)."""
    start = datetime(2026, 7, 1, 13, 45, tzinfo=timezone.utc)
    end = datetime(2026, 7, 3, 8, 20, tzinfo=timezone.utc)

    opened_ats = [opened_at for opened_at, _ in fetch(start, end)]

    assert opened_ats == [
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 2, tzinfo=timezone.utc),
        datetime(2026, 7, 3, tzinfo=timezone.utc),
    ]


def test_single_bucket_range(fake_upbit):
    day = datetime(2026, 6, 10, tzinfo=timezone.utc)

    assert [opened_at for opened_at, _ in fetch(day, day)] == [day]


def test_in_progress_candle_is_excluded(fake_upbit):
    """오늘(진행 중인 봉)까지 요청해도 어제까지만 나온다 — 값이 계속 바뀌는 봉은 제외한다."""
    today = candles_service._current_bucket_start("1d", datetime.now(timezone.utc))

    opened_ats = [opened_at for opened_at, _ in fetch(today - DAY * 3, today)]

    assert opened_ats[-1] == today - DAY


def test_range_entirely_in_the_future_returns_empty(fake_upbit):
    future = datetime.now(timezone.utc) + DAY * 10

    assert fetch(future, future + DAY * 3) == []
    assert fake_upbit.call_count == 0


# ── 거부되는 요청 ──────────────────────────────────────────────────────────


def test_end_before_start_is_rejected(fake_upbit):
    start = datetime(2026, 1, 10, tzinfo=timezone.utc)

    with pytest.raises(InvalidCandleRangeError):
        fetch(start, start - DAY)


@pytest.mark.parametrize(
    "interval,days_over,expected_message",
    [
        ("1m", 8, "1분봉은 최대 7일까지 조회할 수 있습니다."),
        ("10m", 31, "10분봉은 최대 1개월까지 조회할 수 있습니다."),
        ("30m", 91, "30분봉은 최대 3개월까지 조회할 수 있습니다."),
        ("1h", 181, "1시간봉은 최대 6개월까지 조회할 수 있습니다."),
        ("1d", 1826, "일봉은 최대 5년까지 조회할 수 있습니다."),
    ],
)
def test_range_over_interval_limit_is_rejected(fake_upbit, interval, days_over, expected_message):
    """봉단위별 최대 기간을 넘기면 사용자에게 보여줄 문구와 함께 거부한다 (06-backtesting.md 4장)."""
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(CandleRangeTooLongError) as error:
        fetch(end - timedelta(days=days_over), end, interval)

    assert error.value.message == expected_message
    assert fake_upbit.call_count == 0


@pytest.mark.parametrize("interval,days", [("1m", 7), ("1d", 1825)])
def test_range_exactly_at_the_limit_is_allowed(fake_upbit, interval, days):
    """상한 자체는 허용한다 — 경계에서 하루 차이로 막히면 "최대 7일"이라는 안내와 어긋난다."""
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)

    fetch(end - timedelta(days=days), end, interval)  # 예외가 나지 않으면 통과


def test_unknown_symbol_is_rejected(fake_upbit):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with session_scope() as db:
        with pytest.raises(CoinNotFoundError):
            get_candles_in_range(db, "NOSUCHCOIN", "1d", start, start + DAY)
