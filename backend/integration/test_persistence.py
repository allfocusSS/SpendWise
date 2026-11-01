"""Data survives `docker compose down` + `up` when the volume is kept. Runs last (restarts)."""

import httpx
import pytest

from integration.conftest import COOKIE_NAME, User
from integration.stack import Stack


def snapshot(client: httpx.Client) -> dict:
    return {
        "me": client.get("/api/auth/me").json(),
        "categories": client.get("/api/categories").json(),
        "transactions": client.get("/api/transactions").json(),
        "summary": client.get("/api/analytics/summary").json(),
        "breakdown": client.get("/api/analytics/by-category", params={"type": "expense"}).json(),
    }


@pytest.mark.restarts_stack
def test_accounts_sessions_and_data_survive_down_and_up(
    stack: Stack, alice: User, bob: User
) -> None:
    alice.post("/api/categories", json={"name": "Persisted", "type": "expense", "color": "#0EA5E9"})
    ids = alice.category_ids()
    for category, type_, amount in [
        ("Salary", "income", 600_000_00),
        ("Persisted", "expense", 1_234_56),
    ]:
        response = alice.post(
            "/api/transactions",
            json={
                "amount_cents": amount,
                "type": type_,
                "category_id": ids[category],
                "description": f"before restart: {category}",
                "occurred_on": "2026-09-15",
            },
        )
        assert response.status_code == 201, response.text
    before = snapshot(alice.client)
    assert before["transactions"]["total"] == 2
    token = alice.client.cookies[COOKIE_NAME]
    volumes = stack.volumes()
    assert len(volumes) == 1

    stack.down(volumes=False)
    assert stack.services() == {}
    assert stack.volumes() == volumes  # the database volume is kept
    stack.up(build=False)

    # The open connections died with the old containers: use new clients from here on.
    with httpx.Client(
        base_url=stack.base_url, cookies={COOKIE_NAME: token}, timeout=30
    ) as same_browser:
        assert snapshot(same_browser) == before  # same session, same data, same numbers

    with httpx.Client(base_url=stack.base_url, timeout=30) as new_browser:
        login = new_browser.post(
            "/api/auth/login", json={"email": alice.email, "password": alice.password}
        )
        assert login.status_code == 200
        assert new_browser.get("/api/transactions").json() == before["transactions"]

    with httpx.Client(base_url=stack.base_url, timeout=30) as bob_browser:
        bob_browser.post("/api/auth/login", json={"email": bob.email, "password": bob.password})
        assert bob_browser.get("/api/transactions").json()["total"] == 0

    # The schema was already current: the restart ran no migration.
    assert "Running upgrade" not in stack.compose("logs", "--no-color", "app").stdout
