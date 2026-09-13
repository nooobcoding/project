"""샤드 계산 — 심볼을 `matcher` 샤드에 배정한다 (확장판 00-architecture.md 3.1절).

**역할마다 샤딩 키가 다르다.** `matcher`는 `coin_symbol`이다 — 틱이 심볼 단위로 오고 한
심볼 안에서의 체결 순서를 보장해야 하기 때문이다. `worker`는 `user_id`를 쓴다(7단계): 슬롯
평가에는 심볼 순서가 필요 없고 균등 분포가 훨씬 중요한데, 심볼로 나누면 BTC 쏠림 하나로
프로세스를 늘려도 유효 병렬도가 안 오른다.

`SHARD_COUNT`는 고정 상수다. 바꾸면 재해싱이 일어나므로 함부로 조정하지 않는다.
"""

from zlib import crc32

from app.config import settings


def shard_of(symbol: str) -> int:
    """심볼이 속한 샤드 번호. 애플리케이션에서만 계산하고 SQL에 넘기지 않는다 —
    Python `zlib.crc32`와 SQL이 같은 값을 내는지 맞출 필요를 없애기 위해서다
    (02-market-data.md 4.3절). KRW 마켓이 200종 남짓이라 심볼 목록을 넘기는 비용은
    무시할 만하다."""
    return crc32(symbol.encode()) % settings.shard_count


def shard_of_user(user_id: int) -> int:
    """유저가 속한 `worker` 샤드 번호 (7단계).

    `crc32`가 아니라 나머지 연산인 것이 중요하다 — **애플리케이션과 SQL이 같은 식을 그대로
    쓸 수 있다.** 워커는 자기 샤드의 슬롯을 SQL로 골라내야 하는데(`user_id % :n = ANY(:owned)`),
    crc32였다면 Python `zlib.crc32`와 PostgreSQL이 같은 값을 내는지부터 맞춰야 했다
    (03-worker-orchestration.md 2.1절).
    """
    return user_id % settings.shard_count


def owned_by_user_shard(user_id_column, owned: set[int]):
    """`user_id % SHARD_COUNT IN (...)` SQL 조건 (03-worker-orchestration.md 2.1절).

    워커 tick과 샤드 재조정이 **같은 조건으로 같은 슬롯 집합**을 골라야 한다 — 둘이 어긋나면
    "평가는 되는데 재조정은 안 되는" 슬롯이 생기고, 그건 정확히 재조정이 막으려던 사고가
    조용히 남는 상태다. 그래서 한 곳에서만 만든다.
    """
    return (user_id_column % settings.shard_count).in_(sorted(owned))


def all_shards() -> range:
    return range(settings.shard_count)
