"""알면서 안 고친 것들을 **의도된 동작**으로 못박는다 (Phase 4).

여기 모인 것은 버그가 아니라 근거를 갖고 남겨둔 선택들이다. 문제는 그 근거가 문서와 주석에만
있다는 점이다 — 나중에 누가 코드만 보고 "이건 버그네" 하고 고치면 아무 테스트도 막지 않는다.
그래서 **고치면 빨간불이 나게** 해 둔다. 빨간불을 본 사람이 이 파일을 읽고 "일부러 이렇게 둔
것이구나"를 알게 되는 것이 목적이다.

**이미 다른 파일이 지키고 있는 것은 여기서 다시 쓰지 않는다**:

- 로그아웃 후에도 토큰이 만료까지 유효 → `test_api_auth.py`
- 수수료 정밀도(기록 fee와 실제 차감액이 건당 0.00005원까지 다름) → `test_matcher_fill_db.py`
- 슬롯 OFF 중 수동 매도 후 재ON 보정 → `test_slot_reconcile_db.py` (6건)
- 체결 후처리 2트랜잭션 분리를 샤드 점유 시 재조정으로 덮는 것 → `test_worker_reconcile_db.py`
"""

from contextlib import suppress
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.constants import TRADING_FEE_RATE
from app.database import session_scope
from app.models import Order
from app.services import candles as candles_service
from app.strategy_engine import backtest, costs, worker
from app.strategy_engine.runner import SlotSpec
from tests.conftest import load_slot_state, requires_db

CANDLE_START = datetime(2026, 9, 1, tzinfo=timezone.utc)

# 하한 100 / 상한 200 / 4칸 → 매수 라인 [100, 125, 150, 175]
GRID_PARAMS = {"interval": "1d", "lower_price": 100, "upper_price": 200, "grid_count": 4}
INVEST = Decimal("1000000")
SLIPPAGE = Decimal("0.001")  # 0.1%


class _Candle:
    def __init__(self, opened_at: datetime, close: Decimal) -> None:
        self.opened_at = opened_at
        self.close = close


def _candles(*closes) -> list[_Candle]:
    return [
        _Candle(CANDLE_START + timedelta(days=index), Decimal(str(close)))
        for index, close in enumerate(closes)
    ]


@pytest.fixture
def feed_candles(monkeypatch):
    def _feed(candles: list[_Candle]) -> None:
        monkeypatch.setattr(
            candles_service,
            "get_confirmed_candles",
            lambda db, symbol, interval, **kwargs: candles,
        )

    return _feed


def _order_count(user_id: int) -> int:
    with session_scope() as db:
        return db.scalar(select(func.count()).select_from(Order).where(Order.user_id == user_id))


def _lines(slot_id: int) -> list[dict]:
    return load_slot_state(slot_id)["grid"]["lines"]


def _fail_second_buy(monkeypatch):
    """두 번째 매수 intent에서만 터지게 만든다 (다중 intent 중간 실패 재현)."""
    original = worker._place_buy
    calls = {"count": 0}

    def _wrapped(slot, amount):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("두 번째 라인에서 주문 실패")
        return original(slot, amount)

    monkeypatch.setattr(worker, "_place_buy", _wrapped)
    return original


# ------------------------------------------------- 1. 실매매 vs 백테스트의 의도된 비대칭


