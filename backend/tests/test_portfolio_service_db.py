"""08-portfolio 서비스 검증 (Phase A 집계 + Phase B CSV 내보내기). 실제 postgres에 붙는다.

신규 테이블이 없어 orders/holdings/deposits_withdrawals에 직접 데이터를 심고 집계
결과를 손계산 기댓값과 대조한다.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.constants import INITIAL_SEED_KRW
from app.database import session_scope
from app.models import DepositWithdrawal, Holding, Order
from app.services import portfolio as portfolio_service

from .conftest import TEST_COIN_SYMBOL, requires_db

pytestmark = requires_db


def _make_holding(user_id: int, quantity: Decimal, avg_buy_price: Decimal) -> None:
    with session_scope() as db:
        holding = db.get(Holding, (user_id, TEST_COIN_SYMBOL))
        if holding is None:
            holding = Holding(user_id=user_id, coin_symbol=TEST_COIN_SYMBOL)
            db.add(holding)
        holding.quantity = quantity
        holding.avg_buy_price = avg_buy_price


def _make_deposit_withdrawal(user_id: int, type_: str, amount: Decimal) -> None:
    with session_scope() as db:
        db.add(
            DepositWithdrawal(
                user_id=user_id,
                type=type_,
                amount=amount,
                balance_after=Decimal(0),
                created_at=datetime.now(timezone.utc),
            )
        )


def _make_order(
    user_id: int,
    side: str,
    source: str = "manual",
    status: str = "filled",
    price: Decimal = Decimal("1000"),
    quantity: Decimal = Decimal("1"),
    realized_profit: Decimal | None = None,
    filled_at: datetime | None = None,
) -> None:
    with session_scope() as db:
        db.add(
            Order(
                user_id=user_id,
                coin_symbol=TEST_COIN_SYMBOL,
                side=side,
                order_type="market",
                price=price,
                quantity=quantity,
                status=status,
                source=source,
                realized_profit=realized_profit,
                created_at=datetime.now(timezone.utc),
                filled_at=(filled_at or datetime.now(timezone.utc)) if status == "filled" else None,
            )
        )


# ── summary ──────────────────────────────────────────────────────────────


def test_get_summary_values(test_user, set_price):
    set_price(Decimal("2000"))
    _make_holding(test_user, Decimal("3"), Decimal("1500"))
    _make_deposit_withdrawal(test_user, "deposit", Decimal("500000"))
    _make_deposit_withdrawal(test_user, "withdraw", Decimal("200000"))

    with session_scope() as db:
        summary = portfolio_service.get_summary(db, test_user)

    assert summary["coin_valuation"] == Decimal("3") * Decimal("2000")
    assert summary["krw_balance"] == Decimal("10000000")  # test_user 픽스처 초기값
    assert summary["net_deposit"] == INITIAL_SEED_KRW + Decimal("500000") - Decimal("200000")


def test_get_summary_falls_back_to_avg_price_without_cached_price(test_user):
    _make_holding(test_user, Decimal("2"), Decimal("1234"))

    with session_scope() as db:
        summary = portfolio_service.get_summary(db, test_user)

    assert summary["coin_valuation"] == Decimal("2") * Decimal("1234")


def test_get_summary_ignores_zero_quantity_holdings(test_user, set_price):
    set_price(Decimal("2000"))
    _make_holding(test_user, Decimal("0"), Decimal("0"))

    with session_scope() as db:
        summary = portfolio_service.get_summary(db, test_user)

    assert summary["coin_valuation"] == Decimal("0")


# ── holdings ─────────────────────────────────────────────────────────────


def test_list_holdings_computes_profit(test_user, set_price):
    set_price(Decimal("1200"))
    _make_holding(test_user, Decimal("10"), Decimal("1000"))

    with session_scope() as db:
        items = portfolio_service.list_holdings(db, test_user)

    assert len(items) == 1
    item = items[0]
    assert item["coin_symbol"] == TEST_COIN_SYMBOL
    assert item["valuation"] == Decimal("12000")
    assert item["profit"] == Decimal("2000")
    assert item["profit_pct"] == Decimal("20")


def test_list_holdings_excludes_zero_quantity(test_user):
    _make_holding(test_user, Decimal("0"), Decimal("0"))

    with session_scope() as db:
        items = portfolio_service.list_holdings(db, test_user)

    assert items == []


# ── trades ───────────────────────────────────────────────────────────────


def test_list_trades_filters_by_side_and_source(test_user):
    _make_order(test_user, side="buy", source="manual")
    _make_order(test_user, side="sell", source="auto", realized_profit=Decimal("100"))
    _make_order(test_user, side="buy", source="auto")

    with session_scope() as db:
        items, total, _ = portfolio_service.list_trades(
            db, test_user, side="sell", source=None, coin_symbol=None, page=1, page_size=20
        )
    assert total == 1
    assert items[0]["side"] == "sell"

    with session_scope() as db:
        items, total, _ = portfolio_service.list_trades(
            db, test_user, side=None, source="auto", coin_symbol=None, page=1, page_size=20
        )
    assert total == 2


def test_list_trades_excludes_non_filled_orders(test_user):
    _make_order(test_user, side="buy", status="pending")
    _make_order(test_user, side="buy", status="filled")

    with session_scope() as db:
        items, total, _ = portfolio_service.list_trades(
            db, test_user, side=None, source=None, coin_symbol=None, page=1, page_size=20
        )
    assert total == 1


def test_list_trades_pagination(test_user):
    for _ in range(3):
        _make_order(test_user, side="buy")

    with session_scope() as db:
        items, total, _ = portfolio_service.list_trades(
            db, test_user, side=None, source=None, coin_symbol=None, page=1, page_size=2
        )
    assert total == 3
    assert len(items) == 2

    with session_scope() as db:
        items, total, _ = portfolio_service.list_trades(
            db, test_user, side=None, source=None, coin_symbol=None, page=2, page_size=2
        )
    assert len(items) == 1


def test_list_trades_traded_coins_ignore_coin_filter(test_user):
    """코인 필터를 걸어도 traded_coins는 그 필터를 제외한 나머지 조건 기준으로 나온다."""
    _make_order(test_user, side="buy")

    with session_scope() as db:
        _, _, traded_coins = portfolio_service.list_trades(
            db,
            test_user,
            side=None,
            source=None,
            coin_symbol=TEST_COIN_SYMBOL,
            page=1,
            page_size=20,
        )
    assert any(c["symbol"] == TEST_COIN_SYMBOL for c in traded_coins)


# ── CSV 내보내기 ─────────────────────────────────────────────────────────


def test_export_csv_has_bom_and_header(test_user):
    _make_order(test_user, side="buy")

    with session_scope() as db:
        csv_text = portfolio_service.export_trades_csv(
            db, test_user, side=None, source=None, coin_symbol=None
        )

    assert csv_text.startswith("﻿")  # 없으면 Excel에서 한글이 깨진다
    lines = csv_text.lstrip("﻿").splitlines()
    assert lines[0] == "체결일시,코인,유형,구분,체결가,수량"
    assert len(lines) == 2  # 헤더 + 체결 1건


def test_export_csv_applies_filters_without_pagination(test_user):
    for _ in range(25):  # 목록 페이지 크기(20)보다 많게 — 전체가 담겨야 한다
        _make_order(test_user, side="buy")
    _make_order(test_user, side="sell", realized_profit=Decimal("10"))

    with session_scope() as db:
        all_rows = portfolio_service.export_trades_csv(
            db, test_user, side=None, source=None, coin_symbol=None
        )
        buys_only = portfolio_service.export_trades_csv(
            db, test_user, side="buy", source=None, coin_symbol=None
        )

    assert len(all_rows.splitlines()) == 27  # 헤더 + 26건
    assert len(buys_only.splitlines()) == 26  # 헤더 + 매수 25건


def test_export_csv_renders_kst_and_korean_labels(test_user):
    """UTC 1월 31일 15:00은 KST로 2월 1일 00:00이다 — CSV는 KST 문자열로 굳혀 내보낸다."""
    _make_order(
        test_user,
        side="sell",
        source="auto",
        realized_profit=Decimal("10"),
        filled_at=datetime(2026, 1, 31, 15, 0, tzinfo=timezone.utc),
    )

    with session_scope() as db:
        csv_text = portfolio_service.export_trades_csv(
            db, test_user, side=None, source=None, coin_symbol=None
        )

    row = csv_text.lstrip("﻿").splitlines()[1]
    assert row.startswith("2026-02-01 00:00:00,")
    assert ",매도,자동," in row


# ── report ───────────────────────────────────────────────────────────────


def test_get_report_rejects_unknown_period(test_user):
    with session_scope() as db:
        with pytest.raises(portfolio_service.InvalidPeriodError):
            portfolio_service.get_report(db, test_user, "2m")


def test_get_report_most_traded_coin(test_user):
    _make_order(test_user, side="buy")
    _make_order(test_user, side="sell", realized_profit=Decimal("50"))

    with session_scope() as db:
        report = portfolio_service.get_report(db, test_user, "all")

    assert report["most_traded_coin"]["symbol"] == TEST_COIN_SYMBOL


def test_get_report_monthly_profit_kst_month_boundary(test_user):
    """UTC 1월 31일 15:00은 KST로 2월 1일 00:00이라 2월로 잡혀야 한다."""
    boundary_utc = datetime(2026, 1, 31, 15, 0, tzinfo=timezone.utc)
    _make_order(
        test_user, side="sell", realized_profit=Decimal("1000"), filled_at=boundary_utc
    )

    with session_scope() as db:
        report = portfolio_service.get_report(db, test_user, "all")

    months = [item["month"] for item in report["monthly_profits"]]
    assert months == ["2026-02"]
    assert report["monthly_profits"][0]["profit"] == Decimal("1000")


def test_get_report_excludes_out_of_period_orders(test_user):
    old_order_at = datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year - 2)
    _make_order(test_user, side="sell", realized_profit=Decimal("999"), filled_at=old_order_at)

    with session_scope() as db:
        report = portfolio_service.get_report(db, test_user, "1m")

    assert report["monthly_profits"] == []
