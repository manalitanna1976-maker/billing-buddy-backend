// Client-side INR amount-in-words for on-screen display in the invoice
// totals panel (design: "Grand Total ... Total in words" below it). The
// backend independently computes its own amount-in-words for the PDF
// (app/services/gst.py) — this is a display-only convenience so the number
// updates live as the user edits the form, not the source of truth for the
// PDF text.

const ONES = [
  "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
  "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
  "Seventeen", "Eighteen", "Nineteen",
];
const TENS = [
  "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety",
];

function twoDigits(n: number): string {
  if (n < 20) return ONES[n];
  const tens = Math.floor(n / 10);
  const ones = n % 10;
  return TENS[tens] + (ones ? " " + ONES[ones] : "");
}

function threeDigits(n: number): string {
  const hundreds = Math.floor(n / 100);
  const rest = n % 100;
  const parts: string[] = [];
  if (hundreds) parts.push(ONES[hundreds] + " Hundred");
  if (rest) parts.push(twoDigits(rest));
  return parts.join(" ");
}

/** Converts an integer (Indian numbering: crore/lakh/thousand) to words. */
function integerToWords(value: number): string {
  if (value === 0) return "Zero";
  const crore = Math.floor(value / 1_00_00_000);
  value %= 1_00_00_000;
  const lakh = Math.floor(value / 1_00_000);
  value %= 1_00_000;
  const thousand = Math.floor(value / 1_000);
  value %= 1_000;
  const hundred = value;

  const parts: string[] = [];
  if (crore) parts.push(threeDigits(crore) + " Crore");
  if (lakh) parts.push(threeDigits(lakh) + " Lakh");
  if (thousand) parts.push(threeDigits(thousand) + " Thousand");
  if (hundred) parts.push(threeDigits(hundred));
  return parts.join(" ");
}

/** Formats a rupee amount (string or number) as "X Rupees Y Paise Only". */
export function amountInWords(amount: string | number): string {
  const num = typeof amount === "string" ? parseFloat(amount) : amount;
  if (!isFinite(num) || num < 0) return "";

  const rupees = Math.floor(num);
  const paise = Math.round((num - rupees) * 100);

  let words = integerToWords(rupees) + " Rupees";
  if (paise > 0) {
    words += " " + integerToWords(paise) + " Paise";
  }
  return words + " Only";
}
