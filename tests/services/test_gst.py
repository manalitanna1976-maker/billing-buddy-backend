from decimal import Decimal

from app.services.gst import LineItemInput, compute_invoice_totals, line_taxable_value, split_gst


def test_line_taxable_value():
    item = LineItemInput(qty=Decimal("10"), price=Decimal("100"), discount=Decimal("50"), gst_rate=Decimal("18"))
    assert line_taxable_value(item) == Decimal("950")


def test_split_gst_same_state_splits_cgst_sgst():
    result = split_gst(Decimal("1000"), Decimal("18"), same_state=True)
    assert result == {"cgst": Decimal("90.00"), "sgst": Decimal("90.00"), "igst": Decimal("0.00")}


def test_split_gst_different_state_uses_igst():
    result = split_gst(Decimal("1000"), Decimal("18"), same_state=False)
    assert result == {"cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": Decimal("180.00")}


def test_compute_invoice_totals_single_item_same_state():
    items = [LineItemInput(qty=Decimal("2"), price=Decimal("500"), discount=Decimal("0"), gst_rate=Decimal("18"))]
    totals = compute_invoice_totals(
        items, same_state=True, discount_type="Rs", discount_value=Decimal("0"),
        tcs=Decimal("0"), round_off=False,
    )
    assert totals.taxable_total == Decimal("1000.00")
    assert totals.cgst_total == Decimal("90.00")
    assert totals.sgst_total == Decimal("90.00")
    assert totals.igst_total == Decimal("0.00")
    assert totals.tax_total == Decimal("180.00")
    assert totals.grand_total == Decimal("1180.00")
    assert totals.amount_in_words.startswith("One Thousand One Hundred Eighty Rupees")


def test_compute_invoice_totals_applies_percent_discount_and_round_off():
    items = [LineItemInput(qty=Decimal("1"), price=Decimal("999"), discount=Decimal("0"), gst_rate=Decimal("0"))]
    totals = compute_invoice_totals(
        items, same_state=True, discount_type="%", discount_value=Decimal("10"),
        tcs=Decimal("0"), round_off=True,
    )
    # 999 - 10% = 899.10 taxable, no tax, round-off to nearest rupee -> 899
    assert totals.discount_amount == Decimal("99.90")
    assert totals.grand_total == Decimal("899.00")
    assert totals.round_off_amount == Decimal("-0.10")
