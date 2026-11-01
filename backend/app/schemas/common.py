from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

# 10 billion KZT expressed in cents: far above any personal transaction, far below BIGINT limits.
MAX_AMOUNT_CENTS = 1_000_000_000_000

# Every money field carries this description so the unit is visible in the OpenAPI spec.
TIYN_DESCRIPTION = "Amount in tiyn (1 KZT = 100 tiyn)."

# Request amounts. strict=True rejects floats (10.5), numeric strings ("100") and booleans.
AmountCents = Annotated[
    int, Field(strict=True, gt=0, le=MAX_AMOUNT_CENTS, description=TIYN_DESCRIPTION)
]

# Response money values (totals, balances). May be zero or, for balances, negative.
MoneyCents = Annotated[int, Field(description=TIYN_DESCRIPTION)]

NonEmptyStr50 = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]
NonEmptyStr255 = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


class ErrorResponse(BaseModel):
    detail: str
