import os
import sys
from pathlib import Path

os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from main import app
from app.routers import ui as ui_module

client = TestClient(app)


def test_get_profile_returns_profile(monkeypatch):
    monkeypatch.setattr(ui_module, "get_latest_profile", lambda user_id="demo": {"age": 42})
    resp = client.get("/ui/profile")
    assert resp.status_code == 200
    assert resp.json()["profile"] == {"age": 42}


def test_post_profile_saves_to_store(monkeypatch):
    saved = {}

    class DummyDoc:
        def set(self, data):
            saved.update(data)

    class DummyCollection:
        def document(self, name):
            assert name == "latest"
            return DummyDoc()

    class DummyUser:
        def collection(self, name):
            assert name == "profile"
            return DummyCollection()

    monkeypatch.setattr(ui_module, "user_doc", lambda user_id="demo": DummyUser())
    monkeypatch.setattr(ui_module, "bq_upsert_profile", lambda user_id="demo": {"ok": True})

    resp = client.post("/ui/profile", json={"age": 30})
    assert resp.status_code == 200
    assert saved["age"] == 30
