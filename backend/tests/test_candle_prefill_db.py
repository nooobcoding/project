"""캔들 미리 채우기와 워커의 캔들 미스 처리 (확장판 6단계).

6단계는 **워커 tick에서 Upbit REST를 제거**하는 단계다. 그러면 캔들 공급이 워커 자신에게서
`scheduler`로 옮겨가는데, 이 이관이 어긋나면 나타나는 증상은 하나뿐이다 — **아무 오류 없이
신호가 영영 안 나간다.** 프로세스는 전부 정상이고 로그도 조용하다.

그래서 여기서 못 박는 것은 세 가지다:

1. 워커가 캐시 미스에서 **Upbit를 안 부른다** (부르면 테스트가 실패한다).
2. 안 부르는 대신 **건너뛴 사실을 센다** — 조용한 실패 금지 (06-observability.md 5장).
3. `scheduler`가 **활성 슬롯의 조합을 실제로 채운다**, 그리고 같은 봉에서 두 번 부르지 않는다.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.database import session_scope
from app.models import Candle, Coin, StrategySlot
from app.services import candle_prefill
from app.services import candles as candles_service
from app.strategy_engine import worker
from tests.conftest import requires_db


def _clear_candles(symbol: str) -> None:
    with session_scope() as db:
        db.execute(delete(Candle).where(Candle.coin_symbol == symbol))


def _cached_count(symbol: str, interval: str) -> int:
    with session_scope() as db:
        return len(
            db.scalars(
                select(Candle.id).where(
                    Candle.coin_symbol == symbol, Candle.interval == interval
                )
            ).all()
        )


def _raw_daily_candles(count: int) -> list[dict]:
    """Upbit 응답 모양의 합성 일봉 (최신순)."""
    newest = candles_service._current_bucket_start("1d", datetime.now(timezone.utc))
    return [
        {
            "candle_date_time_utc": (newest - timedelta(days=index)).strftime(
                "%Y-%m-%dT%H:%M:%S"
            ),
            "opening_price": 100.0,
            "high_price": 110.0,
            "low_price": 90.0,
            "trade_price": 105.0,
            "candle_acc_trade_volume": 1.0,
        }
        for index in range(count)
    ]


@pytest.fixture(autouse=True)
def isolated_prefill_memory():
    """시도 기록은 모듈 전역이라 테스트 사이에 새지 않게 비운다."""
    candle_prefill._attempted.clear()
    yield
    candle_prefill._attempted.clear()


@pytest.fixture
def no_upbit(monkeypatch):
    """Upbit 호출이 일어나면 즉시 실패시킨다."""

    def _forbidden(*args, **kwargs):
        pytest.fail("이 경로에서 Upbit REST를 부르면 안 된다")

    monkeypatch.setattr(candles_service, "_fetch_upbit_candles", _forbidden)


@pytest.fixture
def fake_upbit(monkeypatch, test_coin):
    """Upbit 응답을 합성으로 대체하고, **합성 코인에 대한** 호출 횟수를 센다.

    호출 수를 전부 세지 않는 이유: 개발 DB에는 이 테스트와 무관한 활성 슬롯이 남아 있을 수
    있고, `run_prefill`은 그것들도 함께 돈다. 우리 코인만 세야 테스트가 환경에 안 흔들린다.
    """
    calls: list[tuple] = []
    market_code = f"KRW-{test_coin}"

    def _fake(code, interval, count, to=None):
        if code == market_code:
            calls.append((code, interval, count, to))
        return _raw_daily_candles(count)

    monkeypatch.setattr(candles_service, "_fetch_upbit_candles", _fake)
    return calls


@requires_db
def test_worker_skips_without_calling_upbit(make_slot, test_coin, set_price, no_upbit):
    """캔들이 없으면 워커는 블로킹 HTTP 대신 건너뛰고 그 사실을 센다.

    **6단계의 본 목적이다** (03-worker-orchestration.md 5.1절 표) — 캐시 미스가 곧 0.27초
    블로킹이었고, 봉 경계 직후에는 활성 조합 수만큼 순차로 터져 10초 tick 예산을 넘겼다.
    """
    _clear_candles(test_coin)
    slot_id = make_slot(params={"interval": "1d", "short_period": 2, "long_period": 3})
    set_price(Decimal("1000"))

    worker._tick_skip_count = 0
    worker.process_slot(slot_id)  # no_upbit 픽스처가 HTTP를 감시한다

    assert worker._tick_skip_count == 1


@requires_db
def test_prefill_fills_active_slot_combination(make_slot, test_coin, fake_upbit):
    """`scheduler`가 활성 슬롯의 (심볼, 봉단위) 조합을 실제로 채운다."""
    _clear_candles(test_coin)
    make_slot(params={"interval": "1d", "short_period": 2, "long_period": 3})
    assert _cached_count(test_coin, "1d") == 0

    candle_prefill.run_prefill()

    assert _cached_count(test_coin, "1d") > 0
    assert len(fake_upbit) == 1


@requires_db
def test_prefill_unblocks_the_worker(make_slot, test_coin, set_price, fake_upbit, monkeypatch):
    """채우기 전에는 건너뛰던 슬롯이 채운 뒤에는 평가된다 — 이관이 실제로 이어진다."""
    _clear_candles(test_coin)
    slot_id = make_slot(params={"interval": "1d", "short_period": 2, "long_period": 3})
    set_price(Decimal("1000"))

    worker._tick_skip_count = 0
    worker.process_slot(slot_id)
    assert worker._tick_skip_count == 1  # 아직 캔들이 없다

    candle_prefill.run_prefill()

    # 이제 워커는 Upbit를 부르지 않고도 평가에 들어간다.
    monkeypatch.setattr(
        candles_service,
        "_fetch_upbit_candles",
        lambda *a, **k: pytest.fail("워커가 Upbit를 불렀다"),
    )
    worker._tick_skip_count = 0
    worker.process_slot(slot_id)

    assert worker._tick_skip_count == 0


@requires_db
def test_prefill_does_not_refetch_within_same_bucket(make_slot, test_coin, fake_upbit):
    """같은 봉 안에서는 조합당 한 번만 부른다.

    거래가 없던 분봉은 Upbit에도 없어서 "없으면 채운다"를 그대로 돌리면 그 조합이 매 주기
    헛호출을 반복한다. 잡 주기가 20초이므로 1분봉 하나가 분당 3회를 태우게 된다.
    """
    _clear_candles(test_coin)
    make_slot(params={"interval": "1d", "short_period": 2, "long_period": 3})

    candle_prefill.run_prefill()
    candle_prefill.run_prefill()
    candle_prefill.run_prefill()

    assert len(fake_upbit) == 1


@requires_db
def test_prefill_ignores_inactive_slots(make_slot, test_coin, fake_upbit):
    """꺼진 슬롯은 채우지 않는다 — 워커도 평가하지 않으므로 부를 이유가 없다."""
    _clear_candles(test_coin)
    make_slot(params={"interval": "1d"}, is_active=False)

    candle_prefill.run_prefill()

    assert fake_upbit == []
    assert (test_coin, "1d") not in candle_prefill._attempted


@requires_db
def test_prefill_survives_one_bad_combination(make_slot, test_user, test_coin, fake_upbit):
    """알 수 없는 봉단위가 섞여 있어도 나머지 조합은 채운다.

    조합 하나가 잡 전체를 끝내면 그 주기의 나머지 코인이 전부 안 채워지고, 그만큼 워커가
    건너뛴다. 실패는 조합 단위로 격리되어야 한다.
    """
    _clear_candles(test_coin)
    # 활성 슬롯은 (유저, 코인)당 하나뿐이므로(ux_strategy_slots_active_coin) 두 번째 조합은
    # 별도 코인으로 만든다.
    bad_symbol = "ZZBAD"
    with session_scope() as db:
        if db.get(Coin, bad_symbol) is None:
            db.add(
                Coin(
                    symbol=bad_symbol,
                    market_code=f"KRW-{bad_symbol}",
                    korean_name="테스트코인2",
                    english_name="Test Coin 2",
                    is_active=True,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        db.add(
            StrategySlot(
                user_id=test_user,
                coin_symbol=bad_symbol,
                strategy_type="trend",
                indicator="ma",
                params={"interval": "3분봉"},  # 정상 경로에서는 나오지 않는 값
                invest_amount=Decimal("1000000"),
                state={},
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
        )
    make_slot(params={"interval": "1d", "short_period": 2, "long_period": 3})

    candle_prefill.run_prefill()

    assert _cached_count(test_coin, "1d") > 0
