"""백테스트 시뮬레이터 (06 계획 A-4) — 과거 캔들을 재생하며 워커의 tick과 같은 순서로 처리한다.

**설계의 핵심은 "직접 계산하지 않는 것"이다.** 이 모듈이 자체적으로 하는 산술은 **현금 잔고**
하나뿐이고, 나머지는 전부 실매매가 쓰는 바로 그 함수를 호출한다:

| 하는 일 | 쓰는 함수 | 실매매에서 같은 함수를 쓰는 곳 |
|---|---|---|
| 청산 판정 | `exits.decide_exit` | `worker._try_exit` |
| 신호 판정·주문 규모 | `runner.evaluate` | `worker._try_signal` / `_try_dca` |
| 체결가(슬리피지) | `costs.calc_fill_price` | (실체결은 미적용 — 의도된 비대칭) |
| 수수료·체결액·실현손익 | `costs.calc_*` | `services/matcher.py` |
| 포지션 산술(평단·수량) | `slot_state.apply_buy/apply_sell` | `matcher._apply_auto_trading_hook` |
| 그리드 라인·DCA 진행 | `grid.mark_line_*` / `dca.advance_after_buy` | `worker._write_grid_lines` / `_execute_dca_buy` |

그래서 이 파일이 실매매와 어긋날 수 있는 지점은 "순서"와 "현금"뿐이며, 둘 다 아래 한 함수
(`_process_candle`)에 모여 있다.

**봉 하나를 처리하는 순서** (워커 tick과 동일)
  1. 청산 판정 — 있으면 집행하고 이번 봉은 여기서 끝낸다 (워커가 `_try_exit` 후 return하는 것과 같다).
  2. 신호 평가 — 나온 주문 의도를 순서대로 집행한다.
  3. 봉 끝에 자산(현금 + 보유수량 × 종가)을 수익 곡선에 적립한다.

**시간 축의 단순화**: 워커는 10초마다 돌지만 시뮬레이터는 봉 하나를 1 tick으로 본다. 봉 안에서의
가격 흔들림은 종가로만 대표되므로, 봉 중간에 손절선을 찍고 회복한 경우는 재현되지 않는다 —
봉단위를 잘게 잡을수록 실제에 가까워진다.

**현금 부족**: 의도한 금액보다 현금이 적으면 있는 만큼 산다 — 실매매(워커)가 주문을 통째로
건너뛰는 것과 다른, 의도된 비대칭이다. 이유는 `_Simulator._buy` 주석에 있다.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any, Sequence

from app.services import slot_state
from app.strategy_engine import costs, dca, exits, grid, runner
from app.strategy_engine.intents import TradeIntent
from app.strategy_engine.runner import CandleLike, SlotSpec

_QUANTITY_STEP = Decimal("0.00000001")  # orders.quantity NUMERIC(28,8)

# 지표 계산에 넘기는 캔들 창의 최대 길이 (06 계획 A-0에서 실측 후 확정).
#
# 신호 판정에 필요한 것은 최근 지표값 2~3개뿐인데(signals.py), 창을 자르지 않으면 봉마다 전
# 구간을 다시 계산해 비용이 O(n²)이 된다. 1분봉 7일(10,080봉) 실측:
#
#     전략          창 무제한   창 300봉
#     추세추종/MA     21.9s       4.3s
#     추세추종/RSI    33.4s      13.0s   ← 30초 목표(FR-B05) 초과
#
# **결과 차이**: 같은 실측에서 거래 건수(647·1,211건)와 최종 자산이 양쪽 완전히 일치했다.
# SMA·볼린저는 창 안에서 완결되는 계산이라 애초에 동일하고, RSI(Wilder)·MACD(지수이동평균)만
# 이론상 창 시작점의 영향이 남지만 기본 파라미터(RSI 14 / MACD 26·12·9)의 20배가 넘는 300봉을
# 데우고 나면 그 잔차가 신호 판정을 바꾸지 못한다.
INDICATOR_LOOKBACK = 300


@dataclass(frozen=True)
class BacktestTrade:
    """체결 1건 (01-erd.md `backtest_trades`). 수익 곡선의 마커 클릭 시 보여줄 상세다."""

    side: str
    price: Decimal  # 슬리피지가 반영된 체결가
    quantity: Decimal
    amount: Decimal  # 수수료까지 반영된 현금 증감액
    profit: Decimal | None  # 매도만 — 실현손익. 매수는 None.
    executed_at: datetime
    reason: str  # 신호/청산 사유 (exits.*, dca.* 상수). 저장하지 않고 디버깅·표시용.


@dataclass(frozen=True)
class EquityPoint:
    """수익 곡선의 한 점 (01-erd.md `backtest_results.equity_curve`)."""

    at: datetime
    asset: Decimal


@dataclass
class BacktestRun:
    """시뮬레이션 결과 원자료. 성과지표 계산(Phase B)은 이 값만 보고 한다."""

    initial_capital: Decimal
    final_asset: Decimal
    cash: Decimal
    position: dict[str, Any] | None
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)


def run_backtest(
    candles: Sequence[CandleLike],
    spec: SlotSpec,
    initial_capital: Decimal,
    fee_rate: Decimal,
    slippage_rate: Decimal = Decimal("0"),
) -> BacktestRun:
    """캔들을 시간순으로 재생하며 전략을 시뮬레이션한다.

    Args:
        candles: 오래된 순으로 정렬된 확정봉. 진행 중인 봉은 호출자가 빼야 한다.
        spec: 평가할 전략 스펙. `state`는 여기서 시뮬레이션용으로 새로 만들어 쓰므로 비어 있어도 된다.
        initial_capital: 시작 현금(원).
        fee_rate: 수수료율 **소수 비율**(0.05% → `Decimal("0.0005")`). % 단위 컬럼값은 호출자가
            `costs.percent_to_decimal`로 변환해 넘긴다 (costs.py 단위 규칙).
        slippage_rate: 슬리피지율 소수 비율. 백테스팅 전용이다 (00-overview.md 원칙 7).

    Returns:
        체결 목록·수익 곡선·최종 자산이 담긴 `BacktestRun`.
    """
    sim = _Simulator(spec, initial_capital, fee_rate, slippage_rate)
    for index, candle in enumerate(candles):
        sim.process_candle(candles, index, candle)
    return sim.result()


class _Simulator:
    """시뮬레이션 도중의 가변 상태. 실매매의 DB(슬롯 state·잔고) 자리를 메모리가 대신한다."""

    def __init__(
        self,
        spec: SlotSpec,
        initial_capital: Decimal,
        fee_rate: Decimal,
        slippage_rate: Decimal,
    ) -> None:
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate

        self.cash = initial_capital
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[EquityPoint] = []
        # 슬롯 OFF에 해당한다 — DCA 목표 수익률 익절 뒤에는 더 매수하지 않는다
        # (06-backtesting.md 2.5절 "전량 매도 후 전략 종료"). 곡선은 현금만으로 계속 그린다.
        self.stopped = False

        # 실매매의 `strategy_slots.state`와 같은 모양으로 들고 다닌다 — 엔진 함수들이 이 스키마를
        # 전제로 읽고 쓰기 때문이다 (01-erd.md 3.6절). 호출자의 spec을 건드리지 않도록 이 dict를
        # 가리키는 사본을 만든다 — 그러면 runner.evaluate가 갱신된 상태를 그대로 본다.
        self.state: dict[str, Any] = {}
        self.spec = replace(spec, state=self.state)
        if spec.strategy_type == "grid":
            self.state["grid"] = {"lines": grid.initial_lines(spec.params)}

    # ── 봉 1개 처리 ────────────────────────────────────────────────────────

    def process_candle(self, candles: Sequence[CandleLike], index: int, candle: CandleLike) -> None:
        price = candle.close
        at = candle.opened_at

        if not self._try_exit(price, at):
            self._try_signal(candles, index, price, at)

        self.equity_curve.append(EquityPoint(at=at, asset=self._asset(price)))

    def _try_exit(self, price: Decimal, at: datetime) -> bool:
        """청산 판정 — 집행했으면 True(이번 봉은 재진입하지 않는다)."""
        position = slot_state.read_position(self.state)
        if position is None:
            return False

        intent = exits.decide_exit(self.spec, position, price)
        if intent is None:
            return False

        if not self._sell(intent, price, at):
            return False

        if intent.reason == exits.GRID_BREAKOUT:
            # 라인을 전부 비운다 — 포지션이 사라졌는데 "채워짐"으로 남으면 가격이 회복돼도 그
            # 라인은 다시 매수되지 않는다 (worker._record_exit과 같은 처리).
            self.state["grid"] = {"lines": grid.initial_lines(self.spec.params)}
        elif intent.reason == exits.DCA_TAKE_PROFIT:
            self.stopped = True
        return True

    def _try_signal(
        self, candles: Sequence[CandleLike], index: int, price: Decimal, at: datetime
    ) -> None:
        if self.stopped:
            return

        window = candles[max(0, index + 1 - INDICATOR_LOOKBACK) : index + 1]
        # `now`는 재생 중인 봉의 시각이다 — DCA의 시간 스케줄이 과거 시간축을 따라 흐르게 한다.
        for intent in runner.evaluate(self.spec, window, now=at, current_price=price):
            self._execute(intent, price, at)

    # ── 체결 시뮬레이션 ────────────────────────────────────────────────────

    def _execute(self, intent: TradeIntent, price: Decimal, at: datetime) -> None:
        if intent.side == "buy":
            self._buy(intent, price, at)
        else:
            self._sell(intent, price, at)

    def _buy(self, intent: TradeIntent, price: Decimal, at: datetime) -> bool:
        # 현금이 의도한 금액보다 적으면 **있는 만큼** 산다. 워커는 이 상황에서 주문을 통째로
        # 건너뛰지만(InsufficientBalanceError), 그 동작을 그대로 옮기면 백테스트가 무의미해진다:
        # 백테스팅은 초기투자금 = 1회 진입 금액이라, 왕복 한 번에 수수료·슬리피지만큼만 줄어도
        # 이후 모든 매수가 영구히 스킵돼 손실 전략이 "거래 2건"으로 끝난다 (06 계획 A-0 실측에서
        # 발견). 실매매에서 스킵이 옳은 이유는 슬롯 배정액 밖의 **사용자 다른 자금**을 건드리면
        # 안 되기 때문인데, 백테스트에는 그런 외부 자금이 없다 — 슬리피지와 같은 성격의
        # **의도된 비대칭**이며 06-backtesting.md에 명시한다.
        budget = min(intent.amount or Decimal(0), self.cash)
        fill_price = costs.calc_fill_price(price, "buy", self.slippage_rate)
        quantity = costs.calc_buy_quantity(budget, fill_price, self.fee_rate)
        if quantity <= 0:
            self._on_buy_skipped(intent, at)
            return False

        # 8자리 내림 덕분에 항상 budget 이하이고, budget ≤ cash이므로 잔고가 음수가 되지 않는다.
        amount = costs.calc_buy_amount(fill_price, quantity, self.fee_rate)
        self.cash -= amount
        self.state["position"] = slot_state.apply_buy(
            slot_state.read_position(self.state), fill_price, quantity, self.fee_rate, at
        )
        self._record(intent, "buy", fill_price, quantity, amount, profit=None, at=at)
        self._on_buy_filled(intent, fill_price, quantity, amount, at)
        return True

    def _sell(self, intent: TradeIntent, price: Decimal, at: datetime) -> bool:
        position = slot_state.read_position(self.state)
        if position is None:
            return False

        # 보유분을 넘겨 팔지 않는다 — 워커의 min(요청, 포지션, 가용수량) 상한과 같은 방어다.
        quantity = min(intent.quantity or Decimal(0), Decimal(position["quantity"]))
        quantity = quantity.quantize(_QUANTITY_STEP, rounding=ROUND_DOWN)
        if quantity <= 0:
            return False

        fill_price = costs.calc_fill_price(price, "sell", self.slippage_rate)
        avg_buy_price = Decimal(position["avg_price"])
        amount = costs.calc_sell_amount(fill_price, quantity, self.fee_rate)
        profit = costs.calc_realized_profit(fill_price, quantity, avg_buy_price, self.fee_rate)

        self.cash += amount
        new_position = slot_state.apply_sell(position, quantity)
        if new_position is None:
            self.state.pop("position", None)
        else:
            self.state["position"] = new_position

        self._record(intent, "sell", fill_price, quantity, amount, profit=profit, at=at)
        if intent.grid_line_index is not None:
            self._update_grid_lines(grid.mark_line_empty, intent.grid_line_index)
        return True

    # ── 체결 후 전략 상태 갱신 (실매매와 같은 함수) ───────────────────────

    def _on_buy_filled(
        self, intent: TradeIntent, fill_price: Decimal, quantity: Decimal, amount: Decimal, at: datetime
    ) -> None:
        if intent.grid_line_index is not None:
            self._update_grid_lines(grid.mark_line_filled, intent.grid_line_index, quantity)
        elif self.spec.strategy_type == "dca":
            # 지출은 수수료까지 포함한 실제 체결액으로 쌓는다 (worker._execute_dca_buy와 동일).
            self.state["dca"] = dca.advance_after_buy(
                dca.read_state(self.state), intent, fill_price, amount, at, self.spec.params
            )

    def _on_buy_skipped(self, intent: TradeIntent, at: datetime) -> None:
        """사지 못한 회차의 뒷정리 — DCA 정기 매수는 예정 시각을 밀어 다음 회차로 넘긴다."""
        if self.spec.strategy_type == "dca" and intent.reason == dca.SCHEDULED_BUY:
            self.state["dca"] = dca.skip_scheduled_buy(
                dca.read_state(self.state), at, self.spec.params
            )

    def _update_grid_lines(self, mark, line_index: int, *args: Any) -> None:
        lines = slot_state.read_grid_lines(self.state)
        if lines:
            self.state["grid"] = {"lines": mark(lines, line_index, *args)}

    # ── 집계 ───────────────────────────────────────────────────────────────

    def _record(
        self,
        intent: TradeIntent,
        side: str,
        price: Decimal,
        quantity: Decimal,
        amount: Decimal,
        profit: Decimal | None,
        at: datetime,
    ) -> None:
        self.trades.append(
            BacktestTrade(
                side=side,
                price=price,
                quantity=quantity,
                amount=amount,
                profit=profit,
                executed_at=at,
                reason=intent.reason,
            )
        )

    def _position_quantity(self) -> Decimal:
        position = slot_state.read_position(self.state)
        return Decimal(position["quantity"]) if position else Decimal(0)

    def _asset(self, price: Decimal) -> Decimal:
        """평가자산 = 현금 + 보유수량 × 종가. 미실현 손익까지 반영한 값이다."""
        return self.cash + self._position_quantity() * price

    def result(self) -> BacktestRun:
        final_asset = self.equity_curve[-1].asset if self.equity_curve else self.initial_capital
        return BacktestRun(
            initial_capital=self.initial_capital,
            final_asset=final_asset,
            cash=self.cash,
            position=slot_state.read_position(self.state),
            trades=self.trades,
            equity_curve=self.equity_curve,
        )
