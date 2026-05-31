"""kasse sprint2 — kasse_documents + cash_reports

Additive only:
- kasse_documents (original image/PDF audit trail, R2 key + sha256 dedup)
- cash_reports (generated PDF report metadata)

No learning tables (Phase 1 reuses existing Correction + LearningRule).
Reversible. Validated up/down round-trip on scratch SQLite.

Revision ID: 003_kasse_sprint2
Revises: 002_kasse_sprint1
Create Date: 2026-05-31 13:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "003_kasse_sprint2"
down_revision = "002_kasse_sprint1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kasse_documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("r2_key", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=40), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("doc_kind", sa.String(length=16), nullable=True),
        sa.Column("business_type", sa.String(length=24), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "sha256", name="uq_kassedoc_user_sha"),
    )
    op.create_index("ix_kasse_documents_user_id", "kasse_documents", ["user_id"])
    op.create_index("ix_kasse_documents_sha256", "kasse_documents", ["sha256"])

    op.create_table(
        "cash_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("report_type", sa.String(length=16), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("r2_key", sa.String(length=255), nullable=True),
        sa.Column("total_income", sa.Float(), nullable=True),
        sa.Column("total_expense", sa.Float(), nullable=True),
        sa.Column("profit", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_cash_reports_user_id", "cash_reports", ["user_id"])
    op.create_index("ix_cashreport_user_created", "cash_reports", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_cashreport_user_created", table_name="cash_reports")
    op.drop_index("ix_cash_reports_user_id", table_name="cash_reports")
    op.drop_table("cash_reports")
    op.drop_index("ix_kasse_documents_sha256", table_name="kasse_documents")
    op.drop_index("ix_kasse_documents_user_id", table_name="kasse_documents")
    op.drop_table("kasse_documents")
