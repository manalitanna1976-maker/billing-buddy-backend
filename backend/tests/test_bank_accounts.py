def _headers(client, email="owner@bank.test"):
    resp = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_create_list_update_delete_bank_account(client):
    headers = _headers(client)

    create_resp = client.post(
        "/bank-accounts",
        headers=headers,
        json={"bank_name": "HDFC Bank", "account_no": "1234567890", "ifsc": "HDFC0000123"},
    )
    assert create_resp.status_code == 201
    account_id = create_resp.json()["id"]

    list_resp = client.get("/bank-accounts", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    update_resp = client.put(
        f"/bank-accounts/{account_id}", headers=headers, json={"is_default": True}
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["is_default"] is True

    delete_resp = client.delete(f"/bank-accounts/{account_id}", headers=headers)
    assert delete_resp.status_code == 204
    assert client.get("/bank-accounts", headers=headers).json() == []


def test_bank_account_isolated_per_tenant(client):
    headers_a = _headers(client, "a@bank.test")
    headers_b = _headers(client, "b@bank.test")

    create_resp = client.post(
        "/bank-accounts",
        headers=headers_a,
        json={"bank_name": "HDFC Bank", "account_no": "111", "ifsc": "HDFC0000111"},
    )
    account_id = create_resp.json()["id"]

    resp = client.put(f"/bank-accounts/{account_id}", headers=headers_b, json={"is_default": True})
    assert resp.status_code == 404


def test_only_one_default_bank_account_at_a_time(client):
    headers = _headers(client, "default@bank.test")

    first = client.post(
        "/bank-accounts",
        headers=headers,
        json={
            "bank_name": "HDFC Bank",
            "account_no": "111",
            "ifsc": "HDFC0000111",
            "is_default": True,
        },
    ).json()

    # Creating a second account as default should clear the first one's flag.
    second = client.post(
        "/bank-accounts",
        headers=headers,
        json={
            "bank_name": "ICICI Bank",
            "account_no": "222",
            "ifsc": "ICIC0000222",
            "is_default": True,
        },
    ).json()

    accounts = {a["id"]: a["is_default"] for a in client.get("/bank-accounts", headers=headers).json()}
    assert accounts[first["id"]] is False
    assert accounts[second["id"]] is True

    # Explicitly re-marking the first account as default should clear the second.
    client.put(f"/bank-accounts/{first['id']}", headers=headers, json={"is_default": True})
    accounts = {a["id"]: a["is_default"] for a in client.get("/bank-accounts", headers=headers).json()}
    assert accounts[first["id"]] is True
    assert accounts[second["id"]] is False
