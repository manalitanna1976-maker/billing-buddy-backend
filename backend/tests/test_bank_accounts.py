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
