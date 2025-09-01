import sys
from pathlib import Path
import asyncio
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import coaching_service as cs


def setup_monkeypatch(monkeypatch):
    days = [{
        "date": "2025-01-01",
        "steps_total": "1000",
        "sleep_line": "7h",
        "spo2_line": "98",
        "calories_total": "2000",
    }]

    async def dummy_fitbit_last_n_days(n):
        return days

    def dummy_save(user_id, d):
        return d

    monkeypatch.setattr("app.services.fitbit_service.fitbit_last_n_days", dummy_fitbit_last_n_days)
    monkeypatch.setattr("app.services.fitbit_service.save_fitbit_daily_firestore", dummy_save)

    async def dummy_meals_last_n_days(n, uid):
        return {}

    monkeypatch.setattr(cs, "meals_last_n_days", dummy_meals_last_n_days)
    monkeypatch.setattr(cs, "get_latest_profile", lambda uid: {})
    monkeypatch.setattr("app.database.bigquery.bq_upsert_fitbit_days", lambda uid, d: {})
    monkeypatch.setattr("app.database.bigquery.bq_upsert_profile", lambda uid: {})
    monkeypatch.setattr(cs, "ask_gpt", lambda prompt: "ok")
    monkeypatch.setattr(cs, "push_line", lambda text: {"sent": True})

    async def dummy_fetch_last7_data(uid):
        return []

    monkeypatch.setattr("app.services.healthplanet_service.fetch_last7_data", dummy_fetch_last7_data)
    monkeypatch.setattr("app.services.healthplanet_service.parse_innerscan_for_prompt", lambda raw: [])


def test_accepts_lowercase_character(monkeypatch):
    setup_monkeypatch(monkeypatch)
    res = asyncio.run(cs.weekly_coaching(dry=True, show_prompt=True, character="b"))
    assert cs.CHARACTER_PROMPTS["B"] in res["prompt"]


def test_invalid_character_defaults(monkeypatch):
    setup_monkeypatch(monkeypatch)
    res = asyncio.run(cs.weekly_coaching(dry=True, show_prompt=True, character="z"))
    assert cs.CHARACTER_PROMPTS["A"] in res["prompt"]
