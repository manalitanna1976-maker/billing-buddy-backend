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
