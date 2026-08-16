from decimal import Decimal

from app.services.num2words_inr import amount_in_words


def test_zero():
    assert amount_in_words(Decimal("0")) == "Zero Rupees Only"


def test_whole_rupees():
    assert amount_in_words(Decimal("100")) == "One Hundred Rupees Only"


def test_rupees_and_paise():
    assert amount_in_words(Decimal("1234.50")) == (
        "One Thousand Two Hundred Thirty Four Rupees And Fifty Paise Only"
    )


def test_lakhs():
    assert amount_in_words(Decimal("150000")) == "One Lakh Fifty Thousand Rupees Only"
