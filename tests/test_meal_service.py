import os
import sys
from pathlib import Path
import asyncio
from datetime import datetime, timezone, date
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import meal_service


def test_meals_last_n_days_returns_meals(monkeypatch):
    sample_row = SimpleNamespace(
        when=datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc),
        when_date=date(2024, 1, 2),
        text="lunch",
        kcal=600,
        source="manual",
    )

    class DummyClient:
        def query(self, query, job_config=None):
            return [sample_row]

    dummy_client = DummyClient()
    monkeypatch.setattr(meal_service, "bq_client", dummy_client)
    monkeypatch.setattr(meal_service.settings, "BQ_PROJECT_ID", "p")
    monkeypatch.setattr(meal_service.settings, "BQ_DATASET", "d")
    monkeypatch.setattr(meal_service.settings, "BQ_TABLE_MEALS", "t")

    result = asyncio.run(meal_service.meals_last_n_days(1, "demo"))

    assert result == {
        "2024-01-02": [
            {
                "text": "lunch",
                "kcal": 600,
                "when": "2024-01-02T12:00:00+00:00",
                "source": "manual",
            }
        ]
    }