@requires_db
def test_real_trading_skips_where_backtest_reduces_the_buy(
    make_slot, test_user, test_coin, set_price, feed_candles
):
    """현금이 모자랄 때 **실매매는 건너뛰고 백테스트는 줄여서 산다** (06-backtesting.md 2.7절).

    두 동작은 각 파일에서 따로 검증돼 있지만(`test_worker_db.py` / `test_backtest.py`), 둘이
    **서로 다르다는 사실 자체**를 고정하는 곳이 없었다. 한쪽만 보고 "다른 쪽도 같아야 한다"며
    통일하면 그게 여기서 걸린다.

    왜 달라야 하는가: 실매매의 스킵은 슬롯 배정액 밖의 **사용자 다른 자금**을 지키기 위한
    것이다. 백테스트에는 그런 외부 자금이 없고 초기투자금이 곧 1회 진입 금액이라, 스킵을
    그대로 옮기면 왕복 한 번에 수수료만큼만 줄어도 이후 매수가 영구히 스킵돼 손실 전략이
    "거래 2건"으로 끝난다 (구현 중 실측으로 발견).
    """
    # 실매매: 배정액이 시드머니를 넘어 매수가 불가능한 상황
    slot_id = make_slot(
        strategy_type="grid", indicator=None, params=GRID_PARAMS, invest_amount=Decimal("50000000")
    )
    set_price(Decimal("130"))
    feed_candles(_candles(190, 130))

    worker.process_slot(slot_id)

    assert _order_count(test_user) == 0, "실매매가 잔고 부족인데도 줄여서 샀다"

    # 백테스트: 같은 "배정액 > 현금" 상황에서는 남은 현금만큼 줄여서 산다
    run = backtest.run_backtest(
        candles=_candles(190, 130),
        spec=SlotSpec(
            strategy_type="grid",
            indicator=None,
            params=GRID_PARAMS,
            invest_amount=Decimal("50000000"),
            state={},
        ),
        initial_capital=Decimal("1000000"),  # 배정액의 1/50
        fee_rate=TRADING_FEE_RATE,
    )

    buys = [trade for trade in run.trades if trade.side == "buy"]
    assert buys, "백테스트가 현금 부족을 스킵으로 처리했다 (줄여서 사야 한다)"


def test_backtest_applies_slippage_but_real_path_does_not():
    """슬리피지는 **백테스트에만** 적용된다 (00-overview.md 원칙 7).

    실체결은 실시세로 체결되므로 슬리피지를 더하면 이중 반영이다. 두 경로가 같은 `costs`
    모듈을 공유하기 때문에 "공유하는데 왜 다르게 쓰지?"라는 이유로 통일될 위험이 실제로 있다.
    """
    price = Decimal("100000")

    # 백테스트: 불리한 방향으로 밀린다
    assert costs.calc_fill_price(price, "buy", SLIPPAGE) == price * (1 + SLIPPAGE)
    assert costs.calc_fill_price(price, "sell", SLIPPAGE) == price * (1 - SLIPPAGE)

    # 실매매: 슬리피지 인자를 아예 넘기지 않는다 (기본값 0 = 이론가 그대로)
    assert costs.calc_fill_price(price, "buy") == price
    assert costs.calc_fill_price(price, "sell") == price


@requires_db
def test_real_market_fill_uses_the_exact_cached_price(test_user, test_coin, set_price):
    """실체결가에 슬리피지가 섞이지 않는지 **체결 경로로** 확인한다.

    위 테스트는 `costs` 함수의 계약만 본다. 체결 경로가 실수로 슬리피지를 적용하기 시작하면
    그쪽은 통과하고 이 테스트가 잡는다.
    """
    from app.services.orders import create_order

    price = Decimal("100000")
    set_price(price)

    with session_scope() as db:
        order_id = create_order(
            db,
            user_id=test_user,
            coin_symbol=test_coin,
            side="buy",
            order_type="market",
            quantity=Decimal("0.1"),
            source="manual",
        ).id

    with session_scope() as db:
        assert db.get(Order, order_id).price == price, "실체결가에 슬리피지가 섞였다"


# ------------------------------------------------- 2. 워커 다중 intent 부분 실패


