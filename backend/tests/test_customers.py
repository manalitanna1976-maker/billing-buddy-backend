def _headers(client, email="owner@cust.test"):
    resp = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_create_and_search_customers(client):
    headers = _headers(client)

    client.post(
        "/customers",
        headers=headers,
        json={"name": "Acme Traders", "place_of_supply": "Maharashtra"},
    )
    client.post(
        "/customers", headers=headers, json={"name": "Beta Corp", "place_of_supply": "Gujarat"}
    )

    resp = client.get("/customers", headers=headers, params={"q": "acme"})
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert names == ["Acme Traders"]


def test_update_customer(client):
    headers = _headers(client)
    create_resp = client.post("/customers", headers=headers, json={"name": "Acme Traders"})
    customer_id = create_resp.json()["id"]

    update_resp = client.put(
        f"/customers/{customer_id}", headers=headers, json={"gstin_pan": "27AAAAA0000A1Z5"}
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["gstin_pan"] == "27AAAAA0000A1Z5"
