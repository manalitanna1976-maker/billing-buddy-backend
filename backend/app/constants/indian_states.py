"""The 37 Indian states / union territories with their GST state codes.

Canonical form used across the app: ``"<code>-<Name>"`` (e.g. ``"27-Maharashtra"``).
``normalize_state`` accepts the messy real-world variants a user might have
typed before the dropdown existed — bare name, bare code, ``"27 Maharashtra"``,
``"MAHARASHTRA"`` — and returns the canonical string, or ``None`` if it matches
nothing.
"""

from __future__ import annotations

# (code, name) — code is the GST state code (TIN first two digits).
INDIAN_STATES: list[tuple[str, str]] = [
    ("01", "Jammu and Kashmir"),
    ("02", "Himachal Pradesh"),
    ("03", "Punjab"),
    ("04", "Chandigarh"),
    ("05", "Uttarakhand"),
    ("06", "Haryana"),
    ("07", "Delhi"),
    ("08", "Rajasthan"),
    ("09", "Uttar Pradesh"),
    ("10", "Bihar"),
    ("11", "Sikkim"),
    ("12", "Arunachal Pradesh"),
    ("13", "Nagaland"),
    ("14", "Manipur"),
    ("15", "Mizoram"),
    ("16", "Tripura"),
    ("17", "Meghalaya"),
    ("18", "Assam"),
    ("19", "West Bengal"),
    ("20", "Jharkhand"),
    ("21", "Odisha"),
    ("22", "Chhattisgarh"),
    ("23", "Madhya Pradesh"),
    ("24", "Gujarat"),
    ("26", "Dadra and Nagar Haveli and Daman and Diu"),
    ("27", "Maharashtra"),
    ("29", "Karnataka"),
    ("30", "Goa"),
    ("31", "Lakshadweep"),
    ("32", "Kerala"),
    ("33", "Tamil Nadu"),
    ("34", "Puducherry"),
    ("35", "Andaman and Nicobar Islands"),
    ("36", "Telangana"),
    ("37", "Andhra Pradesh"),
    ("38", "Ladakh"),
    ("97", "Other Territory"),
]

CANONICAL: list[str] = [f"{code}-{name}" for code, name in INDIAN_STATES]

_BY_CODE = {code: name for code, name in INDIAN_STATES}
_BY_NAME = {name.casefold(): code for code, name in INDIAN_STATES}


def _strip_leading_code(value: str) -> str:
    """``"27-Maharashtra"`` / ``"27 Maharashtra"`` / ``"27,Maharashtra"`` -> ``"Maharashtra"``."""
    v = value.strip()
    if len(v) >= 3 and v[:2].isdigit() and v[2] in "-–— ,:":
        return v[3:].strip()
    return v


def normalize_state(value: str | None) -> str | None:
    """Best-effort map any input to the canonical ``"<code>-<Name>"`` string."""
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None

    # bare 2-digit code
    if raw.isdigit() and raw.zfill(2) in _BY_CODE:
        code = raw.zfill(2)
        return f"{code}-{_BY_CODE[code]}"

    name_part = _strip_leading_code(raw)
    code = _BY_NAME.get(name_part.casefold())
    if code:
        return f"{code}-{_BY_CODE[code]}"

    # already canonical? (code-name with matching name)
    if "-" in raw:
        head, _, tail = raw.partition("-")
        if head.strip() in _BY_CODE and _BY_CODE[head.strip()].casefold() == tail.strip().casefold():
            return f"{head.strip()}-{_BY_CODE[head.strip()]}"

    return None


def same_gst_state(a: str | None, b: str | None) -> bool:
    """True iff both resolve to the same Indian state (so CGST+SGST, not IGST).

    Tolerant of free-text legacy data: ``"Maharashtra"`` and ``"27-Maharashtra"``
    are the same state. Unrecognised values fall back to a casefold compare so a
    typo'd-but-consistent pair still counts as intra-state.
    """
    na, nb = normalize_state(a), normalize_state(b)
    if na is not None and nb is not None:
        return na == nb
    if not a or not b:
        return False
    return a.strip().casefold() == b.strip().casefold()
