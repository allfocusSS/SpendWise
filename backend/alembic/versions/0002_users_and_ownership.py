"""users, sessions and per-user ownership of categories and transactions

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-01 18:00:00

Data created before accounts existed has no owner, and there is no safe way to guess one. So:

- If the database holds any transactions or user-created categories, this migration stops with
  an error and changes nothing. Back the data up and reset the database (see README,
  "Accounts and existing data") before upgrading.
- Otherwise the only rows are the global default categories. They are removed: every new
  account gets its own copy of the defaults at signup.

The downgrade returns to the 0001 schema and deletes all users, sessions, categories and
transactions, because rows owned by several users cannot be merged back into one global set.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_DATA_ERROR = (
    "This database has {transactions} transaction(s) and {categories} custom categor(ies) "
    "created before accounts existed. They cannot be assigned to a user automatically, so the "
    "upgrade was stopped and nothing was changed. Back up the data if you need it, then reset "
    "the database (Docker Compose: `docker compose down -v`; local SQLite: delete "
    "backend/spendwise.db) and start again. See README, 'Accounts and existing data'."
)


def _refuse_unowned_data() -> None:
    if context.is_offline_mode():
        return  # --sql output: there is no database to inspect
    bind = op.get_bind()
    transactions = bind.execute(sa.text("SELECT COUNT(*) FROM transactions")).scalar_one()
    custom = bind.execute(
        sa.text("SELECT COUNT(*) FROM categories WHERE is_default = :no"), {"no": False}
    ).scalar_one()
    if transactions or custom:
        raise RuntimeError(LEGACY_DATA_ERROR.format(transactions=transactions, categories=custom))


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    _refuse_unowned_data()

    # Only global default categories can be left at this point; recreate both tables with owners.
    op.drop_table("transactions")
    op.drop_table("categories")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"])

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("type IN ('income', 'expense')", name=op.f("ck_categories_type_valid")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_categories_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_categories_id_user_id")),
        sa.UniqueConstraint(
            "user_id", "name", "type", name=op.f("uq_categories_user_id_name_type")
        ),
    )
    op.create_index(op.f("ix_categories_user_id"), "categories", ["user_id"])

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_transactions_amount_positive")),
        sa.CheckConstraint(
            "type IN ('income', 'expense')", name=op.f("ck_transactions_type_valid")
        ),
        sa.CheckConstraint("source IN ('manual', 'ai')", name=op.f("ck_transactions_source_valid")),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name=op.f("fk_transactions_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_transactions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    op.create_index(op.f("ix_transactions_category_id"), "transactions", ["category_id"])
    op.create_index(op.f("ix_transactions_occurred_on"), "transactions", ["occurred_on"])
    op.create_index(op.f("ix_transactions_user_id"), "transactions", ["user_id"])


def downgrade() -> None:
    # Per-user rows cannot be merged back into one global set: everything is removed.
    op.drop_table("transactions")
    op.drop_table("categories")
    op.drop_table("sessions")
    op.drop_table("users")

    # The 0001 tables, empty (the global default categories are not restored).
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("type IN ('income', 'expense')", name=op.f("ck_categories_type_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("name", "type", name=op.f("uq_categories_name_type")),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("source IN ('manual', 'ai')", name=op.f("ck_transactions_source_valid")),
        sa.CheckConstraint(
            "type IN ('income', 'expense')", name=op.f("ck_transactions_type_valid")
        ),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_transactions_amount_positive")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_transactions_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    op.create_index(op.f("ix_transactions_category_id"), "transactions", ["category_id"])
    op.create_index(op.f("ix_transactions_occurred_on"), "transactions", ["occurred_on"])
