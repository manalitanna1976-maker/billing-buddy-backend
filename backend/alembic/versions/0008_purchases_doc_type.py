"""purchases.doc_type — invoice / credit_note / debit_note

The agent's ingestion pipeline now classifies each uploaded document. A
credit note / debit note is stored as a purchases row with negative totals
and negative line quantities; doc_type records which kind it is. No CHECK
constraint — consistent with status / origin / reason.

Revision ID: a7c3e1f90d24
Revises: d3f9a1c47b02
Create Date: 2026-09-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e1f90d24"
down_revision: Union[str, Sequence[str], None] = "d3f9a1c47b02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "purchases",
        sa.Column("doc_type", sa.String(length=12), nullable=False,
                  server_default="invoice"),
    )
    op.alter_column("purchases", "doc_type", server_default=None)


def downgrade() -> None:
    op.drop_column("purchases", "doc_type")
