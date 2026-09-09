"""전략 엔진 — 06-backtesting과 07-auto-trading이 공유하는 지표 계산 + 신호 판단 로직
(docs/02-coding-conventions.md 6장, 06-backtesting.md 2.6절).

DB·FastAPI 어느 쪽에도 의존하지 않는 순수 패키지다. 07 워커는 이 패키지의 `runner.evaluate`만
호출하고, DB 모델(`StrategySlot`) ↔ `SlotSpec` 변환은 호출부(워커) 책임으로 남긴다.
"""

from app.strategy_engine.runner import CandleLike, SlotSpec, evaluate
from app.strategy_engine.signals import Signal

__all__ = ["CandleLike", "Signal", "SlotSpec", "evaluate"]
