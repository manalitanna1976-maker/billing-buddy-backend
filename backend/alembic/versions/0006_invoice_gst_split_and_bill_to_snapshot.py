"""invoice: GST split + discount/round-off amounts, bill-to snapshot, finalize, wider numerics

Revision ID: c1a7f0b2e5d4
Revises: 134e2bbc2775
Create Date: 2026-09-07 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1a7f0b2e5d4"
down_revision: Union[str, Sequence[str], None] = "134e2bbc2775"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MONEY = sa.Numeric(18, 2)


def upgrade() -> None:
    # --- bill-to snapshot -------------------------------------------------- #
    op.add_column("invoices", sa.Column("bill_to_name", sa.String(200), nullable=True))
    op.add_column("invoices", sa.Column("bill_to_address", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("bill_to_gstin", sa.String(15), nullable=True))
    op.add_column("invoices", sa.Column("bill_to_pan", sa.String(10), nullable=True))
    op.add_column("invoices", sa.Column("bill_to_state", sa.String(100), nullable=True))
    op.add_column("invoices", sa.Column("bill_to_phone", sa.String(20), nullable=True))
    op.add_column("invoices", sa.Column("ship_to", sa.Text(), nullable=True))

    # --- GST split + amounts -------------------------------------------------- #
    for col in (
        "discount_amount",
        "cgst_total",
        "sgst_total",
        "igst_total",
        "round_off_amount",
    ):
        op.add_column(
            "invoices",
            sa.Column(col, _MONEY, nullable=False, server_default="0"),
        )

    op.add_column("invoices", sa.Column("finalized_at", sa.DateTime(), nullable=True))

    # --- widen numerics / discount_type ---------------------------------- #
    op.alter_column("invoices", "discount_type", type_=sa.String(4))
    for col in ("discount_value", "tcs", "taxable_total", "tax_total", "grand_total"):
        op.alter_column("invoices", col, type_=_MONEY)
    op.alter_column("invoice_line_items", "qty", type_=sa.Numeric(15, 3))
    op.alter_column("invoice_line_items", "price", type_=sa.Numeric(15, 2))
    op.alter_column("invoice_line_items", "discount", type_=sa.Numeric(15, 2))
    op.alter_column("invoice_line_items", "gst_rate", type_=sa.Numeric(5, 2))
    op.alter_column("invoice_line_items", "line_total", type_=_MONEY)

    # backfill snapshot for existing rows from the current customer record
    op.execute(
        """
        UPDATE invoices i SET
            bill_to_name = c.name,
            bill_to_address = c.address,
            bill_to_gstin = c.gstin,
            bill_to_pan = c.pan,
            bill_to_state = c.place_of_supply,
            bill_to_phone = c.phone,
            ship_to = c.ship_to
        FROM customers c
        WHERE i.customer_id = c.id AND i.bill_to_name IS NULL
        """
    )

    # drop the server_default now that existing rows are populated; the app sets it
    for col in (
        "discount_amount",
        "cgst_total",
        "sgst_total",
        "igst_total",
        "round_off_amount",
    ):
        op.alter_column("invoices", col, server_default=None)


def downgrade() -> None:
    op.alter_column("invoice_line_items", "line_total", type_=sa.Numeric(12, 2))
    op.alter_column("invoice_line_items", "gst_rate", type_=sa.Numeric(4, 2))
    op.alter_column("invoice_line_items", "discount", type_=sa.Numeric(12, 2))
    op.alter_column("invoice_line_items", "price", type_=sa.Numeric(12, 2))
    op.alter_column("invoice_line_items", "qty", type_=sa.Numeric(12, 3))
    for col in ("discount_value", "tcs", "taxable_total", "tax_total", "grand_total"):
        op.alter_column("invoices", col, type_=sa.Numeric(12, 2))
    op.alter_column("invoices", "discount_type", type_=sa.String(3))

    for col in (
        "finalized_at",
        "round_off_amount",
        "igst_total",
        "sgst_total",
        "cgst_total",
        "discount_amount",
        "ship_to",
        "bill_to_phone",
        "bill_to_state",
        "bill_to_pan",
        "bill_to_gstin",
        "bill_to_address",
        "bill_to_name",
    ):
        op.drop_column("invoices", col)
