def test_signup_then_login(client):
    signup_resp = client.post(
        "/auth/signup",
        json={
            "business_name": "Dattani Steel",
            "email": "owner@dattanisteel.test",
            "password": "correct horse battery staple",
        },
    )
    assert signup_resp.status_code == 201
    assert "access_token" in signup_resp.json()

    login_resp = client.post(
        "/auth/login",
        json={"email": "owner@dattanisteel.test", "password": "correct horse battery staple"},
    )
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()


def test_login_wrong_password_rejected(client):
    client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": "a@b.test", "password": "right-pass"},
    )
    resp = client.post("/auth/login", json={"email": "a@b.test", "password": "wrong-pass"})
    assert resp.status_code == 401


def test_signup_duplicate_email_rejected(client):
    payload = {"business_name": "Dattani Steel", "email": "dupe@b.test", "password": "pass1234"}
    first = client.post("/auth/signup", json=payload)
    assert first.status_code == 201
    second = client.post("/auth/signup", json=payload)
    assert second.status_code == 409


def test_login_locked_out_after_too_many_failed_attempts(client):
    client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": "hammered@b.test", "password": "right-pass"},
    )

    for _ in range(10):
        resp = client.post(
            "/auth/login", json={"email": "hammered@b.test", "password": "wrong-pass"}
        )
        assert resp.status_code == 401

    # 11th failed attempt for the same email within the window is rate limited
    locked_resp = client.post(
        "/auth/login", json={"email": "hammered@b.test", "password": "wrong-pass"}
    )
    assert locked_resp.status_code == 429
    assert "detail" in locked_resp.json()

    # Even the correct password is rejected while locked out
    still_locked = client.post(
        "/auth/login", json={"email": "hammered@b.test", "password": "right-pass"}
    )
    assert still_locked.status_code == 429


def test_login_succeeds_within_threshold_after_some_failures(client):
    client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": "legit@b.test", "password": "right-pass"},
    )

    for _ in range(5):
        resp = client.post("/auth/login", json={"email": "legit@b.test", "password": "wrong-pass"})
        assert resp.status_code == 401

    ok_resp = client.post(
        "/auth/login", json={"email": "legit@b.test", "password": "right-pass"}
    )
    assert ok_resp.status_code == 200
    assert "access_token" in ok_resp.json()


def test_login_rate_limit_scoped_per_email(client):
    client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": "victim@b.test", "password": "right-pass"},
    )
    client.post(
        "/auth/signup",
        json={"business_name": "Other Co", "email": "bystander@b.test", "password": "right-pass"},
    )

    for _ in range(10):
        resp = client.post("/auth/login", json={"email": "victim@b.test", "password": "wrong-pass"})
        assert resp.status_code == 401

    locked = client.post("/auth/login", json={"email": "victim@b.test", "password": "wrong-pass"})
    assert locked.status_code == 429

    # A different email's lockout must not bleed over
    other_ok = client.post(
        "/auth/login", json={"email": "bystander@b.test", "password": "right-pass"}
    )
    assert other_ok.status_code == 200


def test_login_rate_limit_blocks_ip_spraying_many_emails(client):
    # Spraying wrong passwords across several distinct emails from the same
    # client should trip the per-IP cap even though no single email crosses
    # its own (higher) individual threshold.
    emails = [f"spray{i}@b.test" for i in range(4)]
    for email in emails:
        client.post(
            "/auth/signup",
            json={"business_name": "Dattani Steel", "email": email, "password": "right-pass"},
        )

    last_resp = None
    for i in range(32):
        email = emails[i % len(emails)]
        last_resp = client.post("/auth/login", json={"email": email, "password": "wrong-pass"})

    assert last_resp.status_code == 429
