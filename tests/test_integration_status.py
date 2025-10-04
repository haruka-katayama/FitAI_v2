import os
import sys
from pathlib import Path

os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_integration_status_marks_services_linked():
    doc = MagicMock()
    snapshot = MagicMock()
    snapshot.exists = True
    doc.get.return_value = snapshot

    with patch("app.routers.integration.fitbit_token_doc", return_value=doc), \
        patch("app.routers.integration.healthplanet_token_doc", return_value=doc):
        response = client.get("/integration/status?user_id=demo")

    assert response.status_code == 200
    data = response.json()
    assert data["fitbit"]["linked"] is True
    assert data["healthplanet"]["linked"] is True


def test_integration_status_marks_services_unlinked_when_missing():
    doc = MagicMock()
    snapshot = MagicMock()
    snapshot.exists = False
    doc.get.return_value = snapshot

    with patch("app.routers.integration.fitbit_token_doc", return_value=doc), \
        patch("app.routers.integration.healthplanet_token_doc", return_value=doc):
        response = client.get("/integration/status?user_id=demo")

    assert response.status_code == 200
    data = response.json()
    assert data["fitbit"]["linked"] is False
    assert data["healthplanet"]["linked"] is False
