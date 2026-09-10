"""엔진이 워커·백테스터에게 넘기는 주문 의도.

전략 엔진은 "매수/매도" 방향만이 아니라 **얼마나** 사고팔지까지 결정해야 한다. 전략유형마다
1회 주문 규모의 의미가 다르기 때문이다 (06-backtesting.md 2.4-1절):

  - 추세추종/역추세: 1회 진입에 `invest_amount` 전액
  - 그리드: 라인 하나당 `invest_amount / 격자 수`
  - DCA: 회당 매수금액

그래서 엔진은 단순한 "buy"/"sell" 대신 이 의도 목록을 돌려주고, 호출부(워커)는 그것을 그대로
주문으로 옮기기만 한다. 그리드는 한 번의 평가에서 여러 라인이 동시에 체결될 수 있어 목록이어야
한다는 점도 같은 이유다.

매수는 **금액**으로, 매도는 **수량**으로 지시한다 — 매수 체결 수량은 주문 시점 현재가에 따라
달라지므로 금액이 안정적인 단위이고, 매도는 이미 보유한 몫을 파는 것이라 수량이 자연스럽다.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class TradeIntent:
    side: Literal["buy", "sell"]
    # 매수일 때만 사용 — 수수료까지 포함해 이 금액을 넘지 않게 수량을 환산한다.
    amount: Decimal | None = None
    # 매도일 때만 사용 — 워커가 min(포지션, 가용수량)으로 한 번 더 상한을 건다.
    quantity: Decimal | None = None
    # 그리드 전용 — 체결 후 어느 라인을 채우거나 비울지 워커가 알기 위한 값.
    grid_line_index: int | None = None
