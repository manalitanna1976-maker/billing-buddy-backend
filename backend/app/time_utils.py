"""Single source of "now" for the app.

``datetime.utcnow()`` is deprecated in 3.12+. We still store *naive* UTC
datetimes (every ``DateTime`` column in the app is naive, and comparisons
throughout assume naive), so this returns an aware ``datetime.now(UTC)`` with
the tzinfo stripped -- deprecation-free, behaviour identical.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
