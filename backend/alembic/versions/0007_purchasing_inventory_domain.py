"""purchasing / inventory shared domain: suppliers, products, purchases,
purchase_line_items, stock_movements

Adds the shared purchasing/inventory tables that ``billing-buddy-agent`` writes
to and reads back. The agent hand-writes matching SQLAlchemy models and runs
``verify_schema()`` on startup — it refuses to start on drift. The authoritative
column list is ``docs/handoff/purchasing-tables.md`` in that repo; keep this
migration, that doc, and ``app/models.py`` in lockstep.

Differences from the handoff DDL, on purpose:

* ``purchases`` gains ``shipping_total`` / ``other_charges`` / ``round_off``
  (numeric(12, 2), NOT NULL, default 0; ``round_off`` may be negative) for the
  freight / packing / rounding split the agent reconciles the grand total
  against. The agent's persist stage writes them; the full breakdown is also
  kept in ``agent.ingestion_runs.extracted_payload``.
* Server-side ``DEFAULT gen_random_uuid()`` / ``DEFAULT now()`` / ``DEFAULT 0``
  from the handoff DDL are omitted to match CRM's existing convention — every
  other CRM table relies on the app/ORM to supply id, created_at and zero
  money totals. The agent always does (client-side SQLAlchemy defaults).

The ``agent`` schema (``agent.source_documents``, ``agent.ingestion_runs``) is
owned end to end by ``billing-buddy-agent``. This migration must not, and does
not, touch it. ``purchases.source_document_id`` is an unenforced UUID reference
to ``agent.source_documents`` — deliberately NO cross-schema foreign key.

Revision ID: d3f9a1c47b02
Revises: c1a7f0b2e5d4
Create Date: 2026-09-09 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3f9a1c47b02"
down_revision: Union[str, Sequence[str], None] = "c1a7f0b2e5d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MONEY = sa.Numeric(12, 2)
_QTY = sa.Numeric(12, 3)
_RATE = sa.Numeric(4, 2)


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_norm", sa.String(length=200), nullable=False),
        sa.Column("gstin", sa.String(length=15), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("state_code", sa.String(length=2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_suppliers_business_id", "suppliers", ["business_id"], unique=False)
    op.create_index(
        "ux_suppliers_business_id_name_norm",
        "suppliers",
        ["business_id", "name_norm"],
        unique=True,
    )
    op.create_index(
        "ix_suppliers_business_id_gstin",
        "suppliers",
        ["business_id", "gstin"],
        unique=False,
    )

    op.create_table(
        "products",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_norm", sa.String(length=200), nullable=False),
        sa.Column("hsn_sac", sa.String(length=10), nullable=True),
        sa.Column("uom", sa.String(length=20), nullable=True),
        sa.Column("current_qty", _QTY, nullable=False),
        sa.Column("reorder_level", _QTY, nullable=True),
        sa.Column("default_purchase_price", _MONEY, nullable=True),
        sa.Column("auto_created", sa.Boolean(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_business_id", "products", ["business_id"], unique=False)
    op.create_index(
        "ux_products_business_id_name_norm",
        "products",
        ["business_id", "name_norm"],
        unique=True,
    )

    op.create_table(
        "purchases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("supplier_id", sa.UUID(), nullable=True),
        # unenforced ref to agent.source_documents — NO cross-schema FK
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("invoice_no", sa.String(length=50), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("po_no", sa.String(length=50), nullable=True),
        sa.Column("taxable_total", _MONEY, nullable=False),
        sa.Column("tax_total", _MONEY, nullable=False),
        # charges the document adds on top of the taxed line items;
        # round_off may be negative. taxable_total + tax_total + shipping_total
        # + other_charges + round_off == grand_total.
        sa.Column("shipping_total", _MONEY, nullable=False),
        sa.Column("other_charges", _MONEY, nullable=False),
        sa.Column("round_off", _MONEY, nullable=False),
        sa.Column("grand_total", _MONEY, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchases_business_id", "purchases", ["business_id"], unique=False)
    op.create_index(
        "ix_purchases_business_id_created_at",
        "purchases",
        ["business_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ux_purchases_business_supplier_invoice",
        "purchases",
        ["business_id", "supplier_id", "invoice_no"],
        unique=True,
        postgresql_where=sa.text("invoice_no IS NOT NULL AND supplier_id IS NOT NULL"),
    )
    # purchase orders carry no invoice number; dedupe them on po_no instead
    op.create_index(
        "ux_purchases_business_supplier_po",
        "purchases",
        ["business_id", "supplier_id", "po_no"],
        unique=True,
        postgresql_where=sa.text(
            "invoice_no IS NULL AND po_no IS NOT NULL AND supplier_id IS NOT NULL"
        ),
    )

    op.create_table(
        "purchase_line_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("purchase_id", sa.UUID(), nullable=False),
        sa.Column("sr_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("raw_description", sa.String(length=500), nullable=False),
        sa.Column("hsn_sac", sa.String(length=10), nullable=True),
        sa.Column("qty", _QTY, nullable=False),
        sa.Column("uom", sa.String(length=20), nullable=True),
        sa.Column("price", _MONEY, nullable=False),
        sa.Column("discount", _MONEY, nullable=False),
        sa.Column("gst_rate", _RATE, nullable=False),
        sa.Column("line_total", _MONEY, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["purchase_id"], ["purchases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_purchase_line_items_purchase_id",
        "purchase_line_items",
        ["purchase_id"],
        unique=False,
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("delta_qty", _QTY, nullable=False),
        sa.Column("balance_after", _QTY, nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("ref_type", sa.String(length=20), nullable=True),
        sa.Column("ref_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stock_movements_business_id", "stock_movements", ["business_id"], unique=False
    )
    op.create_index(
        "ix_stock_movements_product_id", "stock_movements", ["product_id"], unique=False
    )
    op.create_index(
        "ix_stock_movements_business_id_product_id_created_at",
        "stock_movements",
        ["business_id", "product_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("stock_movements")
    op.drop_index(
        "ix_purchase_line_items_purchase_id", table_name="purchase_line_items"
    )
    op.drop_table("purchase_line_items")
    op.drop_index("ux_purchases_business_supplier_po", table_name="purchases")
    op.drop_index("ux_purchases_business_supplier_invoice", table_name="purchases")
    op.drop_index("ix_purchases_business_id_created_at", table_name="purchases")
    op.drop_index("ix_purchases_business_id", table_name="purchases")
    op.drop_table("purchases")
    op.drop_index("ux_products_business_id_name_norm", table_name="products")
    op.drop_index("ix_products_business_id", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_suppliers_business_id_gstin", table_name="suppliers")
    op.drop_index("ux_suppliers_business_id_name_norm", table_name="suppliers")
    op.drop_index("ix_suppliers_business_id", table_name="suppliers")
    op.drop_table("suppliers")