@requires_db
def test_failed_intent_loses_the_rest_of_the_candle_but_heals_next_candle(
    make_slot, test_user, test_coin, set_price, feed_candles, monkeypatch
):
    """그리드 여러 라인 중 하나에서 예외가 나면 **그 봉의 나머지 라인은 유실된다.**

    `claim_candle`이 이미 봉을 선점했으므로 같은 봉으로 다시 들어오지 않는다. 그래도 방치해도
    되는 이유는 **라인이 empty로 남아 다음 봉에 재시도되기 때문**이다 —
    03-worker-orchestration.md 6장이 "self-healing이라 영향 낮아 방치"로 판단한 그 성질이다.

    이 테스트는 그 판단의 **전제**를 고정한다. 실패한 라인이 empty로 남지 않거나(= filled로
    마킹되거나) 다음 봉에 재시도되지 않으면, "방치해도 된다"는 근거 자체가 무너진다.
    """
    slot_id = make_slot(
        strategy_type="grid", indicator=None, params=GRID_PARAMS, invest_amount=INVEST
    )
    set_price(Decimal("130"))

    original_place_buy = _fail_second_buy(monkeypatch)

    # 종가 130이면 그 위 라인(150·175) 둘이 함께 매수 대상이 된다 — intent가 2개 나온다.
    feed_candles(_candles(190, 130))
    # 예외가 호출부로 올라오는지 자체는 계약이 아니다 — 워커가 나중에 intent별로 잡아내도록
    # 바뀌면 그건 개선이다. 여기서 고정하는 것은 "실패한 라인이 재시도 가능한 모양으로
    # 남는가"뿐이므로 전파 여부와 무관하게 통과해야 한다.
    with suppress(RuntimeError):
        worker.process_slot(slot_id)

    filled_after_failure = [line for line in _lines(slot_id) if line["filled"]]
    empty_after_failure = [line for line in _lines(slot_id) if not line["filled"]]
    assert len(filled_after_failure) == 1, "실패 전에 체결된 라인이 기록되지 않았다"
    assert empty_after_failure, "실패한 라인이 empty로 남지 않아 재시도될 수 없다"

    # 다음 봉에서 재시도된다 — 이것이 self-healing의 실체다.
    monkeypatch.setattr(worker, "_place_buy", original_place_buy)
    feed_candles(_candles(190, 130, 130))
    worker.process_slot(slot_id)

    filled_after_retry = [line for line in _lines(slot_id) if line["filled"]]
    assert len(filled_after_retry) > len(filled_after_failure), (
        "다음 봉에 재시도되지 않았다 — self-healing이라는 판단의 근거가 무너진다"
    )


@requires_db
def test_grid_ledger_stays_consistent_after_a_failed_intent(
    make_slot, test_user, test_coin, set_price, feed_candles, monkeypatch
):
    """부분 실패 뒤에도 **라인 합 == state.position.quantity** 불변식이 지켜져야 한다.

    유실 자체는 받아들이지만, 유실이 장부를 깨뜨리면 "영향 낮음"이 아니다 — 라인 합이
    position보다 작으면 그 라인이 다시 매수 대상이 되어 배정액을 넘겨 산다.
    """
    slot_id = make_slot(
        strategy_type="grid", indicator=None, params=GRID_PARAMS, invest_amount=INVEST
    )
    set_price(Decimal("130"))
    _fail_second_buy(monkeypatch)

    feed_candles(_candles(190, 130))
    with suppress(RuntimeError):
        worker.process_slot(slot_id)

    state = load_slot_state(slot_id)
    line_total = sum(
        Decimal(line["quantity"]) for line in state["grid"]["lines"] if line["filled"]
    )
    position = state.get("position")
    position_quantity = Decimal(position["quantity"]) if position else Decimal(0)

    assert line_total == position_quantity, (
        f"부분 실패가 장부를 깨뜨렸다 (라인 합={line_total}, position={position_quantity})"
    )


# ------------------------------------------------- 3. 셀프 초기화 경로 없음


@requires_db
@pytest.mark.parametrize("method", ["post", "delete"])
def test_portfolio_self_reset_endpoint_does_not_exist(client, auth_headers, method):
    """모의투자 셀프 초기화(FR-P05)는 **일부러 구현하지 않았다** (08-portfolio.md 6장).

    계획 단계에서 `POST /api/portfolio/reset`까지 설계했다가, 사용자가 자기 거래 데이터를
    스스로 전부 지우는 self-service 초기화는 프로젝트 방향과 맞지 않는다고 판단해 제외했다.
    초기화는 성격상 관리자 기능이고, 그때는 대상 `user_id` 파라미터와 권한 검사가 필요해
    여기서 계획했던 엔드포인트와는 **다른 설계**가 된다.

    "계획서에 있는데 왜 없지?" 하고 되살리는 것을 막기 위해 부재 자체를 고정한다.
    """
    response = getattr(client, method)("/api/portfolio/reset", headers=auth_headers)

    assert response.status_code in (404, 405), (
        f"셀프 초기화 엔드포인트가 생겼다 ({method.upper()} → {response.status_code}) — "
        "관리자 기능으로 다시 설계하기로 한 결정을 확인할 것"
    )
