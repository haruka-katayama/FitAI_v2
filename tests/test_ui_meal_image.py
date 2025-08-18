import os
import sys
from pathlib import Path

os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")
os.environ.setdefault("OPENAI_API_KEY", "test")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from main import app


client = TestClient(app)


def test_meal_image_empty_file_returns_400():
    response = client.post(
        "/ui/meal_image?dry=true",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "Empty file"


def test_meal_image_preview_empty_file_returns_400():
    response = client.post(
        "/ui/meal_image/preview",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "Empty file"


def test_meal_image_includes_memo(monkeypatch):
    """メモ付きでアップロードした場合、メモがGPTプロンプトと保存データに渡る"""
    called = {}

    async def fake_vision(data, mime, memo=None):
        called["memo"] = memo
        return "ok"

    def fake_save(payload, user_id):
        called["notes"] = payload.get("notes")
        return {"ok": True, "dedup_key": "x", "firestore": {"skipped": False}}

    monkeypatch.setattr(
        "app.routers.ui.vision_extract_meal_bytes", fake_vision
    )
    monkeypatch.setattr(
        "app.routers.ui.save_meal_to_stores", fake_save
    )

    import app.routers.ui as ui
    monkeypatch.setattr(ui.settings, "OPENAI_API_KEY", "test", raising=False)

    resp = client.post(
        "/ui/meal_image",
        data={"when": "2024-01-01T12:00:00", "memo": "ご飯大盛り"},
        files={"file": ("img.png", b"123", "image/png")},
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert called["memo"] == "ご飯大盛り"
    assert called["notes"] == "ご飯大盛り"

