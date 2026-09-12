"""캔들(OHLCV) 캐시 서비스 (01-erd.md 2장 `candles`, 02-dashboard 차트가 최초 소비자).

Upbit 캔들 REST는 1회 최대 200개·레이트리밋이 있어, 최초 조회 시 DB에 캐싱하고
이후 요청은 캐시를 우선 사용한다. 캐시의 최신 봉이 비어있을 때만(=진행 중인
구간이 아직 없을 때) Upbit에서 다시 받아온다 (01-erd.md `candles` 설명).

**두 가지 조회 방식**이 있고 소비자가 다르다:

  - `get_candles` / `get_confirmed_candles` — "최신 N개". 02-dashboard 차트와 07 워커가 쓴다.
  - `get_candles_in_range` — "기간 지정". 06-backtesting이 쓴다 (06 계획 Phase C). Upbit의
    `to` 파라미터로 과거로 거슬러 페이지네이션하며, 캐시에 없는 구간만 채운다.

확장판 6단계에서 **Upbit REST 호출이 이 모듈로 일원화됐다** (04-async-jobs.md 3장):

  - 호출은 전부 `_fetch_upbit_candles` 한 곳을 지나고, 거기서 토큰 버킷을 통과한다
    (services/rate_limit.py). 호출 주체가 늘어나도 총량이 새지 않는 유일한 보장이다.
  - 캐시를 **채우는** 주체는 `scheduler` 역할이다 (services/candle_prefill.py).
  - 워커는 `fetch_if_missing=False`로 DB 캐시만 읽는다 — tick 중 블로킹 HTTP를 없애는
    것이 6단계의 목적이다 (03-worker-orchestration.md 5.1절).
"""

import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Candle, Coin
from app.services import rate_limit

Interval = Literal["1m", "10m", "30m", "1h", "1d"]

_INTERVAL_SECONDS: dict[Interval, int] = {
    "1m": 60,
    "10m": 600,
    "30m": 1800,
    "1h": 3600,
    "1d": 86400,
}

_MINUTE_UNITS: dict[Interval, int] = {"1m": 1, "10m": 10, "30m": 30, "1h": 60}

DEFAULT_CANDLE_COUNT = 200  # Upbit 캔들 REST 1회 최대치

# 봉단위별 최대 조회 기간 (06-backtesting.md 2.1-1절 표).
#
# Upbit 1회 200개 제한 + 레이트리밋 하에서 백테스팅 30초 목표(FR-B05)를 지키기 위한 상한이며,
# 어떤 조합도 1만 봉 이내다. "개월"은 30일, "년"은 365일로 환산했다 —
# `strategy_engine/dca.py`가 매수 주기의 "월"을 30일로 고정한 것과 같은 규칙이다.
MAX_RANGE_DAYS: dict[Interval, int] = {
    "1m": 7,  # 10,080봉
    "10m": 30,  # 4,320봉
    "30m": 90,  # 4,320봉
    "1h": 180,  # 4,320봉
    "1d": 1825,  # 1,825봉
}

_INTERVAL_LABELS: dict[Interval, str] = {
    "1m": "1분봉",
    "10m": "10분봉",
    "30m": "30분봉",
    "1h": "1시간봉",
    "1d": "일봉",
}

# 오류 문구에 쓰는 사람이 읽는 기간 표현 (06-backtesting.md 4장 오류 처리 표).
_LIMIT_LABELS: dict[Interval, str] = {
    "1m": "7일",
    "10m": "1개월",
    "30m": "3개월",
    "1h": "6개월",
    "1d": "5년",
}

# 페이지네이션 호출 사이 간격 — Upbit 레이트리밋 대비. 1분봉 7일이 51회 호출이므로
# 이 값이 전체 소요에 5초쯤 더한다 (30초 목표 안에서 감당 가능한 수준).
_FETCH_DELAY_SECONDS = 0.1


class CoinNotFoundError(Exception):
    """존재하지 않거나 상장폐지(is_active=False)된 코인 심볼을 조회하려는 경우."""


class InvalidCandleRangeError(Exception):
    """종료 시점이 시작 시점보다 앞서거나 같은 경우 (06-backtesting.md 4장)."""


class CandleRangeTooLongError(Exception):
    """봉단위별 최대 조회 기간을 넘긴 경우 (06-backtesting.md 2.1-1절).

    `message`는 그대로 사용자에게 보여줄 수 있는 문구다.
    """

    def __init__(self, interval: Interval) -> None:
        self.interval = interval
        self.message = (
            f"{_INTERVAL_LABELS[interval]}은 최대 {_LIMIT_LABELS[interval]}까지 조회할 수 있습니다."
        )
        super().__init__(self.message)


