"""Shared field validators for request schemas.

Format rules for Indian tax identifiers plus a few small reusable helpers.
Kept in one place so the customer, business, and invoice schemas agree.
"""

from __future__ import annotations

import re
from decimal import Decimal

# GSTIN: 2-digit state code, 10-char PAN, 1 entity digit, 'Z', 1 checksum char.
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
# PAN: 5 letters, 4 digits, 1 letter.
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
# IFSC: 4 letters, '0', 6 alphanumerics.
IFSC_RE = re.compile(r"^[A-Z]{4}0[0-9A-Z]{6}$")


def clean_optional_text(value: str | None) -> str | None:
    """Trim; turn an empty/whitespace-only string into ``None``."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def require_non_empty(value: str) -> str:
    """Trim and reject an empty/whitespace-only required string."""
    trimmed = (value or "").strip()
    if not trimmed:
        raise ValueError("must not be blank")
    return trimmed


def validate_gstin(value: str | None) -> str | None:
    value = clean_optional_text(value)
    if value is None:
        return None
    value = value.upper()
    if not GSTIN_RE.match(value):
        raise ValueError("invalid GSTIN format (expected e.g. 27AAPFU0939F1ZV)")
    return value


def validate_pan(value: str | None) -> str | None:
    value = clean_optional_text(value)
    if value is None:
        return None
    value = value.upper()
    if not PAN_RE.match(value):
        raise ValueError("invalid PAN format (expected e.g. AAPFU0939F)")
    return value


def validate_ifsc(value: str | None) -> str | None:
    value = clean_optional_text(value)
    if value is None:
        return None
    value = value.upper()
    if not IFSC_RE.match(value):
        raise ValueError("invalid IFSC format (expected e.g. HDFC0001234)")
    return value


def non_negative(value: Decimal, *, field: str = "value") -> Decimal:
    if value < 0:
        raise ValueError(f"{field} must not be negative")
    return value


def positive(value: Decimal, *, field: str = "value") -> Decimal:
    if value <= 0:
        raise ValueError(f"{field} must be greater than zero")
    return value
