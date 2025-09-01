import os
import sys
from pathlib import Path
import pytest

os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")
os.environ.setdefault("OPENAI_API_KEY", "test")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from main import app


client = TestClient(app)


def _create_large_image_bytes() -> bytes:
    pytest.importorskip("PIL")
    from PIL import Image
    import io

    img = Image.new("RGB", (3000, 3000), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    data = buf.getvalue()
    assert len(data) > 1024 * 1024
    return data


def test_meal_image_empty_file_returns_400():
    response = client.post(
        "/ui/meal_image?dry=true",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "Empty file"


def test_meal_image_large_image_is_compressed():
    big_data = _create_large_image_bytes()
    response = client.post(
        "/ui/meal_image?dry=true",
        files={"file": ("big.jpg", big_data, "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["size"] <= 1024 * 1024


def test_meal_image_preview_empty_file_returns_400():
    response = client.post(
        "/ui/meal_image/preview",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "Empty file"


def test_meal_image_preview_large_image_is_compressed(monkeypatch):
    async def fake_vision(data, mime, memo=None):
        return "ok"

    monkeypatch.setattr(
        "app.routers.ui.vision_extract_meal_bytes", fake_vision
    )
    import app.routers.ui as ui
    monkeypatch.setattr(ui.settings, "OPENAI_API_KEY", "test", raising=False)

    big_data = _create_large_image_bytes()
    response = client.post(
        "/ui/meal_image/preview",
        files={"file": ("big.jpg", big_data, "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["size"] <= 1024 * 1024


def test_meal_image_includes_memo(monkeypatch):
    """メモ付きでアップロードした場合、メモがGPTプロンプトに渡るが保存されない"""
    called = {}

    async def fake_vision(data, mime, memo=None):
        called["memo"] = memo
        return f"これは説明\nユーザーのメモ: {memo}"

    def fake_save(payload, user_id):
        called["notes"] = payload.get("notes")
        called["text"] = payload.get("text")
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
    assert called["notes"] is None
    assert "ご飯大盛り" not in called["text"]


def test_meal_image_saves_base64(monkeypatch):
    """有効な画像をアップロードすると圧縮データが保存される"""
    called = {}

    async def fake_vision(data, mime, memo=None):
        return "ok"

    def fake_save(payload, user_id):
        called["image_base64"] = payload.get("image_base64")
        return {"ok": True, "dedup_key": "x", "firestore": {"skipped": False}}

    monkeypatch.setattr(
        "app.routers.ui.vision_extract_meal_bytes", fake_vision
    )
    monkeypatch.setattr(
        "app.routers.ui.save_meal_to_stores", fake_save
    )

    import app.routers.ui as ui
    monkeypatch.setattr(ui.settings, "OPENAI_API_KEY", "test", raising=False)

    import base64

    img_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQImWNgYGD4DwABBAEAEPyWpQAAAABJRU5ErkJggg=="
    )

    resp = client.post(
        "/ui/meal_image",
        data={"when": "2024-01-01T12:00:00"},
        files={"file": ("img.png", img_bytes, "image/png")},
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert called["image_base64"]

