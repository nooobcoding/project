"""도메인 전역 상수.

여러 기능(01-auth 가입 시 지급, 08-portfolio 모의투자 초기화 등)이 공유하는
값을 한 곳에서 관리해 값이 흩어져 어긋나는 것을 방지한다.
"""

from decimal import Decimal

INITIAL_SEED_KRW = Decimal("10000000")  # 01-auth.md 5장 — 가입 시 지급 시드머니
TRADING_FEE_RATE = Decimal("0.0005")  # 01-erd.md 3.2절 — 체결 수수료율(소수 비율 단위, % 아님)
