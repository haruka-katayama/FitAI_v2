import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.coaching_service import build_weekly_prompt


def test_build_weekly_prompt_includes_healthplanet_data():
    days = [
        {
            "date": "2025-01-01",
            "steps_total": "1000",
            "sleep_line": "7h",
            "spo2_line": "98",
            "calories_total": "2000",
        }
    ]
    meals_by_day = {"2025-01-01": []}
    hp_by_day = {"2025-01-01": {"weight_kg": 60.0, "body_fat_pct": 20.0}}

    prompt = build_weekly_prompt(days, meals_by_day, hp_by_day=hp_by_day)

    assert "体重60.0kg" in prompt
    assert "体脂肪率20.0%" in prompt
