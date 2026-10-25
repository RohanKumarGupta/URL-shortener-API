from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app as shortlink_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(shortlink_app, "DATABASE_PATH", tmp_path / "test-links.db")
    shortlink_app.initialize_db()
    return TestClient(shortlink_app.app)


def test_create_link_returns_short_code(client):
    response = client.post("/links", json={"url": "https://example.com/a"})

    assert response.status_code == 201
    assert response.json()["code"]
    assert response.json()["original_url"] == "https://example.com/a"


def test_custom_alias_redirects_and_tracks_clicks(client):
    created = client.post(
        "/links", json={"url": "https://example.com/path", "alias": "my-link"}
    )
    assert created.status_code == 201

    redirect = client.get("/my-link", follow_redirects=False)
    assert redirect.status_code == 302
    assert redirect.headers["location"] == "https://example.com/path"

    stats = client.get("/links/my-link/stats")
    assert stats.status_code == 200
    assert stats.json()["total_clicks"] == 1
    assert stats.json()["last_clicked_at"] is not None


def test_duplicate_alias_returns_helpful_conflict(client):
    body = {"url": "https://example.com", "alias": "custom"}
    assert client.post("/links", json=body).status_code == 201

    response = client.post("/links", json=body)
    assert response.status_code == 409
    assert "already in use" in response.json()["detail"]


@pytest.mark.parametrize("url", ["ftp://example.com", "not a URL", "https:///missing-host"])
def test_invalid_url_is_rejected(client, url):
    response = client.post("/links", json={"url": url})

    assert response.status_code == 422


def test_unknown_code_returns_404(client):
    response = client.get("/not-found")

    assert response.status_code == 404
    assert response.json()["detail"] == "Short link not found."


def test_expired_link_returns_410(client):
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    created = client.post(
        "/links",
        json={"url": "https://example.com", "alias": "old-link", "expires_at": expired},
    )
    assert created.status_code == 422

    # Insert an already-expired row directly to exercise redirect expiry handling.
    with shortlink_app.connect_db() as connection:
        connection.execute(
            """
            INSERT INTO links (code, original_url, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "old-link",
                "https://example.com",
                datetime.now(timezone.utc).isoformat(),
                expired,
            ),
        )

    response = client.get("/old-link")
    assert response.status_code == 410
    assert "expired" in response.json()["detail"]


def test_future_expiry_is_accepted(client):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    response = client.post(
        "/links", json={"url": "https://example.com", "expires_at": future}
    )

    assert response.status_code == 201
    assert response.json()["expires_at"] is not None
