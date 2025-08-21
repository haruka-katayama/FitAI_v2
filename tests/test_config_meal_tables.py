import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.config as config_module


def test_meal_tables_configurable_independently(monkeypatch):
    """Ensure dashboard and meal service tables can be set separately."""
    monkeypatch.setenv("BQ_TABLE_MEALS", "meal_table")
    monkeypatch.setenv("BQ_TABLE_MEALS_DASHBOARD", "dashboard_table")
    importlib.reload(config_module)

    assert config_module.settings.BQ_TABLE_MEALS == "meal_table"
    assert config_module.settings.BQ_TABLE_MEALS_DASHBOARD == "dashboard_table"

    # Clean up: reload settings without the overridden env vars
    monkeypatch.delenv("BQ_TABLE_MEALS", raising=False)
    monkeypatch.delenv("BQ_TABLE_MEALS_DASHBOARD", raising=False)
    importlib.reload(config_module)
