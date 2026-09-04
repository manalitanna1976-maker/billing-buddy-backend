from app import rate_limit as rl


def test_email_cap_trips_at_10(db_session):
    for _ in range(10):
        rl.record_failed_login(db_session, "a@b.test", "1.1.1.1")
    assert rl.is_login_rate_limited(db_session, "a@b.test", "9.9.9.9") is True


def test_reset_forgives_email(db_session):
    for _ in range(10):
        rl.record_failed_login(db_session, "a@b.test", "1.1.1.1")
    rl.reset_failed_logins(db_session, "a@b.test")
    assert rl.is_login_rate_limited(db_session, "a@b.test", "9.9.9.9") is False


def test_ip_cap_trips_at_30_across_emails(db_session):
    for i in range(30):
        rl.record_failed_login(db_session, f"u{i}@b.test", "5.5.5.5")
    assert rl.is_login_rate_limited(db_session, "fresh@b.test", "5.5.5.5") is True
