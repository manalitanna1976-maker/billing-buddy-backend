from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.services.num2words_inr import amount_in_words as _amount_in_words

TWO_PLACES = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass
class LineItemInput:
    qty: Decimal
    price: Decimal
    discount: Decimal
    gst_rate: Decimal


@dataclass
class InvoiceTotals:
    taxable_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    tax_total: Decimal
    discount_amount: Decimal
    tcs_amount: Decimal
    round_off_amount: Decimal
    grand_total: Decimal
    amount_in_words: str


def line_taxable_value(item: LineItemInput) -> Decimal:
    return _q(item.qty * item.price - item.discount)


def split_gst(taxable: Decimal, gst_rate: Decimal, same_state: bool) -> dict:
    tax = _q(taxable * gst_rate / Decimal("100"))
    if same_state:
        half = _q(tax / 2)
        return {"cgst": half, "sgst": tax - half, "igst": Decimal("0.00")}
    return {"cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": tax}


def compute_invoice_totals(
    items: list[LineItemInput],
    same_state: bool,
    discount_type: str,
    discount_value: Decimal,
    tcs: Decimal,
    round_off: bool,
) -> InvoiceTotals:
    line_taxables = [line_taxable_value(item) for item in items]
    subtotal = _q(sum(line_taxables, Decimal("0")))

    if discount_type == "%":
        discount_amount = _q(subtotal * discount_value / Decimal("100"))
    else:
        discount_amount = _q(discount_value)

    taxable_total = _q(subtotal - discount_amount)

    # Tax computed per line on its pre-discount taxable value (matches the
    # reference form: discount is a header-level adjustment, not per-line).
    cgst_total = sgst_total = igst_total = Decimal("0.00")
    for item, line_taxable in zip(items, line_taxables):
        split = split_gst(line_taxable, item.gst_rate, same_state)
        cgst_total += split["cgst"]
        sgst_total += split["sgst"]
        igst_total += split["igst"]

    tax_total = _q(cgst_total + sgst_total + igst_total)
    tcs_amount = _q(tcs)

    pre_round_total = _q(taxable_total + tax_total + tcs_amount)

    if round_off:
        grand_total = pre_round_total.to_integral_value(rounding=ROUND_HALF_UP)
        round_off_amount = _q(grand_total - pre_round_total)
    else:
        grand_total = pre_round_total
        round_off_amount = Decimal("0.00")

    return InvoiceTotals(
        taxable_total=taxable_total,
        cgst_total=cgst_total,
        sgst_total=sgst_total,
        igst_total=igst_total,
        tax_total=tax_total,
        discount_amount=discount_amount,
        tcs_amount=tcs_amount,
        round_off_amount=round_off_amount,
        grand_total=_q(grand_total),
        amount_in_words=_amount_in_words(_q(grand_total)),
    )
