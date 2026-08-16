from decimal import Decimal

_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
]
_TENS = [
    "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety",
]


def _two_digits(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return f"{_TENS[tens]} {_ONES[ones]}".strip()


def _three_digits(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_two_digits(rest))
    return " ".join(parts)


def _int_to_words(n: int) -> str:
    if n == 0:
        return ""
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1_000)
    hundred = n

    parts = []
    if crore:
        parts.append(f"{_int_to_words(crore)} Crore")
    if lakh:
        parts.append(f"{_two_digits(lakh) if lakh < 100 else _three_digits(lakh)} Lakh")
    if thousand:
        parts.append(f"{_two_digits(thousand) if thousand < 100 else _three_digits(thousand)} Thousand")
    if hundred:
        parts.append(_three_digits(hundred))
    return " ".join(p for p in parts if p)


def amount_in_words(amount: Decimal) -> str:
    amount = amount.quantize(Decimal("0.01"))
    rupees = int(amount)
    paise = int((amount - rupees) * 100)

    if rupees == 0 and paise == 0:
        return "Zero Rupees Only"

    words = f"{_int_to_words(rupees)} Rupees".strip() if rupees else ""
    if paise:
        paise_words = f"And {_two_digits(paise)} Paise"
        words = f"{words} {paise_words}".strip() if words else f"{paise_words.removeprefix('And ')}"
    return f"{words} Only".strip()
