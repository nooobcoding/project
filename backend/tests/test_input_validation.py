"""입력 검증 — 날짜 범위 역전과 단기·장기 기간 역전.

**둘 다 "에러 없이 돌아서" 위험한 종류다.** 날짜가 뒤집힌 입출금 조회는 200과 빈 목록을 돌려줘
"그 기간에 내역이 없다"로 읽히고, 단기·장기가 뒤집힌 이동평균은 같은 가격 흐름에서 **신호가
정반대**로 나온다(정상 설정이 매수를 내는 봉에 매도를 낸다). 자동매매 슬롯에서는 팔아야 할 때
사는 슬롯이 만들어진다.

사용자 보고로 발견했다 — 이 저장소의 어떤 테스트도 이 경계를 건드린 적이 없었다.

검증은 **한 곳에서** 하고 여러 경로가 공유한다: 단기·장기는 `validate_params_for`를 거치는
백테스트 실행 / 슬롯 생성 / 슬롯 수정이 전부 한 번에 막힌다.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from app.database import session_scope
from app.models import DepositWithdrawal
from app.schemas.strategy_slots import validate_params_for
from app.services import candles as candles_service
from app.strategy_engine import signals
from tests.conftest import requires_db

INVALID_DATE_RANGE = "종료일은 시작일 이후로 설정해주세요."
PERIOD_ORDER = "단기 기간은 장기 기간보다 짧아야 합니다."


# ---------------------------------------------------------------- 입출금 조회 날짜


@requires_db
def test_wallet_transactions_reject_inverted_date_range(client, auth_headers):
    response = client.get(
        "/api/wallet/transactions",
        headers=auth_headers,
        params={"start": "2026-12-31", "end": "2026-01-01"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == INVALID_DATE_RANGE


@requires_db
def test_wallet_transactions_accept_same_day_range(client, auth_headers, test_user):
    """시작일 == 종료일은 정상이다 (하루 조회) — 경계를 `<=`로 잘못 막으면 이게 깨진다."""
    with session_scope() as db:
        db.add(
            DepositWithdrawal(
                user_id=test_user,
                type="deposit",
                amount=Decimal("1000"),
                balance_after=Decimal("1001000"),
                memo=None,
                created_at=datetime(2026, 6, 15, 3, 0, tzinfo=timezone.utc),  # KST 12:00
            )
        )

    response = client.get(
        "/api/wallet/transactions",
        headers=auth_headers,
        params={"start": "2026-06-15", "end": "2026-06-15"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1


@requires_db
def test_wallet_transactions_accept_open_ended_ranges(client, auth_headers):
    """한쪽만 준 경우는 비교할 대상이 없으므로 막으면 안 된다."""
    assert client.get(
        "/api/wallet/transactions", headers=auth_headers, params={"start": "2026-01-01"}
    ).status_code == 200
    assert client.get(
        "/api/wallet/transactions", headers=auth_headers, params={"end": "2026-01-01"}
    ).status_code == 200


# ---------------------------------------------------------------- 백테스트 날짜


def _save_payload(coin: str, start: str, end: str) -> dict:
    return {
        "coin_symbol": coin,
        "strategy_type": "trend",
        "indicator": "ma",
        "params": {"interval": "1d", "short_period": 5, "long_period": 20},
        "start_date": start,
        "end_date": end,
        "initial_capital": "10000000",
        "fee_rate": "0.05",
        "slippage_rate": "0.1",
        "metrics": {
            "total_return": "0",
            "final_asset": "10000000",
            "trade_count": 0,
            "win_rate": "0",
            "mdd": "0",
            "sharpe_ratio": "0",
            "benchmark_return": "0",
            "excess_return": "0",
        },
        "equity_curve": [],
        "trades": [],
        "label": "날짜 검증",
    }


@requires_db
def test_backtest_save_rejects_inverted_date_range(client, auth_headers, test_coin):
    """`/run`은 이미 막는데 **저장 경로만 빠져 있었다** — 역전된 기간이 201로 저장됐다."""
    response = client.post(
        "/api/backtest/results",
        headers=auth_headers,
        json=_save_payload(test_coin, "2026-12-31", "2026-01-01"),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == INVALID_DATE_RANGE

    listed = client.get("/api/backtest/results", headers=auth_headers).json()
    assert listed == [], "거절된 저장이 목록에 남았다"


@requires_db
def test_backtest_save_accepts_valid_and_same_day_range(client, auth_headers, test_coin):
    """음성 대조군 — 위 400이 "저장이 통째로 망가져서"가 아님을 보인다."""
    assert client.post(
        "/api/backtest/results",
        headers=auth_headers,
        json=_save_payload(test_coin, "2026-01-01", "2026-12-31"),
    ).status_code == 201
    assert client.post(
        "/api/backtest/results",
        headers=auth_headers,
        json=_save_payload(test_coin, "2026-06-15", "2026-06-15"),
    ).status_code == 201


@requires_db
def test_backtest_run_rejects_inverted_date_range(client, auth_headers, test_coin, monkeypatch):
    monkeypatch.setattr(candles_service, "get_candles_in_range", lambda *a, **k: [])
    payload = _save_payload(test_coin, "2026-12-31", "2026-01-01")
    for key in ("metrics", "equity_curve", "trades", "label"):
        payload.pop(key)

    response = client.post("/api/backtest/run", headers=auth_headers, json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == INVALID_DATE_RANGE


# ---------------------------------------------------------------- 단기·장기 기간 (스키마)


@pytest.mark.parametrize(
    "strategy_type,extra",
    [("trend", {}), ("counter_trend", {"deviation_pct": 5})],
)
@pytest.mark.parametrize("short,long", [(50, 5), (20, 20)])
def test_ma_rejects_short_not_below_long(strategy_type, extra, short, long):
    """단기 > 장기뿐 아니라 **같은 값**도 막는다 — 두 선이 겹쳐 교차가 정의되지 않는다."""
    with pytest.raises(ValueError, match="단기 기간은 장기 기간보다 짧아야 합니다"):
        validate_params_for(
            strategy_type,
            "ma",
            {"interval": "1d", "short_period": short, "long_period": long, **extra},
        )


def test_ma_accepts_short_below_long():
    """음성 대조군 — 정상 입력이 막히지 않는다."""
    validated = validate_params_for(
        "trend", "ma", {"interval": "1d", "short_period": 5, "long_period": 20}
    )

    assert validated["short_period"] == 5
    assert validated["long_period"] == 20


def test_macd_rejects_short_not_below_long():
    with pytest.raises(ValueError, match="단기 기간은 장기 기간보다 짧아야 합니다"):
        validate_params_for(
            "trend", "macd", {"interval": "1d", "short_period": 30, "long_period": 10}
        )


def test_macd_rejects_when_only_one_side_is_sent_and_flips_the_default():
    """MACD는 기본값(12/26)이 있어 한쪽만 보내는 요청이 가능하다.

    `short_period=30`만 보내면 장기 기본값 26보다 길다 — 보낸 값끼리만 비교하는 검증은
    이걸 놓친다.
    """
    with pytest.raises(ValueError, match="단기 기간은 장기 기간보다 짧아야 합니다"):
        validate_params_for("trend", "macd", {"interval": "1d", "short_period": 30})


def test_macd_defaults_are_valid():
    validated = validate_params_for("trend", "macd", {"interval": "1d"})

    assert (validated["short_period"], validated["long_period"]) == (12, 26)


def test_swapped_periods_really_do_invert_the_signal():
    """**왜 막아야 하는지**의 증거 — 뒤집으면 같은 봉에서 신호가 정반대로 나온다.

    이 테스트가 깨지는 날(엔진이 뒤집힌 입력을 스스로 정규화하게 되는 날)은 위 검증의 필요성이
    사라진 날이다. 그때 이 파일의 단기·장기 검증을 다시 판단하면 된다.
    """
    closes = pd.Series([140 - i for i in range(30)] + [110 + i * 4 for i in range(15)], dtype=float)

    opposite = []
    for end in range(25, len(closes) + 1):
        window = closes.iloc[:end]
        normal = signals.evaluate_trend_ma(window, {"short_period": 5, "long_period": 20})
        swapped = signals.evaluate_trend_ma(window, {"short_period": 20, "long_period": 5})
        if normal and swapped and normal != swapped:
            opposite.append(end)

    assert opposite, "뒤집어도 신호가 같다 — 단기·장기 검증의 근거를 다시 확인할 것"


# ---------------------------------------------------------------- 경로: 번역된 문구 (HTTP)


@requires_db
def test_backtest_run_reports_the_period_message_not_the_generic_one(
    client, auth_headers, test_coin, monkeypatch
):
    """단기·장기 오류가 "기준값은 0~100 사이"로 번역되면 사용자가 엉뚱한 곳을 고친다."""
    monkeypatch.setattr(candles_service, "get_candles_in_range", lambda *a, **k: [])
    payload = _save_payload(test_coin, "2026-01-01", "2026-06-01")
    payload["params"] = {"interval": "1d", "short_period": 50, "long_period": 5}
    for key in ("metrics", "equity_curve", "trades", "label"):
        payload.pop(key)

    response = client.post("/api/backtest/run", headers=auth_headers, json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == PERIOD_ORDER


@requires_db
def test_slot_creation_rejects_swapped_periods(client, auth_headers, test_coin):
    """같은 검증이 자동매매 슬롯 생성도 막는다 — 팔아야 할 때 사는 슬롯이 만들어지면 안 된다."""
    response = client.post(
        "/api/strategy-slots",
        headers=auth_headers,
        json={
            "coin_symbol": test_coin,
            "strategy_type": "trend",
            "indicator": "ma",
            "params": {"interval": "1d", "short_period": 50, "long_period": 5},
            "invest_amount": "1000000",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == PERIOD_ORDER


@requires_db
def test_out_of_range_params_keep_the_generic_message(client, auth_headers, test_coin):
    """직접 올린 오류가 아닌 범위 위반(RSI 0~100)은 기존 문구를 그대로 쓴다 — 번역 변경이
    문서(07 6장)가 정한 문구를 건드리면 안 된다."""
    response = client.post(
        "/api/strategy-slots",
        headers=auth_headers,
        json={
            "coin_symbol": test_coin,
            "strategy_type": "trend",
            "indicator": "rsi",
            "params": {"interval": "1d", "period": 14, "threshold": 150},
            "invest_amount": "1000000",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "기준값은 0~100 사이의 값을 입력해주세요."


# ---------------------------------------------------------------- 지표 파라미터 범위


def _confirmed_series():
    """워커가 실제로 보는 길이의 확정봉 — 200봉을 받아 진행 중인 봉을 뺀 개수다."""
    import numpy as np

    from app.services.candles import DEFAULT_CANDLE_COUNT

    rng = np.random.default_rng(5)
    return pd.Series(100 + np.cumsum(rng.normal(0, 1, DEFAULT_CANDLE_COUNT - 1)))


def test_max_periods_still_produce_defined_values_on_worker_data():
    """**상한이 근거 있는 숫자인지** — 상한값을 넣어도 신호 함수가 보는 봉에 값이 정의돼야 한다.

    정의되지 않으면 그 상한은 "켜도 영원히 아무것도 안 하는 슬롯"을 허용하는 셈이다. 캔들 수를
    줄이거나 상한을 올리면 여기서 깨진다.
    """
    from app.schemas.strategy_slots import MACD_MAX_WINDOW, MAX_PERIOD
    from app.strategy_engine.indicators import calc_bollinger, calc_ma, calc_macd, calc_rsi

    closes = _confirmed_series()

    assert not pd.isna(calc_ma(closes, MAX_PERIOD).iloc[-2]), "MA 교차는 직전 봉까지 본다"
    assert not pd.isna(calc_rsi(closes, MAX_PERIOD).iloc[-2]), "RSI 교차는 직전 봉까지 본다"
    _, upper, _ = calc_bollinger(closes, MAX_PERIOD)
    assert not pd.isna(upper.iloc[-2]), "볼린저 돌파는 직전 봉까지 본다"

    signal = MACD_MAX_WINDOW - MAX_PERIOD
    _, _, histogram = calc_macd(closes, MAX_PERIOD - 1, MAX_PERIOD, signal)
    assert not pd.isna(histogram.iloc[-3]), "역추세 MACD는 히스토그램 세 개를 본다"


def test_macd_window_one_past_the_limit_is_undefined_on_worker_data():
    """반대쪽 경계 — 합이 한도를 1만 넘어도 워커 데이터로는 정의되지 않는다. 한도가 너무 빡빡한
    것이 아니라 정확히 맞다는 증거다."""
    from app.schemas.strategy_slots import MACD_MAX_WINDOW, MAX_PERIOD
    from app.strategy_engine.indicators import calc_macd

    signal = MACD_MAX_WINDOW - MAX_PERIOD + 1
    _, _, histogram = calc_macd(_confirmed_series(), MAX_PERIOD - 1, MAX_PERIOD, signal)

    assert pd.isna(histogram.iloc[-3])


@pytest.mark.parametrize(
    "strategy_type,indicator,params",
    [
        pytest.param("trend", "ma", {"short_period": 1, "long_period": 20}, id="MA 단기 1"),
        pytest.param("trend", "ma", {"short_period": 5, "long_period": 151}, id="MA 장기 151"),
        pytest.param("trend", "rsi", {"period": 1}, id="RSI 기간 1 (매 봉 매수·매도 반복)"),
        pytest.param("trend", "rsi", {"period": 151}, id="RSI 기간 151"),
        pytest.param("trend", "rsi", {"threshold": 0}, id="RSI 기준선 0 (영원히 신호 없음)"),
        pytest.param("trend", "rsi", {"threshold": 100}, id="RSI 기준선 100"),
        pytest.param("counter_trend", "rsi", {"oversold": 0, "overbought": 70}, id="과매도 0"),
        pytest.param("counter_trend", "rsi", {"oversold": 30, "overbought": 100}, id="과매수 100"),
        pytest.param("trend", "bollinger", {"period": 1}, id="볼린저 기간 1 (역추세는 모든 봉 매수)"),
        pytest.param("trend", "bollinger", {"std_multiplier": 5.1}, id="볼린저 배수 5.1"),
        pytest.param("trend", "bollinger", {"std_multiplier": 0}, id="볼린저 배수 0"),
        pytest.param("trend", "macd", {"signal_period": 1}, id="MACD 시그널 1 (교차 불가)"),
        pytest.param(
            "trend", "macd", {"short_period": 100, "long_period": 150, "signal_period": 49},
            id="MACD 장기+시그널 199",
        ),
    ],
)
def test_indicator_params_outside_range_are_rejected(strategy_type, indicator, params):
    with pytest.raises(ValueError):
        validate_params_for(strategy_type, indicator, {"interval": "1d", **params})


@pytest.mark.parametrize(
    "strategy_type,indicator,params",
    [
        pytest.param("trend", "ma", {"short_period": 2, "long_period": 150}, id="MA 양 끝"),
        pytest.param("trend", "rsi", {"period": 2, "threshold": 0.1}, id="RSI 하한"),
        pytest.param("trend", "rsi", {"period": 150, "threshold": 99.9}, id="RSI 상한"),
        pytest.param("trend", "bollinger", {"period": 150, "std_multiplier": 5}, id="볼린저 상한"),
        pytest.param(
            "trend", "macd", {"short_period": 100, "long_period": 150, "signal_period": 48},
            id="MACD 장기+시그널 198",
        ),
    ],
)
def test_indicator_params_at_the_boundary_are_accepted(strategy_type, indicator, params):
    """음성 대조군 — 경계값 자체는 통과해야 한다 (위의 상한 검증과 짝을 이룬다)."""
    validate_params_for(strategy_type, indicator, {"interval": "1d", **params})


@requires_db
@pytest.mark.parametrize(
    "params,expected",
    [
        ({"interval": "1d", "period": 1}, "기간은 2~150 사이의 값을 입력해주세요."),
        ({"interval": "1d", "std_multiplier": 10}, "표준편차 배수는 0보다 크고 5 이하인 값을 입력해주세요."),
    ],
)
def test_range_errors_name_the_field_instead_of_the_rsi_message(client, auth_headers, test_coin, params, expected):
    """범위 위반이 전부 "기준값은 0~100 사이"로 나가면 기간을 1로 넣은 사용자가 엉뚱한 곳을 고친다."""
    response = client.post(
        "/api/strategy-slots",
        headers=auth_headers,
        json={
            "coin_symbol": test_coin,
            "strategy_type": "trend",
            "indicator": "bollinger",
            "params": params,
            "invest_amount": "1000000",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == expected
