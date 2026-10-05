"""요청으로 들어온 금액·수량·비율 문자열을 저장 가능한 `Decimal`로 바꾼다.

금액은 부동소수점 오차를 피하려고 문자열로 받아 `Decimal(raw)`로 바꾸는데
(02-coding-conventions.md 9절), `Decimal`은 `"NaN"`·`"Infinity"`·`"1e30"`을 **정상 값으로
받아들인다.** 그대로 흘려보내면:

- `Infinity` 입금이 잔고를 `NaN`으로 바꿔 계좌가 영구히 오염된다 (이후 모든 입출금·주문 불가)
- `Infinity` 감시가격이 `NaN`으로 저장되어 매칭 루프가 매 틱 터지고, **그 코인을 거래하는
  모든 유저의 지정가 체결이 멈춘다**
- `1e-9` 수량은 검증(`> 0`)을 통과한 뒤 저장할 때 컬럼 자릿수에서 0이 되어, 0수량 주문이
  체결 단계에서 0으로 나누며 같은 사고를 낸다

그래서 **저장될 값 그대로** 검증하도록 순서를 고정한다: 유한값 확인 → 크기 확인 → 컬럼
자릿수로 내림. 호출자의 `> 0` 같은 검사는 내림이 끝난 값을 보게 된다.
"""

from decimal import ROUND_DOWN, Decimal, InvalidOperation


class InvalidDecimalInputError(ValueError):
    """숫자가 아니거나, 유한하지 않거나, 컬럼에 담기지 않는 크기다."""


def parse_decimal(raw: str, *, places: int, max_digits: int) -> Decimal:
    """`NUMERIC(max_digits, places)` 컬럼에 저장할 값으로 파싱한다.

    소수 자릿수가 넘치면 **거부하지 않고 내린다** — 화면이 금액÷가격으로 수량을 계산해 보내면
    자릿수가 길게 나오는 것이 정상이다. 내림인 이유는 매수 수량을 올리면 동결액이 요청보다
    커지기 때문이다.

    Raises:
        InvalidDecimalInputError: 숫자가 아님 / NaN·Infinity / 정수부가 컬럼보다 큼.
    """
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidDecimalInputError(raw) from exc

    if not value.is_finite():
        raise InvalidDecimalInputError(raw)

    # 내림보다 **먼저** 본다 — 1e30을 소수 8자리로 내리려면 38자리가 필요해 Decimal 기본
    # 정밀도(28자리)를 넘고, 그 자체로 InvalidOperation이 난다.
    if abs(value) >= Decimal(10) ** (max_digits - places):
        raise InvalidDecimalInputError(raw)

    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


def parse_optional_decimal(raw: str | None, *, places: int, max_digits: int) -> Decimal | None:
    if raw is None:
        return None
    return parse_decimal(raw, places=places, max_digits=max_digits)


# 컬럼별 자릿수 — 모델 정의(app/models)와 맞춘다.
KRW_AMOUNT = {"places": 4, "max_digits": 20}  # balances·deposits_withdrawals·invest_amount 등
COIN_PRICE = {"places": 8, "max_digits": 20}  # orders.price / trigger_price
COIN_QUANTITY = {"places": 8, "max_digits": 28}  # orders.quantity
PERCENT = {"places": 3, "max_digits": 6}  # 손절·익절·수수료율·슬리피지율 (최대 999.999)
RATIO_METRIC = {"places": 4, "max_digits": 10}  # 백테스트 수익률·MDD·샤프·벤치마크
