"""Every monetary field must document its unit in the OpenAPI spec."""

import pytest
from fastapi.testclient import TestClient

from app.schemas.common import MAX_AMOUNT_CENTS, TIYN_DESCRIPTION

MONEY_FIELDS = [
    ("TransactionCreate", "amount_cents"),
    ("TransactionUpdate", "amount_cents"),
    ("TransactionRead", "amount_cents"),
    ("Summary", "total_income_cents"),
    ("Summary", "total_expense_cents"),
    ("Summary", "balance_cents"),
    ("CategoryBreakdown", "total_cents"),
    ("CategoryBreakdownItem", "total_cents"),
    ("MonthlyTrendItem", "income_cents"),
    ("MonthlyTrendItem", "expense_cents"),
    ("MonthlyTrendItem", "net_cents"),
]


@pytest.fixture
def schemas(client: TestClient) -> dict:
    return client.get("/openapi.json").json()["components"]["schemas"]


def test_tiyn_description_text() -> None:
    assert TIYN_DESCRIPTION == "Amount in tiyn (1 KZT = 100 tiyn)."


@pytest.mark.parametrize("schema_name,field", MONEY_FIELDS)
def test_money_field_is_documented_in_tiyn(schemas: dict, schema_name: str, field: str) -> None:
    prop = schemas[schema_name]["properties"][field]

    assert prop["description"] == TIYN_DESCRIPTION
    assert prop["type"] == "integer"


def test_every_cents_field_in_the_spec_is_documented(schemas: dict) -> None:
    """Catches new money fields that are added without the description."""
    undocumented = [
        f"{name}.{field}"
        for name, schema in schemas.items()
        for field, prop in schema.get("properties", {}).items()
        if field.endswith("_cents") and prop.get("description") != TIYN_DESCRIPTION
    ]
    found = {
        (name, field)
        for name, schema in schemas.items()
        for field in schema.get("properties", {})
        if field.endswith("_cents")
    }

    assert undocumented == []
    assert found == set(MONEY_FIELDS), "Update MONEY_FIELDS when money fields change"


def test_request_amount_limits_are_in_the_spec(schemas: dict) -> None:
    prop = schemas["TransactionCreate"]["properties"]["amount_cents"]

    assert prop["exclusiveMinimum"] == 0
    assert prop["maximum"] == MAX_AMOUNT_CENTS
