from decimal import Decimal

from app.models import Business, Product, StockMovement
from app.services.inventory import apply_stock_movement, normalize_name


def test_normalize_name_lowercases_and_collapses_whitespace():
    assert normalize_name("  Acme   Traders  ") == "acme traders"


def test_normalize_name_strips_punctuation_to_space():
    assert normalize_name("Acme, Traders (Retail).") == "acme traders retail"


def test_normalize_name_strips_pvt_ltd_suffix():
    assert normalize_name("Acme Pvt. Ltd.") == "acme"
    assert normalize_name("Acme Private Limited") == "acme"


def test_normalize_name_dedupes_against_plain_name():
    assert normalize_name("Acme Pvt Ltd") == normalize_name("Acme")


def test_normalize_name_and_co_and_ampersand_co_suffix():
    assert normalize_name("Acme and Co") == "acme"
    assert normalize_name("Acme & Co") == "acme"


def test_normalize_name_keeps_ampersand_when_not_co_suffix():
    assert normalize_name("Acme & Sons") == "acme & sons"


def test_normalize_name_does_not_empty_out_bare_suffix():
    assert normalize_name("Ltd") == "ltd"


def test_normalize_name_strips_leading_trailing_symbol_tokens():
    assert normalize_name("-- Acme --") == "acme"


def test_normalize_name_empty_and_none():
    assert normalize_name("") == ""
    assert normalize_name(None) == ""


def _business(db_session) -> Business:
    business = Business(name="Test Co")
    db_session.add(business)
    db_session.flush()
    return business


def _product(db_session, business, **overrides) -> Product:
    product = Product(
        business_id=business.id,
        name=overrides.get("name", "Widget"),
        name_norm=overrides.get("name_norm", "widget"),
        current_qty=overrides.get("current_qty", Decimal("0")),
    )
    db_session.add(product)
    db_session.flush()
    return product


def test_apply_stock_movement_increases_qty_and_records_movement(db_session):
    business = _business(db_session)
    product = _product(db_session, business, current_qty=Decimal("10"))

    movement = apply_stock_movement(
        db_session, product, delta_qty=Decimal("5"), reason="manual_adjustment"
    )

    assert product.current_qty == Decimal("15")
    assert movement.delta_qty == Decimal("5")
    assert movement.balance_after == Decimal("15")
    assert movement.reason == "manual_adjustment"
    assert movement.business_id == business.id
    assert movement.product_id == product.id

    stored = db_session.query(StockMovement).filter_by(product_id=product.id).one()
    assert stored.balance_after == Decimal("15")


def test_apply_stock_movement_decreases_qty(db_session):
    business = _business(db_session)
    product = _product(db_session, business, current_qty=Decimal("10"))

    apply_stock_movement(db_session, product, delta_qty=Decimal("-3"), reason="purchase_reversal")

    assert product.current_qty == Decimal("7")


def test_apply_stock_movement_sequential_calls_accumulate(db_session):
    business = _business(db_session)
    product = _product(db_session, business, current_qty=Decimal("0"))

    apply_stock_movement(db_session, product, delta_qty=Decimal("4"), reason="purchase")
    apply_stock_movement(db_session, product, delta_qty=Decimal("-1"), reason="manual_adjustment")

    assert product.current_qty == Decimal("3")
    movements = (
        db_session.query(StockMovement)
        .filter_by(product_id=product.id)
        .order_by(StockMovement.created_at)
        .all()
    )
    assert [m.balance_after for m in movements] == [Decimal("4"), Decimal("3")]


def test_apply_stock_movement_stores_ref_and_note(db_session):
    business = _business(db_session)
    product = _product(db_session, business)
    ref_id = product.id  # any uuid works as a stand-in ref target for this test

    movement = apply_stock_movement(
        db_session,
        product,
        delta_qty=Decimal("2"),
        reason="purchase",
        ref_type="purchase",
        ref_id=ref_id,
        note="from PO-1",
    )

    assert movement.ref_type == "purchase"
    assert movement.ref_id == ref_id
    assert movement.note == "from PO-1"
