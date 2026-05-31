"""kasse sprint1 — cash_categories + cash_entries additive columns/indexes

Additive only. Safe on a populated prod DB:
- new table cash_categories
- cash_entries: +category_id, +net_amount, +source, +status,
  +ocr_document_id, +extraction_meta (all NULLABLE → no rewrite)
- 3 composite indexes on cash_entries

batch_alter_table used for SQLite compatibility (local tests) and works
on PostgreSQL too. Reversible via downgrade().

Revision ID: 002_kasse_sprint1
Revises: 001_baseline
Create Date: 2026-05-31 12:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "002_kasse_sprint1"
down_revision = "001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) New table: cash_categories
    op.create_table(
        "cash_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("datev_konto", sa.String(length=10), nullable=True),
        sa.Column("euer_line", sa.String(length=40), nullable=True),
        sa.Column("default_vat_rate", sa.String(length=4), nullable=True),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column("icon", sa.String(length=40), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "name", name="uq_cashcat_user_name"),
    )
    op.create_index("ix_cash_categories_user_id", "cash_categories", ["user_id"])
    op.create_index("ix_cashcat_user_kind", "cash_categories", ["user_id", "kind"])

    # 2) Additive columns on cash_entries (all nullable)
    with op.batch_alter_table("cash_entries") as b:
        b.add_column(sa.Column("category_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("net_amount", sa.Float(), nullable=True))
        b.add_column(sa.Column("source", sa.String(length=16), nullable=True, server_default="manual"))
        b.add_column(sa.Column("status", sa.String(length=16), nullable=True, server_default="confirmed"))
        b.add_column(sa.Column("ocr_document_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("extraction_meta", sa.Text(), nullable=True))

    # 3) Indexes on cash_entries
    op.create_index("ix_cash_entries_category_id", "cash_entries", ["category_id"])
    op.create_index("ix_cash_user_date", "cash_entries", ["user_id", "date"])
    op.create_index("ix_cash_user_type_date", "cash_entries", ["user_id", "entry_type", "date"])
    op.create_index("ix_cash_user_status", "cash_entries", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_cash_user_status", table_name="cash_entries")
    op.drop_index("ix_cash_user_type_date", table_name="cash_entries")
    op.drop_index("ix_cash_user_date", table_name="cash_entries")
    op.drop_index("ix_cash_entries_category_id", table_name="cash_entries")
    with op.batch_alter_table("cash_entries") as b:
        b.drop_column("extraction_meta")
        b.drop_column("ocr_document_id")
        b.drop_column("status")
        b.drop_column("source")
        b.drop_column("net_amount")
        b.drop_column("category_id")
    op.drop_index("ix_cashcat_user_kind", table_name="cash_categories")
    op.drop_index("ix_cash_categories_user_id", table_name="cash_categories")
    op.drop_table("cash_categories")
