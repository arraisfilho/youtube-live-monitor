from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import backend.app as webapp
from backend.store import Store, cipher_from_secret

SECRET = b"segredo-de-teste-com-mais-de-32-caracteres"
HEADERS = {"X-YLM-Request": "1"}
VID = "AbCdEfGhI12"


@pytest.fixture()
def env(tmp_path: Path) -> dict[str, Any]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    app = webapp.create_app(data_dir=str(tmp_path), secret=SECRET, vm_url="http://vm:8428", static_dir=str(dist),
                            start_collector=False)
    store = Store(str(tmp_path / "state.db"), cipher_from_secret(SECRET))
    return {"client": TestClient(app), "store": store, "db": tmp_path / "state.db"}


def login(client: TestClient, password: str) -> Any:
    return client.post("/api/login", json={"password": password}, headers=HEADERS)


def ready(env: dict[str, Any]) -> TestClient:
    """Account created, first sign-in done and final password set."""
    client = env["client"]
    temporary = env["store"].reset_password()
    assert login(client, temporary).json() == {"must_change_password": True}
    response = client.post("/api/password", json={"current": temporary, "new": "senha-definitiva-123"}, headers=HEADERS)
    assert response.status_code == 200
    return client


def test_first_access_requires_password_change(env: dict[str, Any]) -> None:
    client = env["client"]
    temporary = env["store"].reset_password()
    response = login(client, temporary)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/lives").status_code == 403
    assert client.get("/api/session").json()["must_change_password"] is True
    weak = client.post("/api/password", json={"current": temporary, "new": "curta"}, headers=HEADERS)
    assert weak.status_code == 400
    wrong = client.post("/api/password", json={"current": "errada", "new": "senha-definitiva-123"}, headers=HEADERS)
    assert wrong.status_code == 400
    ok = client.post("/api/password", json={"current": temporary, "new": "senha-definitiva-123"}, headers=HEADERS)
    assert ok.status_code == 200
    assert client.get("/api/lives").status_code == 200
    assert login(client, temporary).status_code == 401


def test_requests_without_session_or_csrf_header_are_refused(env: dict[str, Any]) -> None:
    client = env["client"]
    assert client.get("/api/lives").status_code == 401
    env["store"].reset_password()
    assert client.post("/api/login", json={"password": "x"}).status_code == 403


