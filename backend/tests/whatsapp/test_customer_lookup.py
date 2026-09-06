"""Task B3: deterministic, read-only customer resolution.

Injection defense layer #2 — the Claude parser (B1) only ever produces a
free-text `customer_name`; THIS code decides which `customers` row (if any)
it maps to, scoped strictly to the caller's business.
"""

import pytest

from app.models import Business, Customer
from app.services import whatsapp_customer_lookup as lookup
from app.services.whatsapp_customer_lookup import Ambiguous, Matched, NotFound


def _biz(db, name="Acme Corp"):
    b = Business(name=name)
    db.add(b)
    db.flush()
    return b


def _cust(db, business, name):
    c = Customer(business_id=business.id, name=name)
    db.add(c)
    db.flush()
    return c


# --- brief's four ----------------------------------------------------------

def test_exact_one_match_case_insensitive(db_session):
    b = _biz(db_session)
    c = _cust(db_session, b, "ABC Corp")
    result = lookup.resolve(db_session, b, "abc corp")
    assert isinstance(result, Matched)
    assert result.customer.id == c.id


def test_two_same_named_customers_are_ambiguous(db_session):
    b = _biz(db_session)
    c1 = _cust(db_session, b, "ABC")
    c2 = _cust(db_session, b, "abc")
    result = lookup.resolve(db_session, b, "ABC")
    assert isinstance(result, Ambiguous)
    assert {c.id for c in result.candidates} == {c1.id, c2.id}


def test_no_match_is_not_found(db_session):
    b = _biz(db_session)
    _cust(db_session, b, "ABC Corp")
    assert isinstance(lookup.resolve(db_session, b, "Nonexistent Ltd"), NotFound)


def test_other_business_customer_is_never_matched(db_session):
    a = _biz(db_session, "Business A")
    other = _biz(db_session, "Business B")
    _cust(db_session, other, "Shared Name Pvt Ltd")
    result = lookup.resolve(db_session, a, "Shared Name Pvt Ltd")
    assert isinstance(result, NotFound)


# --- additional coverage from the task instructions ----------------------

def test_whitespace_and_case_variance(db_session):
    b = _biz(db_session)
    c = _cust(db_session, b, "ABC Corp")
    result = lookup.resolve(db_session, b, "  abc corp ")
    assert isinstance(result, Matched)
    assert result.customer.id == c.id


@pytest.mark.parametrize("name", ["", "   ", "\t\n", None])
def test_empty_or_whitespace_name_is_not_found(db_session, name):
    b = _biz(db_session)
    _cust(db_session, b, "ABC Corp")
    assert isinstance(lookup.resolve(db_session, b, name), NotFound)


def test_substring_single_match(db_session):
    b = _biz(db_session)
    c = _cust(db_session, b, "Acme Industries Pvt Ltd")
    _cust(db_session, b, "Globex Corporation")
    result = lookup.resolve(db_session, b, "acme")
    assert isinstance(result, Matched)
    assert result.customer.id == c.id


def test_query_longer_than_name_still_matches(db_session):
    # customer.name appears as a substring of the query
    b = _biz(db_session)
    c = _cust(db_session, b, "Acme")
    result = lookup.resolve(db_session, b, "Acme Industries Pvt Ltd")
    assert isinstance(result, Matched)
    assert result.customer.id == c.id


def test_token_collision_is_ambiguous(db_session):
    b = _biz(db_session)
    c1 = _cust(db_session, b, "Alpha Traders")
    c2 = _cust(db_session, b, "Beta Traders")
    result = lookup.resolve(db_session, b, "traders")
    assert isinstance(result, Ambiguous)
    assert {c.id for c in result.candidates} == {c1.id, c2.id}


def test_more_than_five_matches_capped_at_five(db_session):
    b = _biz(db_session)
    for i in range(8):
        _cust(db_session, b, f"Traders {i}")
    result = lookup.resolve(db_session, b, "traders")
    assert isinstance(result, Ambiguous)
    assert len(result.candidates) == 5


def test_more_than_five_exact_matches_capped_at_five(db_session):
    b = _biz(db_session)
    for _ in range(7):
        _cust(db_session, b, "Dup Corp")
    result = lookup.resolve(db_session, b, "dup corp")
    assert isinstance(result, Ambiguous)
    assert len(result.candidates) == 5


def test_exact_match_wins_over_substring(db_session):
    b = _biz(db_session)
    exact = _cust(db_session, b, "Sun")
    _cust(db_session, b, "Sunrise Traders")
    result = lookup.resolve(db_session, b, "sun")
    assert isinstance(result, Matched)
    assert result.customer.id == exact.id


def test_exact_match_survives_fetch_cap(db_session):
    # A large book (> FETCH_CAP) with the target sorting alphabetically last:
    # the exact pass is a SQL filter, so it must still resolve.
    b = _biz(db_session)
    for i in range(260):
        _cust(db_session, b, f"Cust {i:03d}")
    target = _cust(db_session, b, "ZZZ Target Traders")
    result = lookup.resolve(db_session, b, "ZZZ Target Traders")
    assert isinstance(result, Matched)
    assert result.customer.id == target.id


def test_exact_match_case_insensitive_survives_fetch_cap(db_session):
    b = _biz(db_session)
    for i in range(210):
        _cust(db_session, b, f"Cust {i:03d}")
    target = _cust(db_session, b, "  ZZZ Wholesale  ")
    result = lookup.resolve(db_session, b, "zzz wholesale")
    assert isinstance(result, Matched)
    assert result.customer.id == target.id


def test_other_business_customer_never_matched_on_fuzzy_path(db_session):
    a = _biz(db_session, "Business A")
    other = _biz(db_session, "Business B")
    _cust(db_session, other, "Acme Ltd")
    result = lookup.resolve(db_session, a, "acme")
    assert isinstance(result, NotFound)


def test_short_customer_name_does_not_auto_pick(db_session):
    """M1: the `cn in qn` direction with no minimum length lets a 2-char
    customer name match almost any query. Require len(cn) >= 3 for that
    direction."""
    b = _biz(db_session)
    _cust(db_session, b, "AB")  # 2 chars -- a substring of "Fabricators"
    result = lookup.resolve(db_session, b, "Fabricators supplies order")
    assert isinstance(result, NotFound)


def test_notfound_is_hashable(db_session):
    b = _biz(db_session)
    result = lookup.resolve(db_session, b, "nobody")
    assert {result}  # must not raise TypeError: unhashable type


def test_read_only_no_mutation(db_session):
    b = _biz(db_session)
    _cust(db_session, b, "ABC Corp")
    db_session.commit()
    lookup.resolve(db_session, b, "abc corp")
    assert not db_session.new
    assert not db_session.dirty
    assert not db_session.deleted
