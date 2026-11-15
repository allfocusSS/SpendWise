"""Demo traffic for the local dashboard (docs/observability.md, "Dashboard").

    cd backend && uv run python scripts/demo_traffic.py                 # 2 minutes, port 8000
    cd backend && uv run python scripts/demo_traffic.py --minutes 5 --url http://127.0.0.1:8000

Signs up a throwaway demo user on the LOCAL stack, then for the given time saves transactions,
sometimes sends one for a category that doesn't exist (a failed save), sometimes signs in with a
wrong password (a refused sign-in), and reads lists and analytics. Only meant for a local stack:
it refuses any URL that isn't on this machine.
"""

import argparse
import random
import secrets
import sys
import time
from urllib.parse import urlsplit

import httpx


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--minutes", type=float, default=2.0)
    args = parser.parse_args(argv)
    if urlsplit(args.url).hostname not in ("127.0.0.1", "localhost"):
        print("Demo traffic is for a local stack only (127.0.0.1 or localhost).", file=sys.stderr)
        return 2

    email = f"demo-{secrets.token_hex(4)}@example.com"
    password = secrets.token_urlsafe(18)
    counts = {"saved": 0, "failed saves": 0, "refused sign-ins": 0}
    with httpx.Client(base_url=args.url, timeout=30) as client:
        signup = client.post("/api/auth/signup", json={"email": email, "password": password})
        signup.raise_for_status()
        categories = client.get("/api/categories").json()
        end = time.monotonic() + args.minutes * 60
        while time.monotonic() < end:
            category = random.choice(categories)
            body = {
                "amount_cents": random.randint(500, 2_500_000),
                "type": category["type"],
                "category_id": category["id"],
                "description": random.choice(["Groceries", "Taxi", "Coffee", "Salary", "Rent"]),
                "occurred_on": time.strftime("%Y-%m-%d"),
            }
            if random.random() < 0.1:
                body["category_id"] = 10**9  # doesn't exist: counted as a validation error
                counts["failed saves"] += client.post("/api/transactions", json=body).is_error
            else:
                counts["saved"] += client.post("/api/transactions", json=body).is_success
            if random.random() < 0.15:
                wrong = {"email": email, "password": "not the password"}
                counts["refused sign-ins"] += client.post("/api/auth/login", json=wrong).is_error
            client.get("/api/transactions")
            client.get("/api/analytics/summary")
            time.sleep(random.uniform(0.2, 0.8))
    print(", ".join(f"{count} {what}" for what, count in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