_http_client: httpx.Client | None = None


def _client() -> httpx.Client:
    """Upbit 호출에 재사용하는 HTTP 클라이언트.

    매번 `httpx.get`을 쓰면 요청마다 TCP+TLS 핸드셰이크를 새로 한다. 기간 조회는 한 번에 수십
    번을 연달아 부르므로(1분봉 7일 = 49회) 그 비용이 그대로 쌓인다 — 실측에서 호출당 0.87초가
    keep-alive 재사용으로 크게 줄었다. 클라이언트는 스레드 세이프해서 워커와 API가 함께 써도 된다.
    """
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(timeout=10.0)
    return _http_client


def _upbit_candle_url(interval: Interval) -> str:
    if interval == "1d":
        return "https://api.upbit.com/v1/candles/days"
    return f"https://api.upbit.com/v1/candles/minutes/{_MINUTE_UNITS[interval]}"


def _fetch_upbit_candles(
    market_code: str, interval: Interval, count: int, to: datetime | None = None
) -> list[dict]:
    """Upbit 캔들 REST 1회 호출. 항상 **최신순**(내림차순)으로 최대 `count`개를 준다.

    Args:
        to: 이 시각 **이전**(exclusive)의 캔들만 받는다. 과거로 거슬러 페이지네이션할 때
            직전 페이지의 가장 오래된 봉 시각을 그대로 넣으면 다음 200개가 이어진다.
            생략하면 가장 최근 캔들부터다.
    """
    params: dict[str, str | int] = {"market": market_code, "count": count}
    if to is not None:
        params["to"] = to.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 이 함수가 이 프로젝트에서 Upbit 캔들 REST를 치는 **유일한 지점**이다. 토큰 버킷을
    # 여기 한 곳에 걸어야 호출 주체가 늘어나도 총량이 새지 않는다 (04-async-jobs.md 3.2절).
    rate_limit.acquire()
    response = _client().get(_upbit_candle_url(interval), params=params)
    if response.status_code == 429:
        # 429를 그냥 raise_for_status로 흘려보내면 같은 속도로 계속 두드리게 된다.
        # 버킷에 알려 리필 속도를 낮춘 뒤에 예외를 올린다.
        rate_limit.note_throttled()
    response.raise_for_status()
    return response.json()


def _parse_opened_at(raw: dict) -> datetime:
    return datetime.strptime(raw["candle_date_time_utc"], "%Y-%m-%dT%H:%M:%S").replace(
        tzinfo=timezone.utc
    )


def _upsert_candles(db: Session, symbol: str, interval: Interval, raw_candles: list[dict]) -> None:
    if not raw_candles:
        return

    opened_ats = [_parse_opened_at(raw) for raw in raw_candles]
    existing = {
        candle.opened_at: candle
        for candle in db.scalars(
            select(Candle).where(
                Candle.coin_symbol == symbol,
                Candle.interval == interval,
                Candle.opened_at.in_(opened_ats),
            )
        )
    }

    for raw, opened_at in zip(raw_candles, opened_ats):
        candle = existing.get(opened_at)
        if candle is None:
            candle = Candle(coin_symbol=symbol, interval=interval, opened_at=opened_at)
            db.add(candle)
        candle.open = Decimal(str(raw["opening_price"]))
        candle.high = Decimal(str(raw["high_price"]))
        candle.low = Decimal(str(raw["low_price"]))
        candle.close = Decimal(str(raw["trade_price"]))
        candle.volume = Decimal(str(raw["candle_acc_trade_volume"]))
    db.commit()


def _current_bucket_start(interval: Interval, now: datetime) -> datetime:
    seconds = _INTERVAL_SECONDS[interval]
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=timezone.utc)


def _bucket_start(interval: Interval, moment: datetime) -> datetime:
    """`moment`가 속한 봉의 시작 시각(내림)."""
    return _current_bucket_start(interval, moment)


def _step(interval: Interval) -> timedelta:
    return timedelta(seconds=_INTERVAL_SECONDS[interval])


