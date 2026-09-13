def _headers(client, email="owner@supp.test"):
    resp = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_create_and_search_suppliers(client):
    headers = _headers(client)
    client.post("/suppliers", headers=headers, json={"name": "Acme Steel Co"})
    client.post("/suppliers", headers=headers, json={"name": "Beta Traders"})

    resp = client.get("/suppliers", headers=headers, params={"q": "acme"})
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()]
    assert names == ["Acme Steel Co"]


def test_create_supplier_duplicate_name_conflicts(client):
    headers = _headers(client)
    client.post("/suppliers", headers=headers, json={"name": "Acme Pvt Ltd"})
    resp = client.post("/suppliers", headers=headers, json={"name": "Acme Private Limited"})
    assert resp.status_code == 409


def test_update_supplier(client):
    headers = _headers(client)
    create_resp = client.post("/suppliers", headers=headers, json={"name": "Acme Traders"})
    supplier_id = create_resp.json()["id"]

    update_resp = client.put(
        f"/suppliers/{supplier_id}", headers=headers, json={"gstin": "27aaaaa0000a1z5"}
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["gstin"] == "27AAAAA0000A1Z5"


def test_suppliers_scoped_to_business(client):
    headers_a = _headers(client, "a@supp.test")
    headers_b = _headers(client, "b@supp.test")
    create_resp = client.post("/suppliers", headers=headers_a, json={"name": "Acme Traders"})
    supplier_id = create_resp.json()["id"]

    resp = client.get(f"/suppliers/{supplier_id}", headers=headers_b)
    assert resp.status_code == 404
