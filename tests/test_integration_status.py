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


def test_integration_status_marks_services_linked():
    response = client.get("/integration/status?user_id=demo")
    assert response.status_code == 200
    data = response.json()
    assert data["fitbit"]["linked"] is True
    assert data["healthplanet"]["linked"] is True
