"""캔들 응답 DTO (Boundary 계층 계약, models와 별개로 유지).

가격·거래량은 문자열로 반환한다 (02-coding-conventions.md 9절).
"""

from datetime import datetime

from pydantic import BaseModel


class CandleResponse(BaseModel):
    opened_at: datetime
    open: str
    high: str
    low: str
    close: str
    volume: str
