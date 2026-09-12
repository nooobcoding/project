"""08-portfolio Control 계층 — 보유자산·거래내역·성과 리포트 (조회 전용 집계).

신규 테이블 없이 orders/holdings/balances/deposits_withdrawals를 조회 시점에 집계한다
(08-portfolio.md 4장). 총손익·수익률은 여기서 계산하지 않는다 — 프론트가 실시간 시세로
평가금액을 재계산하므로(DashboardPage.tsx 패턴과 동일), 이 계층은 그 계산에 필요한
net_deposit(순투입원금)까지만 내려준다.
"""

import calendar
import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import INITIAL_SEED_KRW
from app.models import Balance, Coin, DepositWithdrawal, Holding, Order
from app.services import price_cache

_PERIOD_MONTHS = {"1m": 1, "3m": 3, "6m": 6, "1y": 12}
_KST = ZoneInfo("Asia/Seoul")
_CSV_HEADER = ("체결일시", "코인", "유형", "구분", "체결가", "수량")


class InvalidPeriodError(Exception):
    """report의 period 파라미터가 1m/3m/6m/1y/all 중 하나가 아닌 경우."""


def _current_price(holding: Holding) -> Decimal:
    cached = price_cache.get_cached_price(holding.coin_symbol)
    if cached and "trade_price" in cached:
        return Decimal(str(cached["trade_price"]))
    return holding.avg_buy_price


def _net_deposit(db: Session, user_id: int) -> Decimal:
    """순투입원금 = 초기 시드머니 + Σ입금 − Σ출금 (08-portfolio.md 2-A)."""
    transactions = db.scalars(
        select(DepositWithdrawal).where(DepositWithdrawal.user_id == user_id)
    )
    net = Decimal(0)
    for tx in transactions:
        net += tx.amount if tx.type == "deposit" else -tx.amount
    return INITIAL_SEED_KRW + net


def _subtract_months(dt: datetime, months: int) -> datetime:
    total_months = dt.month - 1 - months
    year = dt.year + total_months // 12
    month = total_months % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def get_summary(db: Session, user_id: int) -> dict[str, Decimal]:
    """상단 요약 카드 4개 중 3개(krw_balance/coin_valuation/net_deposit)를 낸다.

    보유 원화는 이 값 그대로, 나머지(총평가금액/총손익/수익률)는 프론트가 실시간 시세로
    재계산한다.
    """
    balance = db.get(Balance, user_id)
    krw_balance = balance.krw_balance if balance is not None else Decimal(0)

    holdings = db.scalars(
        select(Holding).where(Holding.user_id == user_id, Holding.quantity > 0)
    ).all()
    coin_valuation = Decimal(0)
    for holding in holdings:
        coin_valuation += holding.quantity * _current_price(holding)

    return {
        "krw_balance": krw_balance,
        "coin_valuation": coin_valuation,
        "net_deposit": _net_deposit(db, user_id),
    }


def list_holdings(db: Session, user_id: int) -> list[dict]:
    """보유 자산 현황 테이블 (08-portfolio.md 2-B)."""
    rows = db.execute(
        select(Holding, Coin.korean_name)
        .join(Coin, Coin.symbol == Holding.coin_symbol)
        .where(Holding.user_id == user_id, Holding.quantity > 0)
        .order_by(Holding.coin_symbol)
    ).all()

    items = []
    for holding, korean_name in rows:
        current_price = _current_price(holding)
        valuation = holding.quantity * current_price
        cost = holding.quantity * holding.avg_buy_price
        profit = valuation - cost
        profit_pct = profit / cost * 100 if cost > 0 else Decimal(0)
        items.append(
            {
                "coin_symbol": holding.coin_symbol,
                "korean_name": korean_name,
                "quantity": holding.quantity,
                "avg_buy_price": holding.avg_buy_price,
                "current_price": current_price,
                "valuation": valuation,
                "profit": profit,
                "profit_pct": profit_pct,
            }
        )
    return items


def _trade_conditions(user_id: int, side: str | None, source: str | None) -> list:
    """거래 내역 조회의 공통 조건. 체결분만 다룬다 — 화면 컬럼이 체결가·체결일시이고,
    월별 수익·최다 거래 코인도 체결 기준이어야 일관적이다."""
    conditions = [Order.user_id == user_id, Order.status == "filled"]
    if side is not None:
        conditions.append(Order.side == side)
    if source is not None:
        conditions.append(Order.source == source)
    return conditions


