import os
import sys
from pathlib import Path

os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")
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

