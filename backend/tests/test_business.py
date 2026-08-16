def _signup_and_headers(client, email="owner@biz.test"):
    resp = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_get_business_profile(client):
    headers = _signup_and_headers(client)
    resp = client.get("/business", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Dattani Steel"


def test_update_business_profile(client):
    headers = _signup_and_headers(client)
    resp = client.put(
        "/business",
        headers=headers,
        json={"gstin": "24AAAAA0000A1Z5", "state": "Gujarat"},
    )
    assert resp.status_code == 200
    assert resp.json()["gstin"] == "24AAAAA0000A1Z5"
    assert resp.json()["state"] == "Gujarat"


def test_business_requires_auth(client):
    resp = client.get("/business")
    assert resp.status_code == 401