def get_candles_in_range(
    db: Session, symbol: str, interval: Interval, start: datetime, end: datetime
) -> list[Candle]:
    """`[start, end]` 구간의 확정봉을 오래된 순으로 반환한다 (06-backtesting.md 2.1-1절).

    캐시(`candles` 테이블)를 먼저 보고 **모자란 구간만** Upbit에서 채운다. `UNIQUE (coin_symbol,
    interval, opened_at)` 위에서 `_upsert_candles`가 덮어쓰므로 같은 기간을 다시 요청하면 외부
    호출이 0이다.

    `start`/`end`는 각자 속한 봉의 시작 시각으로 **내림**되고 양쪽 다 포함이다 — 호출부가 날짜
    (자정)를 넘기면 그 날의 봉이 그대로 포함된다. 진행 중인 봉은 값이 계속 바뀌어 신호가 흔들리므로
    (07-auto-trading.md 4장과 같은 이유) 항상 제외한다.

    Raises:
        CoinNotFoundError: 없거나 상장폐지된 심볼.
        InvalidCandleRangeError: `end`가 `start`보다 앞선 경우.
        CandleRangeTooLongError: 봉단위별 최대 기간을 넘긴 경우.
    """
    coin = db.get(Coin, symbol)
    if coin is None or not coin.is_active:
        raise CoinNotFoundError()
    if end < start:
        raise InvalidCandleRangeError()
    if end - start > timedelta(days=MAX_RANGE_DAYS[interval]):
        raise CandleRangeTooLongError(interval)

    range_start = _bucket_start(interval, start)
    # 확정봉만 다룬다 — 진행 중인 봉의 직전 봉이 마지막 확정봉이다.
    last_confirmed = _current_bucket_start(interval, datetime.now(timezone.utc)) - _step(interval)
    range_end = min(_bucket_start(interval, end), last_confirmed)
    if range_end < range_start:
        return []

    for gap_start, gap_end in _missing_ranges(db, symbol, interval, range_start, range_end):
        _fill_range(db, coin.market_code, symbol, interval, gap_start, gap_end)

    return _load_cached_range(db, symbol, interval, range_start, range_end)


def _load_cached_range(
    db: Session, symbol: str, interval: Interval, start: datetime, end: datetime
) -> list[Candle]:
    return list(
        db.scalars(
            select(Candle)
            .where(
                Candle.coin_symbol == symbol,
                Candle.interval == interval,
                Candle.opened_at >= start,
                Candle.opened_at <= end,
            )
            .order_by(Candle.opened_at)
        ).all()
    )


