"""금액·수량·비율 입력의 수치 경계와 필드 간 관계 (요청 스키마 전수 점검에서 발견).

금액은 문자열로 받아 `Decimal(raw)`로 바꾸는데, `Decimal`은 `"NaN"`·`"Infinity"`를 정상 값으로
받는다. 점검에서 실측한 결과:

- **`trigger_price: "Infinity"` 예약가 주문 하나가 그 코인을 거래하는 모든 유저의 지정가 체결을
  영구히 멈췄다.** DB에 NaN으로 저장되어 매칭 루프가 매 틱 같은 자리에서 터졌다.
- `quantity: "1e-9"`는 `> 0` 검증을 통과한 뒤 저장 시 0이 되어, 체결 단계의 0 나누기로 같은
  사고를 냈다.
- `amount: "Infinity"` 입금이 잔고를 `NaN`으로 바꿔 계좌가 영구히 오염됐다.
- 손절 0·음수 / 익절 음수 슬롯은 매수 다음 tick에 팔아버려 수수료만 내는 왕복을 반복했다.

수정은 두 겹이다. **입력 경계**(`schemas/decimal_input.py`)가 새 오염을 막고, **매칭 격리**
(`matcher.run_matching_for_symbol`)가 이미 DB에 있는 오염 행이 다른 주문을 막지 못하게 한다.
둘 중 하나만으로는 부족하다 — 입력 경계는 과거 데이터를 못 고치고, 격리는 오염 자체를 막지 않는다.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import session_scope
from app.main import app
from app.models import Balance, Order
from app.schemas.decimal_input import (
    COIN_QUANTITY,
    KRW_AMOUNT,
    InvalidDecimalInputError,
    parse_decimal,
)
from app.services import matcher, pending_symbols
from app.services.auth import create_access_token
from tests.conftest import requires_db

NON_FINITE = ["NaN", "Infinity", "-Infinity", "sNaN"]


@pytest.fixture
def raw_client():
    """500을 예외가 아니라 응답으로 받는다 — "500이 아니라 400"을 확인하려면 필요하다."""
    return TestClient(app, raise_server_exceptions=False)


def _headers(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _balance(user_id: int) -> Decimal:
    with session_scope() as db:
        return db.get(Balance, user_id).krw_balance


# ---------------------------------------------------------------- 파서 단위


@pytest.mark.parametrize("raw", NON_FINITE)
def test_parser_rejects_non_finite(raw):
    with pytest.raises(InvalidDecimalInputError):
        parse_decimal(raw, **KRW_AMOUNT)


def test_parser_rejects_values_the_column_cannot_hold():
    """NUMERIC(20,4)의 정수부는 16자리다. 1e30은 소수 내림 전에 Decimal 정밀도도 넘는다."""
    for raw in ["1e16", "1e30", "100000000000000000"]:
        with pytest.raises(InvalidDecimalInputError):
            parse_decimal(raw, **KRW_AMOUNT)


def test_parser_rounds_down_to_the_stored_scale():
    """검증과 저장이 같은 값을 보도록 미리 내린다. 1e-9 수량은 여기서 0이 되어 호출부의
    `> 0` 검사에 걸린다 — 예전에는 검증을 통과한 뒤 DB에서 0이 됐다."""
    assert parse_decimal("1e-9", **COIN_QUANTITY) == 0
    assert parse_decimal("0.123456789", **COIN_QUANTITY) == Decimal("0.12345678")
    assert parse_decimal("1.99999", **KRW_AMOUNT) == Decimal("1.9999")  # 올림이 아니라 내림


def test_parser_accepts_ordinary_values():
    assert parse_decimal("10000", **KRW_AMOUNT) == Decimal("10000")
    assert parse_decimal("-5", **KRW_AMOUNT) == Decimal("-5")  # 부호 판단은 호출부의 몫이다


# ---------------------------------------------------------------- 🔴 매칭 루프 격리


def _victim_limit_buy(user_id: int, coin: str) -> int:
    with session_scope() as db:
        order = Order(
            user_id=user_id,
            coin_symbol=coin,
            side="buy",
            order_type="limit",
            price=Decimal("100"),
            quantity=Decimal("0.1"),
            status="pending",
            source="manual",
            fee=Decimal(0),
            created_at=datetime.now(timezone.utc),
        )
        db.add(order)
        pending_symbols.add(coin)  # 직접 넣은 행이라 힌트 등록이 없다 (redis 구성에서 필요)
        db.flush()
        return order.id


def _plant_poisoned_order(user_id: int, coin: str, **overrides) -> int:
    """입력 검증을 **우회해** 오염된 행을 DB에 직접 넣는다 — 수정 전에 이미 들어간 데이터를 흉내 낸다."""
    values = {
        "user_id": user_id,
        "coin_symbol": coin,
        "side": "buy",
        "order_type": "limit",
        "price": Decimal("100"),
        "quantity": Decimal("0.1"),
        "status": "pending",
        "source": "manual",
        "fee": Decimal(0),
        "created_at": datetime.now(timezone.utc),
        **overrides,
    }
    with session_scope() as db:
        order = Order(**values)
        db.add(order)
        pending_symbols.add(coin)  # 직접 넣은 행이라 힌트 등록이 없다 (redis 구성에서 필요)
        db.flush()
        return order.id


def _status(order_id: int) -> str:
    with session_scope() as db:
        return db.get(Order, order_id).status


@requires_db
@pytest.mark.parametrize(
    "poison",
    [
        pytest.param(
            {"order_type": "reserved", "trigger_price": Decimal("NaN"), "trigger_direction": "rising"},
            id="감시가격 NaN 예약가",
        ),
        pytest.param({"quantity": Decimal(0)}, id="수량 0 지정가"),
    ],
)
def test_poisoned_order_does_not_block_other_users_fills(make_user, test_coin, set_price, poison):
    """**가장 심각했던 것.** 한 유저의 오염된 주문이 다른 유저의 평범한 지정가를 막으면 안 된다.

    가해자 주문을 **먼저** 넣는다 — 매칭 후보 순서상 앞에 오면 뒤의 주문이 아예 평가되지 않던
    것이 원래 증상이다.
    """
    set_price(Decimal("100"))
    attacker, victim = make_user(), make_user()

    poisoned = _plant_poisoned_order(attacker, test_coin, **poison)
    victim_order = _victim_limit_buy(victim, test_coin)

    with pytest.raises(matcher.MatchingFailedError) as raised:
        matcher.run_matching_for_symbol(test_coin, Decimal("100"))

    assert _status(victim_order) == "filled", "오염된 주문 하나가 다른 유저의 체결을 막았다"
    assert raised.value.failed_order_ids == [poisoned], "실패가 집계되지 않았다 (조용한 실패)"


@requires_db
def test_healthy_matching_raises_nothing(make_user, test_coin, set_price):
    """음성 대조군 — 실패가 없으면 예외도 없어야 한다 (호출부가 error_count를 올리므로)."""
    set_price(Decimal("100"))
    victim_order = _victim_limit_buy(make_user(), test_coin)

    matcher.run_matching_for_symbol(test_coin, Decimal("100"))

    assert _status(victim_order) == "filled"


# ---------------------------------------------------------------- 🔴 입력 경계 (HTTP)


@requires_db
@pytest.mark.parametrize("raw", ["Infinity", "NaN", "1e20"])
def test_deposit_rejects_non_finite_and_oversized_amounts(raw_client, make_user, raw):
    """`Infinity` 입금은 잔고를 NaN으로 바꿔 계좌를 영구히 오염시켰다. NaN·1e20은 500이었다."""
    user = make_user()
    before = _balance(user)

    response = raw_client.post("/api/wallet/deposit", headers=_headers(user), json={"amount": raw})

    assert response.status_code == 400, response.text
    assert _balance(user) == before, "거부된 입금이 잔고를 건드렸다"


@requires_db
@pytest.mark.parametrize("raw", ["0.5", "0.00001"])
def test_deposit_below_one_won_is_rejected(raw_client, make_user, raw):
    """문서의 오류 문구가 "(1원 이상)"이다. 0.00001원은 0원짜리 입금 이력을 남겼다."""
    response = raw_client.post(
        "/api/wallet/deposit", headers=_headers(make_user()), json={"amount": raw}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "올바른 금액을 입력해주세요. (1원 이상)"


@requires_db
@pytest.mark.parametrize(
    "field,raw",
    [
        ("trigger_price", "Infinity"),
        ("trigger_price", "NaN"),
        ("quantity", "NaN"),
        ("quantity", "1e-9"),
        ("price", "NaN"),
    ],
)
def test_order_rejects_values_that_poison_matching(raw_client, make_user, test_coin, set_price, field, raw):
    set_price(Decimal("90"))
    user = make_user()
    body = {
        "coin_symbol": test_coin,
        "side": "buy",
        "order_type": "reserved",
        "quantity": "0.1",
        "price": "100",
        "trigger_price": "110",
        field: raw,
    }

    response = raw_client.post("/api/orders", headers=_headers(user), json=body)

    assert response.status_code == 400, response.text
    with session_scope() as db:
        count = db.execute(
            text("SELECT count(*) FROM orders WHERE user_id = :u"), {"u": user}
        ).scalar()
    assert count == 0, "거부된 주문이 DB에 남았다"


# ---------------------------------------------------------------- 🟠 손절·익절 범위


@requires_db
@pytest.mark.parametrize(
    "field,raw",
    [
        ("stop_loss_pct", "0"),
        ("stop_loss_pct", "-5"),
        ("stop_loss_pct", "100"),
        ("take_profit_pct", "0"),
        ("take_profit_pct", "-5"),
        ("stop_loss_pct", "NaN"),
        ("take_profit_pct", "Infinity"),
        ("take_profit_pct", "1000"),
    ],
)
def test_slot_rejects_exit_pcts_that_misfire(raw_client, make_user, test_coin, field, raw):
    """손절 0·음수 / 익절 음수는 매수 다음 tick에 팔아버린다(워커로 실측). 손절 100 이상은 영원히
    발동하지 않고, NaN은 그 슬롯을 매 tick 예외로 멈춘다. 1000은 컬럼을 넘어 500이었다."""
    response = raw_client.post(
        "/api/strategy-slots",
        headers=_headers(make_user()),
        json={
            "coin_symbol": test_coin,
            "strategy_type": "trend",
            "indicator": "ma",
            "params": {"interval": "1d", "short_period": 5, "long_period": 20},
            "invest_amount": "1000000",
            field: raw,
        },
    )

    assert response.status_code == 400, response.text


@requires_db
def test_slot_accepts_ordinary_exit_pcts(raw_client, make_user, test_coin):
    """음성 대조군 — 경계 바로 안쪽 값은 통과한다."""
    response = raw_client.post(
        "/api/strategy-slots",
        headers=_headers(make_user()),
        json={
            "coin_symbol": test_coin,
            "strategy_type": "trend",
            "indicator": "ma",
            "params": {"interval": "1d", "short_period": 5, "long_period": 20},
            "invest_amount": "1000000",
            "stop_loss_pct": "99.999",
            "take_profit_pct": "0.001",
        },
    )

    assert response.status_code == 201, response.text


@requires_db
def test_slot_rejects_zero_after_rounding_invest_amount(raw_client, make_user, test_coin):
    """0.00001원은 저장 자릿수(소수 4자리)에서 0이 되어 투자금 0원 슬롯이 만들어졌다."""
    response = raw_client.post(
        "/api/strategy-slots",
        headers=_headers(make_user()),
        json={
            "coin_symbol": test_coin,
            "strategy_type": "trend",
            "indicator": "ma",
            "params": {"interval": "1d", "short_period": 5, "long_period": 20},
            "invest_amount": "0.00001",
        },
    )

    assert response.status_code == 400


# ---------------------------------------------------------------- 🟠 RSI·DCA 필드 관계


@pytest.mark.parametrize("oversold,overbought", [(70, 30), (50, 50)])
def test_rsi_counter_trend_rejects_oversold_not_below_overbought(oversold, overbought):
    """뒤집으면 RSI 70 이하 전 구간이 매수가 되어 관망 구간이 사라진다 (매수 신호 51 → 278건 실측)."""
    from app.schemas.strategy_slots import validate_params_for

    with pytest.raises(ValueError, match="과매도 기준은 과매수 기준보다 작아야 합니다"):
        validate_params_for(
            "counter_trend",
            "rsi",
            {"interval": "1d", "period": 14, "oversold": oversold, "overbought": overbought},
        )


def test_rsi_counter_trend_defaults_are_valid():
    from app.schemas.strategy_slots import validate_params_for

    validated = validate_params_for("counter_trend", "rsi", {"interval": "1d"})

    assert (validated["oversold"], validated["overbought"]) == (30, 70)


@pytest.mark.parametrize("end_condition", ["budget", "count"])
def test_dca_rejects_amount_per_buy_above_invest_amount(end_condition):
    """회당 금액이 투자금보다 크면 엔진이 첫 매수 전에 "종료"로 판정해 영원히 사지 않는다.

    예전 검증은 `end_condition="count"`일 때만 "회당 × 횟수"를 봤으므로 budget 모드에서 통과했다.
    """
    from app.schemas.strategy_slots import validate_dca_budget

    params = {"amount_per_buy": 5000000, "end_condition": end_condition, "max_count": 1}

    with pytest.raises(ValueError, match="회당 매수금액이 투자금을 초과합니다"):
        validate_dca_budget(params, Decimal("1000000"))


def test_dca_accepts_amount_per_buy_equal_to_invest_amount():
    from app.schemas.strategy_slots import validate_dca_budget

    validate_dca_budget(
        {"amount_per_buy": 1000000, "end_condition": "budget", "max_count": 1}, Decimal("1000000")
    )


# ---------------------------------------------------------------- 🟡 백테스트 자본·비용


def _backtest_body(coin: str, **overrides) -> dict:
    return {
        "coin_symbol": coin,
        "strategy_type": "trend",
        "indicator": "ma",
        "params": {"interval": "1d", "short_period": 5, "long_period": 20},
        "start_date": "2026-01-01",
        "end_date": "2026-03-01",
        "initial_capital": "10000000",
        "fee_rate": "0.05",
        "slippage_rate": "0.1",
        **overrides,
    }


@pytest.fixture
def no_candles(monkeypatch):
    """검증을 통과하면 캔들 조회로 내려가 "시세 데이터가 없습니다"가 난다 — 외부 API는 막는다."""
    from app.services import candles as candles_service

    monkeypatch.setattr(candles_service, "get_candles_in_range", lambda *a, **k: [])


@requires_db
@pytest.mark.parametrize(
    "field,raw",
    [
        ("initial_capital", "0"),
        ("initial_capital", "-1000000"),
        ("initial_capital", "NaN"),
        ("fee_rate", "-1"),
        ("fee_rate", "100"),
        ("fee_rate", "NaN"),
        ("slippage_rate", "-5"),
        ("slippage_rate", "Infinity"),
        ("stop_loss_pct", "-5"),
        ("take_profit_pct", "-5"),
    ],
)
def test_backtest_run_rejects_invalid_costs(raw_client, make_user, test_coin, no_candles, field, raw):
    """음수 수수료·슬리피지는 매매할수록 돈이 생겨 결과를 부풀렸다(수수료 -1% → 최종자산 1,754만 원).
    NaN은 500이었다."""
    response = raw_client.post(
        "/api/backtest/run",
        headers=_headers(make_user()),
        json=_backtest_body(test_coin, **{field: raw}),
    )

    assert response.status_code == 400, response.text
    assert "시세 데이터가 없습니다" not in response.text, "검증을 통과해 캔들 조회까지 내려갔다"


@requires_db
def test_backtest_run_accepts_zero_costs(raw_client, make_user, test_coin, no_candles):
    """음성 대조군 — 수수료·슬리피지 0은 정상 입력이다 (비용 없는 시뮬레이션)."""
    response = raw_client.post(
        "/api/backtest/run",
        headers=_headers(make_user()),
        json=_backtest_body(test_coin, fee_rate="0", slippage_rate="0"),
    )

    # 검증을 통과해 캔들 조회까지 갔다는 증거
    assert response.json()["detail"] == "선택한 기간의 시세 데이터가 없습니다."


@requires_db
def test_backtest_save_rejects_negative_fee(raw_client, make_user, test_coin):
    """저장은 `/run`을 거치지 않는 별도 경로라 같은 검증을 따로 한다."""
    body = _backtest_body(test_coin, fee_rate="-1")
    body.update(
        {
            "metrics": {
                "total_return": "75.4",
                "final_asset": "17542674",
                "trade_count": 2,
                "win_rate": "100",
                "mdd": "0",
                "sharpe_ratio": "1",
                "benchmark_return": "0",
                "excess_return": "75.4",
            },
            "equity_curve": [],
            "trades": [],
            "label": "부풀려진 결과",
        }
    )
    user = make_user()

    response = raw_client.post("/api/backtest/results", headers=_headers(user), json=body)

    assert response.status_code == 400
    assert raw_client.get("/api/backtest/results", headers=_headers(user)).json() == []
