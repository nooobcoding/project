"""03-manual-trading 요청/응답 DTO — 코인 목록/가용잔고.

금액·비율 필드는 문자열로 반환한다 (02-coding-conventions.md 9절).
"""

from pydantic import BaseModel


class CoinResponse(BaseModel):
    symbol: str
    korean_name: str
    english_name: str
    current_price: str | None
    change_rate: str | None


class AvailableBalanceResponse(BaseModel):
    available_krw: str
    available_quantity: str
