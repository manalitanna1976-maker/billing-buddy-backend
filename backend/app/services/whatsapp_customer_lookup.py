"""Deterministic, read-only customer resolution for the WhatsApp worker.

This is injection defense layer #2. The Claude parser (B1) only ever extracts
a free-text ``customer_name`` string from the owner's message; it never picks a
database row. THIS module — plain Python, no model in the loop — decides which
``customers`` row that string maps to, and does so strictly within the caller's
own business (cross-tenant isolation is not optional).

Contract::

    resolve(db, business, name) -> Matched | Ambiguous | NotFound

* Read-only: never ``db.add`` / ``db.commit`` / mutate anything.
* Queries ``Customer`` WHERE ``business_id == business.id`` only.
* Matching is case- and whitespace-insensitive, mirroring the
  ``.strip().casefold()`` style of ``invoices.apply_totals_and_items``.

Algorithm:

1. Normalise the query: ``q = (name or "").strip()``. Empty -> ``NotFound``.
2. **Exact** (case/whitespace-insensitive) match, run as a SQL filter
   (``func.lower(func.trim(name)) == q.lower()``) so it is never hidden behind
   the fuzzy-pass fetch cap. Exactly 1 -> ``Matched``; more than 1 ->
   ``Ambiguous`` (first 5).
3. Otherwise **substring/token** match: rows where the normalised query is a
   substring of the normalised customer name, or vice versa.
   1 -> ``Matched``; 2+ -> ``Ambiguous`` (first 5); 0 -> ``NotFound``.
   (More than 5 still returns ``Ambiguous`` with the first 5, so the owner is
   asked to be specific rather than incorrectly told "not found".)

A ``.limit(FETCH_CAP)`` guard bounds the *fuzzy* fetch only; the exact pass is a
SQL filter with its own tiny limit, so an exact-name hit always resolves
regardless of book size. The cap only ever costs recall on a broad fuzzy query
against a book larger than ``FETCH_CAP``.
"""

from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Business, Customer

# Cap on candidates surfaced to the owner for disambiguation.
MAX_CANDIDATES = 5
# Guard on the initial per-business fetch (see module docstring).
FETCH_CAP = 200


@dataclass
class Matched:
    customer: Customer


@dataclass
class Ambiguous:
    candidates: list[Customer]  # 2..MAX_CANDIDATES


@dataclass(frozen=True)
class NotFound:
    # frozen -> value-equal AND hashable (a bare @dataclass sets __hash__ = None).
    pass


def resolve(db: Session, business: Business, name: str) -> "Matched | Ambiguous | NotFound":
    q = (name or "").strip()
    if not q:
        return NotFound()
    qn = q.casefold()

    # Exact pass: run as a SQL filter so a real exact match can never be hidden
    # behind the fuzzy-pass fetch cap (a mid-size book can exceed FETCH_CAP).
    # casefold() has no SQL equivalent; func.lower()/func.trim() is the correct
    # case/whitespace-insensitive comparison for customer names in practice.
    exact = (
        db.query(Customer)
        .filter(Customer.business_id == business.id)
        .filter(func.lower(func.trim(Customer.name)) == q.lower())
        .order_by(Customer.name, Customer.id)
        .limit(MAX_CANDIDATES + 1)
        .all()
    )
    if exact:
        return _resolve_bucket(exact)

    # Fuzzy pass: bounded fetch + Python substring walk.
    rows = (
        db.query(Customer)
        .filter(Customer.business_id == business.id)
        .order_by(Customer.name, Customer.id)
        .limit(FETCH_CAP)
        .all()
    )
    # The `cn in qn` direction needs a minimum length: a customer named "S" /
    # "Co" / "AB" is a substring of almost any query and would auto-select if it
    # were the only such match (M1). `qn in cn` (query is a substring of the
    # name) has no such failure mode.
    fuzzy = [
        c
        for c in rows
        if (cn := (c.name or "").strip().casefold())
        and (qn in cn or (len(cn) >= 3 and cn in qn))
    ]
    if fuzzy:
        return _resolve_bucket(fuzzy)

    return NotFound()


def _resolve_bucket(matches: list[Customer]) -> "Matched | Ambiguous":
    if len(matches) == 1:
        return Matched(customer=matches[0])
    return Ambiguous(candidates=matches[:MAX_CANDIDATES])
