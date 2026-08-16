// Mirrors backend/app/services/gst.py's compute_invoice_totals so the form
// can show a live running total as the user edits line items. This is a
// display-only preview — the backend recomputes and persists the
// authoritative totals on save, using Decimal arithmetic instead of floats.

export interface LineItemPreviewInput {
  qty: string;
  price: string;
  discount: string;
  gst_rate: string;
}

export interface InvoiceTotalsPreview {
  subtotal: number;
  discountAmount: number;
  taxableTotal: number;
  taxTotal: number;
  tcsAmount: number;
  preRoundTotal: number;
  roundOffAmount: number;
  grandTotal: number;
}

function n(value: string | number | undefined | null): number {
  const parsed = typeof value === "number" ? value : parseFloat(value ?? "0");
  return isFinite(parsed) ? parsed : 0;
}

function round2(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

export function lineTaxableValue(item: LineItemPreviewInput): number {
  return round2(n(item.qty) * n(item.price) - n(item.discount));
}

export function computeInvoiceTotalsPreview(
  items: LineItemPreviewInput[],
  discountType: "Rs" | "%",
  discountValue: string,
  tcs: string,
  roundOff: boolean,
): InvoiceTotalsPreview {
  const lineTaxables = items.map(lineTaxableValue);
  const subtotal = round2(lineTaxables.reduce((sum, v) => sum + v, 0));

  const discountAmount =
    discountType === "%" ? round2((subtotal * n(discountValue)) / 100) : round2(n(discountValue));

  const taxableTotal = round2(subtotal - discountAmount);

  // Backend rounds each line's tax to 2dp (via split_gst's per-line CGST/SGST or
  // IGST quantization) before summing, so the total is a sum of already-rounded
  // paise amounts. Rounding only once at the end (on the raw float sum) drifts
  // from that by up to a paisa per extra line item — round each line first to
  // match backend/app/services/gst.py exactly.
  const taxTotal = round2(
    items.reduce((sum, item, i) => sum + round2((lineTaxables[i] * n(item.gst_rate)) / 100), 0),
  );

  const tcsAmount = round2(n(tcs));
  const preRoundTotal = round2(taxableTotal + taxTotal + tcsAmount);

  let grandTotal = preRoundTotal;
  let roundOffAmount = 0;
  if (roundOff) {
    grandTotal = Math.round(preRoundTotal);
    roundOffAmount = round2(grandTotal - preRoundTotal);
  }

  return {
    subtotal,
    discountAmount,
    taxableTotal,
    taxTotal,
    tcsAmount,
    preRoundTotal,
    roundOffAmount,
    grandTotal: round2(grandTotal),
  };
}
