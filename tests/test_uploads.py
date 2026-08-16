import io


def _signup_and_headers(client, email="owner@upload.test"):
    resp = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


PNG_MAGIC_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16  # minimal valid PNG signature + padding


def test_upload_logo(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    headers = _signup_and_headers(client)

    file_bytes = io.BytesIO(PNG_MAGIC_BYTES)
    resp = client.post(
        "/business/logo",
        headers=headers,
        files={"file": ("logo.png", file_bytes, "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["logo_url"].endswith("/logo.png")


def test_upload_rejects_bad_extension(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    headers = _signup_and_headers(client)

    file_bytes = io.BytesIO(PNG_MAGIC_BYTES)
    resp = client.post(
        "/business/logo",
        headers=headers,
        files={"file": ("virus.exe", file_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 422


def test_upload_rejects_content_not_matching_extension(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    headers = _signup_and_headers(client)

    file_bytes = io.BytesIO(b"this is not an image, just relabeled as one")
    resp = client.post(
        "/business/logo",
        headers=headers,
        files={"file": ("logo.png", file_bytes, "image/png")},
    )
    assert resp.status_code == 422