def test_login_is_throttled_after_repeated_failures(env: dict[str, Any]) -> None:
    client = env["client"]
    env["store"].reset_password()
    codes = [login(client, "errada").status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429


def test_lives_crud_and_public_link(env: dict[str, Any]) -> None:
    client = ready(env)
    created = client.post("/api/lives", json={"url": f"https://youtu.be/{VID}?si=x"}, headers=HEADERS)
    assert created.status_code == 201 and created.json()["video_id"] == VID
    assert client.post("/api/lives", json={"url": VID}, headers=HEADERS).status_code == 400
    assert client.post("/api/lives", json={"url": "https://example.com/abc"}, headers=HEADERS).status_code == 400
    assert [live["video_id"] for live in client.get("/api/lives").json()] == [VID]

    shared = client.patch(f"/api/lives/{VID}", json={"share_enabled": True}, headers=HEADERS).json()
    path = shared["share_path"]
    token = path.removeprefix("/p/")
    public = client.get(f"/api/public/{token}")
    assert public.status_code == 200
    assert "url" not in public.json() and "share_path" not in public.json()

    rotated = client.post(f"/api/lives/{VID}/share-token", headers=HEADERS).json()["share_path"]
    assert rotated != path and client.get(f"/api/public/{token}").status_code == 404
    client.patch(f"/api/lives/{VID}", json={"share_enabled": False}, headers=HEADERS)
    assert client.get(f"/api/public/{rotated.removeprefix('/p/')}").status_code == 404

    assert client.patch(f"/api/lives/{VID}", json={"enabled": False}, headers=HEADERS).json()["enabled"] is False
    assert client.delete(f"/api/lives/{VID}", headers=HEADERS).status_code == 204
    assert client.get(f"/api/lives/{VID}").status_code == 404


def test_api_key_is_stored_encrypted_and_masked(env: dict[str, Any]) -> None:
    client = ready(env)
    key = "AIzaFakeTestKeyForUnitTests1234567890a"
    settings = client.put("/api/settings/api-key", json={"api_key": key}, headers=HEADERS).json()
    assert settings["api_key"] == {"configured": True, "masked": "AIza…890a"}
    raw = sqlite3.connect(env["db"]).execute("SELECT value FROM settings WHERE key='api_key'").fetchone()[0]
    assert key not in raw
    assert key not in client.get("/api/settings").text
    assert env["store"].api_key() == key
    other = Store(str(env["db"]), cipher_from_secret(b"outro-segredo-com-mais-de-32-caracteres!"))
    assert other.api_key() == ""
    cleared = client.delete("/api/settings/api-key", headers=HEADERS).json()
    assert cleared["api_key"] == {"configured": False, "masked": None}


def test_settings_validation(env: dict[str, Any]) -> None:
    client = ready(env)
    updated = client.put("/api/settings", json={"daily_quota": 20000, "live_interval": 30,
                                                "display_timezone": "Etc/GMT+4"}, headers=HEADERS).json()
    assert (updated["daily_quota"], updated["live_interval"], updated["display_timezone"]) == (20000, 30, "Etc/GMT+4")
    assert client.put("/api/settings", json={"live_interval": 2}, headers=HEADERS).status_code == 400
    assert client.put("/api/settings", json={"display_timezone": "Marte/Base"}, headers=HEADERS).status_code == 400
    config = webapp.runtime_config(webapp.load_config(None), env["store"])
    assert config["collector"]["interval"] == 30 and config["youtube"]["daily_quota"] == 20000


def test_series_use_fixed_queries(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    client = ready(env)
    client.post("/api/lives", json={"url": VID}, headers=HEADERS)
    queries: list[str] = []

    class Response:
        def raise_for_status(self) -> None:
            pass

        @staticmethod
        def json() -> dict[str, Any]:
            return {"data": {"result": [{"values": [[1000, "10"], [1015, "NaN"], [1030, "12"]]}]}}

    def fake_get(url: str, params: dict[str, Any], timeout: float) -> Response:
        assert url == "http://vm:8428/api/v1/query_range"
        queries.append(params["query"])
        return Response()

    monkeypatch.setattr(webapp.requests, "get", fake_get)
    data = client.get(f"/api/lives/{VID}/series?range=604800").json()
    assert data["step"] == 15 and data["range"] == 604800 and data["aggregated"] is False
    custom = client.get(f"/api/lives/{VID}/series?start=1000&end=4600").json()
    assert (custom["start"], custom["end"], custom["step"]) == (1000.0, 4600.0, 15)
    month = client.get(f"/api/lives/{VID}/series?range=2592000").json()
    assert month["aggregated"] is True and month["step"] == 60
    assert client.get(f"/api/lives/{VID}/series?start=1000&end=1030").status_code == 400
    assert client.get("/api/health/series?range=3600").json()["step"] == 15
    assert data["series"]["viewers"] == [[1000.0, 10.0], [1030.0, 12.0]]
    assert f'youtube_live_concurrent_viewers{{video_id="{VID}"}}' in queries
    assert client.get("/api/lives/naoexiste12/series").status_code == 404
    assert "api_calls" in client.get("/api/health/series").json()["series"]


def test_health_reports_quota_and_lives(env: dict[str, Any]) -> None:
    client = ready(env)
    client.post("/api/lives", json={"url": VID}, headers=HEADERS)
    health = client.get("/api/health").json()
    assert health["quota"] == {"used": 0, "limit": 10000, "paused": False, "paused_until": None}
    assert health["lives"]["enabled"] == 1 and health["api_key_configured"] is False


def test_spa_fallback_headers_and_traversal(env: dict[str, Any]) -> None:
    client = env["client"]
    page = client.get("/lives/AbCdEfGhI12")
    assert page.status_code == 200 and "<title>app</title>" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert client.get("/p/qualquer").status_code == 200
    asset = client.get("/assets/app.js")
    assert "immutable" in asset.headers["cache-control"]
    assert client.get("/api/nao-existe").status_code == 404
    assert "<title>app</title>" in client.get("/../../etc/passwd").text
