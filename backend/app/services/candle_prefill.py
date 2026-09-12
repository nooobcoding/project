"""`scheduler` 역할의 캔들 미리 채우기 (04-async-jobs.md 3.3절, 07-roadmap.md 6단계).

워커 tick에서 Upbit REST를 빼면(03-worker-orchestration.md 5.1절) **누군가는 그 캔들을
대신 채워야 한다.** 그게 이 잡이다. 활성 슬롯이 쓰는 `(coin_symbol, interval)` 조합을
뽑아, 각 조합의 최신 봉이 DB에 없으면 채운다.

**이 잡이 밀리면 워커가 평가를 건너뛴다.** 그래서 두 가지를 지킨다:

1. **고우선 토큰 버킷으로 부른다** — 백테스트가 아무리 많이 돌아도 이쪽 몫은 못 건드린다
   (services/rate_limit.py).
2. **소요 시간을 heartbeat로 남긴다** — 채우기가 봉 주기를 넘기기 시작하면 워커 스킵으로
   이어지는데, 그 인과를 나중에 숫자로 확인할 수 있어야 한다 (06-observability.md).

**봉 하나당 조합 하나에 한 번만 시도한다.** 거래가 한 건도 없는 분봉은 Upbit에도 없어서,
"없으면 채운다"를 그대로 돌리면 그 조합은 매 주기마다 영영 헛호출을 반복한다 — 잡 주기를
20초로 잡았으니 1분봉 하나가 분당 3회를 태운다. 시도 자체를 기억해 봉이 바뀔 때까지 다시
부르지 않는다.
"""

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.database import session_scope
from app.models import StrategySlot
from app.services import candles as candles_service
from app.services import heartbeat, rate_limit

logger = logging.getLogger(__name__)

# 잡 주기. 가장 짧은 봉(1분)의 경계를 놓치지 않을 만큼 촘촘해야 하지만, 조합 수만큼 DB를
# 보므로 지나치게 짧으면 그 자체가 비용이다.
PREFILL_INTERVAL_SECONDS = 20

# 워커가 신호를 내려면 확정봉이 최소 2개 필요하다(strategy_engine/worker.py `_try_signal`).
# 지표 계산에는 더 많이 쓰이므로 채울 때는 항상 최대치를 받아 둔다 — Upbit 호출 비용은
# 개수와 무관하게 1회로 같다.
DEFAULT_INTERVAL = "1d"  # params에 interval이 없을 때 워커가 쓰는 값과 같아야 한다

# (symbol, interval) → 마지막으로 시도한 봉의 시작 시각.
_attempted: dict[tuple[str, str], datetime] = {}


def _active_targets() -> list[tuple[str, str]]:
    """활성 슬롯이 쓰는 `(coin_symbol, interval)` 조합 (04-async-jobs.md 3.3절의 SQL)."""
    with session_scope() as db:
        rows = db.execute(
            select(
                StrategySlot.coin_symbol,
                func.coalesce(StrategySlot.params["interval"].astext, DEFAULT_INTERVAL).label(
                    "interval"
                ),
            )
            .where(StrategySlot.is_active)
            .distinct()
        ).all()
    return [(row.coin_symbol, row.interval) for row in rows]


def run_prefill() -> None:
    """한 주기분 미리 채우기. `scheduler` 역할의 APScheduler가 주기적으로 호출한다.

    조합 하나의 실패가 나머지를 막지 않도록 조합 단위로 예외를 삼키되, **삼킨 예외는
    반드시 센다** (06-observability.md 5장).
    """
    started_at = datetime.now(timezone.utc)
    start = time.monotonic()
    error_count = 0
    skip_count = 0

    try:
        targets = _active_targets()
    except Exception:
        logger.exception("캔들 미리 채우기: 대상 조회 실패")
        _record(started_at, start, item_count=0, error_count=1, skip_count=0)
        return

    for symbol, interval in targets:
        if interval not in candles_service._INTERVAL_SECONDS:
            # 슬롯 생성 경로가 막고 있어 정상적으로는 나오지 않는다. 나왔다면 그 슬롯은
            # 워커도 평가하지 못하는 상태이므로 조용히 넘기면 안 된다.
            logger.warning(
                "캔들 미리 채우기: 알 수 없는 봉단위 %s (symbol=%s) — 건너뛴다", interval, symbol
            )
            skip_count += 1
            continue

        target_bucket = candles_service._current_bucket_start(
            interval, datetime.now(timezone.utc)
        )
        if _attempted.get((symbol, interval)) == target_bucket:
            continue
        # 성공/실패와 무관하게 먼저 기록한다 — 실패했을 때 같은 봉을 주기마다 다시 두드리는
        # 것이 정확히 막으려던 헛호출이다.
        _attempted[(symbol, interval)] = target_bucket

        try:
            with rate_limit.priority("high"):
                with session_scope() as db:
                    candles_service.get_candles(db, symbol, interval)
        except candles_service.CoinNotFoundError:
            # 상장폐지된 코인에 활성 슬롯이 남아 있다. 워커도 이 슬롯을 평가하지 못한다.
            logger.warning("캔들 미리 채우기: 상장폐지 코인의 활성 슬롯 (symbol=%s)", symbol)
            skip_count += 1
        except rate_limit.RateLimitTimeout:
            logger.warning(
                "캔들 미리 채우기: 토큰 대기 초과 (symbol=%s interval=%s) — 워커가 이 봉을 "
                "건너뛴다",
                symbol,
                interval,
            )
            error_count += 1
        except Exception:
            logger.exception("캔들 미리 채우기 실패 (symbol=%s interval=%s)", symbol, interval)
            error_count += 1

    _prune(targets)
    _record(started_at, start, len(targets), error_count, skip_count)


def _prune(targets: list[tuple[str, str]]) -> None:
    """더 이상 활성이 아닌 조합의 기억을 버린다. 안 버리면 슬롯을 껐다 켤 때마다 쌓인다."""
    live = set(targets)
    for key in [key for key in _attempted if key not in live]:
        del _attempted[key]


def _record(
    started_at: datetime, start: float, item_count: int, error_count: int, skip_count: int
) -> None:
    duration_ms = int((time.monotonic() - start) * 1000)
    try:
        heartbeat.record_tick(
            role="candle-prefill",
            shard_id=None,
            started_at=started_at,
            duration_ms=duration_ms,
            # 채우기가 잡 주기를 넘기면 그만큼 대상이 밀린다 — 그 시점이 곧 워커 스킵의
            # 시작점이므로 예산을 잡 주기로 잡는다 (06-observability.md 3장).
            budget_ms=PREFILL_INTERVAL_SECONDS * 1000,
            item_count=item_count,
            error_count=error_count,
            skip_count=skip_count,
        )
    except Exception:
        # 관측이 관측 대상을 망가뜨려서는 안 된다 (strategy_engine/worker.py와 같은 원칙).
        logger.exception("캔들 미리 채우기: heartbeat 기록 실패")
