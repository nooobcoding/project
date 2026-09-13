"""샤드 커버리지 감시 — 아무도 점유하지 않은 샤드를 잡아낸다 (06-observability.md 3.4절).

**다른 지표와 성격이 다르다. 이건 "무엇이 느린가"가 아니라 "무엇이 아예 없는가"를 본다.**

`worker_heartbeats`는 살아 있는 프로세스만 행을 남긴다. 그래서 아무도 점유하지 않은 샤드는
**행 자체가 생기지 않고, 결과적으로 아무 경고도 나지 않는다.** 모든 지표가 초록인데 그 샤드에
속한 심볼의 지정가 주문은 영영 체결되지 않는 상태가 가능하다 — 사용자에게는 "왜 체결이 안
되지?"로만 보이고 서버에는 아무 오류가 없다. 조용한 실패 금지 규칙에 정면으로 걸린다.

`matcher`(심볼 샤드)와 `worker`(유저 샤드)를 둘 다 본다. 둘은 네임스페이스가 다르고 비었을
때의 결과도 다르다 — 자세한 차이는 `check_worker_shards` 참고.

재균형 중에는 잠깐 비는 것이 정상이므로, **연속 N주기 이상 지속될 때만** 경고한다.
"""

import logging

from app.config import settings
from app.services import leader

logger = logging.getLogger(__name__)

# 이 횟수만큼 연속으로 비어 있을 때만 경고한다 — 재균형 중 한두 주기 비는 것은 정상이다.
CONSECUTIVE_MISSES_BEFORE_WARNING = 3

_consecutive_misses: dict[str, int] = {}


def check_matcher_shards() -> set[int]:
    """미점유 matcher 샤드를 돌려준다. 연속으로 비어 있으면 경고를 남긴다."""
    if settings.price_cache_backend != "redis":
        # 단일 프로세스 구성에서는 샤드 점유 자체를 하지 않는다 — 체결은 시세 루프가 직접
        # 한다(price_stream._matches_inline). 검사할 대상이 없다.
        return set()

    return _check(
        "matcher",
        leader.MATCHER_SHARD_NAMESPACE,
        "그 샤드 심볼의 지정가 주문은 체결되지 않는다",
    )


def check_worker_shards() -> set[int]:
    """미점유 worker 샤드를 돌려준다 (7단계).

    matcher와 달리 백엔드 설정에 따라 켜고 끄지 않는다 — 워커 샤딩은 Redis와 무관하게 항상
    동작하고, `SHARD_COUNT=1` + 프로세스 1개가 곧 되돌린 구성이다.

    **matcher보다 조용한 실패다.** 미점유 matcher 샤드는 "지정가가 체결 안 됨"으로 언젠가
    사용자 눈에 띄지만, 미점유 worker 샤드는 그 유저들의 자동매매가 **아무것도 하지 않는
    상태**다 — 손절도 안 걸리고 신호도 안 난다. 화면에는 슬롯이 ON으로 멀쩡히 보인다.
    """
    return _check(
        "worker",
        leader.WORKER_SHARD_NAMESPACE,
        "그 샤드 유저의 자동매매가 평가되지 않는다 (손절·익절 포함)",
    )


def _check(label: str, namespace: int, consequence: str) -> set[int]:
    try:
        occupied = leader.occupied_shards(namespace)
    except Exception:
        logger.warning("%s 샤드 커버리지 조회 실패 — 이번 주기는 건너뛴다", label)
        return set()

    missing = {shard_id for shard_id in range(settings.shard_count) if shard_id not in occupied}
    if not missing:
        _consecutive_misses[label] = 0
        return set()

    misses = _consecutive_misses.get(label, 0) + 1
    _consecutive_misses[label] = misses
    if misses >= CONSECUTIVE_MISSES_BEFORE_WARNING:
        logger.warning(
            "%s 샤드 %d/%d개가 %d주기 연속 미점유다 — %s. 미점유 샤드: %s",
            label,
            len(missing),
            settings.shard_count,
            misses,
            consequence,
            sorted(missing),
        )
    return missing
