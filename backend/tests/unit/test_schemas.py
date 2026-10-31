"""Input validation rules enforced by the Pydantic schemas."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.category import CategoryCreate, CategoryUpdate
from app.schemas.common import MAX_AMOUNT_CENTS
from app.schemas.transaction import TransactionCreate

VALID_TRANSACTION = {
    "amount_cents": 150_000,
    "type": "expense",
    "category_id": 1,
    "description": "Magnum groceries",
    "occurred_on": "2026-10-30",
}


def make_transaction(**overrides) -> TransactionCreate:
    return TransactionCreate.model_validate({**VALID_TRANSACTION, **overrides})


def test_valid_transaction_is_parsed() -> None:
    tx = make_transaction()
    assert tx.amount_cents == 150_000
    assert tx.occurred_on == date(2026, 10, 30)
    assert tx.source == "manual"


@pytest.mark.parametrize(
    "amount",
    [0, -100, 10.5, 100.0, "100", True, MAX_AMOUNT_CENTS + 1, None],
    ids=["zero", "negative", "fraction", "float", "string", "bool", "too-large", "null"],
)
def test_amount_must_be_positive_integer_cents(amount) -> None:
    with pytest.raises(ValidationError):
        make_transaction(amount_cents=amount)


def test_max_amount_is_accepted() -> None:
    assert make_transaction(amount_cents=MAX_AMOUNT_CENTS).amount_cents == MAX_AMOUNT_CENTS


@pytest.mark.parametrize("description", ["", "   ", "x" * 256])
def test_description_must_be_1_to_255_chars(description: str) -> None:
    with pytest.raises(ValidationError):
        make_transaction(description=description)


def test_description_is_trimmed() -> None:
    assert make_transaction(description="  Coffee  ").description == "Coffee"


@pytest.mark.parametrize(
    "field,value",
    [("type", "transfer"), ("occurred_on", "2026-13-01"), ("source", "bank")],
)
def test_rejects_invalid_enum_and_date_values(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        make_transaction(**{field: value})


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        make_transaction(currency="USD")


@pytest.mark.parametrize("color", ["red", "#fff", "#12345G", "123456"])
def test_category_color_must_be_hex(color: str) -> None:
    with pytest.raises(ValidationError):
        CategoryCreate(name="Pets", type="expense", color=color)


def test_category_update_rejects_explicit_null() -> None:
    with pytest.raises(ValidationError):
        CategoryUpdate.model_validate({"name": None})


def test_category_update_allows_partial_changes() -> None:
    update = CategoryUpdate.model_validate({"color": "#123abc"})
    assert update.model_dump(exclude_unset=True) == {"color": "#123abc"}