def list_trades(
    db: Session,
    user_id: int,
    side: str | None,
    source: str | None,
    coin_symbol: str | None,
    page: int,
    page_size: int,
) -> tuple[list[dict], int, list[dict]]:
    """거래 내역 목록 (08-portfolio.md 2-B). 체결분(status='filled')만 다룬다.

    traded_coins(코인 드롭다운 목록)는 코인 필터를 뺀 나머지 조건 기준으로 뽑는다 —
    코인을 고른 뒤에도 후보 목록이 그 코인 하나로 쪼그라들지 않아야 한다(계획 문서 Phase A).
    """
    conditions = _trade_conditions(user_id, side, source)

    traded_coin_rows = db.execute(
        select(Order.coin_symbol, Coin.korean_name)
        .join(Coin, Coin.symbol == Order.coin_symbol)
        .where(*conditions)
        .distinct()
        .order_by(Order.coin_symbol)
    ).all()
    traded_coins = [
        {"symbol": symbol, "korean_name": korean_name} for symbol, korean_name in traded_coin_rows
    ]

    if coin_symbol is not None:
        conditions.append(Order.coin_symbol == coin_symbol)

    total = db.scalar(select(func.count()).select_from(Order).where(*conditions)) or 0
    rows = db.execute(
        select(Order, Coin.korean_name)
        .join(Coin, Coin.symbol == Order.coin_symbol)
        .where(*conditions)
        .order_by(Order.filled_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [
        {
            "id": order.id,
            "coin_symbol": order.coin_symbol,
            "korean_name": korean_name,
            "side": order.side,
            "source": order.source,
            "price": order.price,
            "quantity": order.quantity,
            "filled_at": order.filled_at,
        }
        for order, korean_name in rows
    ]
    return items, total, traded_coins


def export_trades_csv(
    db: Session,
    user_id: int,
    side: str | None,
    source: str | None,
    coin_symbol: str | None,
) -> str:
    """거래 내역을 CSV 문자열로 만든다 (08-portfolio.md 2-B "현재 필터 조건 전체 내역").

    목록과 달리 페이지네이션이 없다 — 필터에 걸린 전체 건을 담는다.

    시각은 여기서 KST 문자열로 굳힌다. JSON 응답은 ISO datetime을 넘겨 프론트가 표시 형식을
    정하지만, CSV는 서버가 만든 결과물이 그대로 파일이 되므로 표시 형식까지 여기서 정해야 한다.
    """
    conditions = _trade_conditions(user_id, side, source)
    if coin_symbol is not None:
        conditions.append(Order.coin_symbol == coin_symbol)

    rows = db.execute(
        select(Order, Coin.korean_name)
        .join(Coin, Coin.symbol == Order.coin_symbol)
        .where(*conditions)
        .order_by(Order.filled_at.desc())
    ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_HEADER)
    for order, korean_name in rows:
        writer.writerow(
            [
                order.filled_at.astimezone(_KST).strftime("%Y-%m-%d %H:%M:%S"),
                korean_name,
                "매수" if order.side == "buy" else "매도",
                "자동" if order.source == "auto" else "수동",
                str(order.price),
                str(order.quantity),
            ]
        )
    # Excel은 BOM이 없으면 CSV를 시스템 인코딩으로 읽어 한글이 깨진다.
    return "﻿" + buffer.getvalue()


def get_report(db: Session, user_id: int, period: str) -> dict:
    """성과 분석 리포트 (08-portfolio.md 2-C, FR-P04).

    월별 수익은 실현손익(orders.realized_profit, 매도 체결에만 채워짐)을 filled_at 기준
    KST 월 경계로 그룹핑한다 — filled_at은 UTC 저장이므로 KST로 변환해야 한다
    (routers/wallet.py의 KST 변환 선례와 같은 이유).
    """
    if period != "all" and period not in _PERIOD_MONTHS:
        raise InvalidPeriodError()

    now = datetime.now(timezone.utc)
    start = None if period == "all" else _subtract_months(now, _PERIOD_MONTHS[period])

    conditions = [Order.user_id == user_id, Order.status == "filled"]
    if start is not None:
        conditions.append(Order.filled_at >= start)

    top_coin_row = db.execute(
        select(Order.coin_symbol, Coin.korean_name, func.count().label("cnt"))
        .join(Coin, Coin.symbol == Order.coin_symbol)
        .where(*conditions)
        .group_by(Order.coin_symbol, Coin.korean_name)
        .order_by(func.count().desc())
        .limit(1)
    ).first()
    most_traded_coin = (
        {"symbol": top_coin_row[0], "korean_name": top_coin_row[1]} if top_coin_row else None
    )

    month_expr = func.date_trunc("month", func.timezone("Asia/Seoul", Order.filled_at))
    monthly_rows = db.execute(
        select(month_expr.label("month"), func.sum(Order.realized_profit))
        .where(*conditions, Order.side == "sell")
        .group_by(month_expr)
        .order_by(month_expr)
    ).all()
    monthly_profits = [
        {"month": month.strftime("%Y-%m"), "profit": Decimal(str(profit))}
        for month, profit in monthly_rows
    ]

    return {
        "start": start,
        "end": now,
        "most_traded_coin": most_traded_coin,
        "monthly_profits": monthly_profits,
    }