def _missing_ranges(
    db: Session, symbol: str, interval: Interval, start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    """캐시에 없어서 Upbit에서 받아와야 하는 구간들 (봉 시작 시각 기준, 양끝 포함).

    앞뒤로 비어 있는 구간은 그대로 채운다. 중간의 공백은 **한 페이지(200봉)를 넘을 때만** 채운다:
    이 모듈의 페이지네이션은 커서를 뒤로 밀며 연속으로 채우므로 우리가 받아온 구간에는 구멍이
    생기지 않는다. 따라서 캐시 중간의 작은 구멍은 "Upbit에 원래 그 봉이 없다"는 뜻이고(거래가
    한 건도 없던 분봉), 다시 요청해도 채워지지 않는다 — 매 백테스트마다 헛된 호출을 반복하지
    않도록 건너뛴다. 반대로 한 페이지를 넘는 큰 공백은 "아직 받아본 적 없는 구간"으로 본다
    (예: 1~2월과 11~12월만 백테스트해 둔 캐시에 1~12월을 요청한 경우).
    """
    cached = [candle.opened_at for candle in _load_cached_range(db, symbol, interval, start, end)]
    if not cached:
        return [(start, end)]

    step = _step(interval)
    hole_threshold = step * DEFAULT_CANDLE_COUNT
    missing: list[tuple[datetime, datetime]] = []

    if cached[0] > start:
        missing.append((start, cached[0] - step))

    for previous, current in zip(cached, cached[1:]):
        if current - previous > hole_threshold:
            missing.append((previous + step, current - step))

    if cached[-1] < end:
        missing.append((cached[-1] + step, end))

    return missing


def _fill_range(
    db: Session,
    market_code: str,
    symbol: str,
    interval: Interval,
    start: datetime,
    end: datetime,
) -> None:
    """`[start, end]` 구간을 Upbit에서 받아 캐시에 적재한다.

    Upbit는 `to` **이전**의 캔들을 최신순 200개씩 주므로, `end` 봉까지 받으려면 한 칸 뒤를
    기준으로 시작해 받은 페이지의 가장 오래된 봉을 다음 커서로 삼으며 과거로 거슬러 간다.
    커서가 전진하지 않으면(빈 응답이거나 같은 페이지가 되풀이되면) 무한 루프를 피해 중단한다 —
    상장 이전 구간을 요청하면 실제로 빈 응답이 온다.
    """
    step = _step(interval)
    cursor = end + step

    while cursor > start:
        raw_candles = _fetch_upbit_candles(market_code, interval, DEFAULT_CANDLE_COUNT, to=cursor)
        if not raw_candles:
            return

        _upsert_candles(db, symbol, interval, raw_candles)

        oldest = min(_parse_opened_at(raw) for raw in raw_candles)
        if oldest >= cursor:
            return
        cursor = oldest
        time.sleep(_FETCH_DELAY_SECONDS)


def get_confirmed_candles(
    db: Session,
    symbol: str,
    interval: Interval,
    count: int = DEFAULT_CANDLE_COUNT,
    *,
    fetch_if_missing: bool = True,
) -> list[Candle]:
    """`get_candles`와 동일하되, 아직 진행 중인(미확정) 마지막 봉을 잘라내고 반환한다.

    07-auto-trading은 확정봉만 신호 판정에 써야 한다(07-auto-trading.md 4장) — 진행 중인
    봉은 아직 값이 바뀔 수 있어 같은 시각에 여러 번 다른 신호를 낼 수 있기 때문이다.
    `services/strategy_slots.py`의 신호 미리보기 조회와 07 Step 2B 워커 tick이 함께 쓴다.

    `fetch_if_missing=False`는 워커 전용이다 — 이유는 `get_candles` docstring 참고.
    """
    fetched = get_candles(db, symbol, interval, count, fetch_if_missing=fetch_if_missing)
    bucket_start = _current_bucket_start(interval, datetime.now(timezone.utc))
    return [candle for candle in fetched if candle.opened_at < bucket_start]


def get_candles(
    db: Session,
    symbol: str,
    interval: Interval,
    count: int = DEFAULT_CANDLE_COUNT,
    *,
    fetch_if_missing: bool = True,
) -> list[Candle]:
    """`(symbol, interval)`의 최신 `count`개 캔들을 오래된 순으로 반환한다.

    `count`는 **반환 개수만** 정한다 — 캐시에 적재하는 양은 호출자와 무관하게 항상
    `DEFAULT_CANDLE_COUNT`다 (이유는 아래 재조회 분기의 주석 참고).

    `fetch_if_missing=False`면 **DB 캐시만 읽고 Upbit를 부르지 않는다.** 워커 tick이
    이 경로를 쓴다 (확장판 03-worker-orchestration.md 5.1절): 캐시 미스가 곧 블로킹
    HTTP였고, 서로 다른 코인 50종에 1분봉을 걸면 매 분 정각에 50회 × 0.27초 ≈ 13.5초로
    10초 tick 예산을 넘긴다. 캐시를 채우는 일은 `scheduler`의 캔들 미리 채우기
    (services/candle_prefill.py)가 맡고, 워커는 없으면 **이번 tick 평가를 건너뛰고
    기록한다.**
    """
    coin = db.get(Coin, symbol)
    if coin is None or not coin.is_active:
        raise CoinNotFoundError()

    def _load_cached() -> list[Candle]:
        return list(
            reversed(
                db.scalars(
                    select(Candle)
                    .where(Candle.coin_symbol == symbol, Candle.interval == interval)
                    .order_by(Candle.opened_at.desc())
                    .limit(count)
                ).all()
            )
        )

    cached = _load_cached()
    now = datetime.now(timezone.utc)
    bucket_start = _current_bucket_start(interval, now)

    if fetch_if_missing and (not cached or cached[-1].opened_at < bucket_start):
        # 요청받은 `count`가 아니라 항상 최대치를 받아 캐시에 넣는다. 신선도 판정이 "최신 봉이
        # 있는가"만 보기 때문에, count가 작은 호출(services/dashboard.py의 전일종가 조회는
        # count=2)이 2개만 적재하면 그 캐시가 같은 날 내내 최신으로 판정된다 — 이후 200개를
        # 요청하는 차트·워커가 그 2개만 돌려받고 굶는다(지표가 조용히 신호를 못 낸다).
        # Upbit 호출 비용은 개수와 무관하게 1회로 같으므로 항상 최대치로 채워 둔다.
        raw_candles = _fetch_upbit_candles(coin.market_code, interval, DEFAULT_CANDLE_COUNT)
        _upsert_candles(db, symbol, interval, raw_candles)
        cached = _load_cached()

    return cached
