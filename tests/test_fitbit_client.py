import sys
from pathlib import Path

import asyncio
import asyncio
import sys
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.external import fitbit_client
from app.config import settings
from app.routers import fitbit as fitbit_router
from main import app


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class DummyClient:
    def __init__(self, *args, **kwargs):
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, data=None):
        self.requests.append({
            "url": url,
            "headers": headers,
            "data": data,
        })
        return DummyResponse({"access_token": "token", "refresh_token": "refresh"})


def test_fitbit_exchange_code_uses_client_id(monkeypatch):
    dummy_client = DummyClient()

    def dummy_async_client(*args, **kwargs):
        return dummy_client

    monkeypatch.setattr(httpx, "AsyncClient", dummy_async_client)
    monkeypatch.setattr(settings, "FITBIT_CLIENT_ID", "client-123")
    monkeypatch.setattr(settings, "FITBIT_CLIENT_SECRET", "secret-456")

    token = asyncio.run(fitbit_client.fitbit_exchange_code("auth-code"))

    assert token["access_token"] == "token"
    assert dummy_client.requests
    sent_data = dummy_client.requests[0]["data"]
    assert sent_data["client_id"] == "client-123"
    assert "clientId" not in sent_data


class DummyTokenDoc:
    def __init__(self):
        self.saved = None

    def set(self, data, merge=False):  # signature compatibility
        self.saved = {"merge": merge, "data": data}


def test_fitbit_auth_callback_persists_tokens(monkeypatch):
    dummy_doc = DummyTokenDoc()
    stored_messages = []

    async def fake_exchange(code: str):
        assert code == "valid-code"
        return {
            "access_token": "token",
            "refresh_token": "refresh",
            "token_type": "Bearer",
            "scope": "activity heartrate",
            "user_id": "user-1",
            "expires_in": 3600,
        }

    monkeypatch.setattr(fitbit_router, "fitbit_exchange_code", fake_exchange)
    monkeypatch.setattr(fitbit_router, "fitbit_token_doc", lambda user_id="demo": dummy_doc)
    monkeypatch.setattr(fitbit_router, "push_line", stored_messages.append)

    client = TestClient(app)
    response = client.get("/fitbit/auth", params={"code": "valid-code"}, follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/#integration"

    assert dummy_doc.saved is not None
    saved_data = dummy_doc.saved["data"]
    assert saved_data["access_token"] == "token"
    assert saved_data["refresh_token"] == "refresh"
    assert saved_data["token_type"] == "Bearer"
    assert saved_data["scope"] == "activity heartrate"
    assert saved_data["user_id"] == "user-1"
    assert stored_messages == ["✅ Fitbit連携が完了しました"]
