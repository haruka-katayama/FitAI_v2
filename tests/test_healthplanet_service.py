import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.healthplanet_service import to_bigquery_rows


def test_to_bigquery_rows_combines_weight_and_fat_percentage():
    raw_data = {
        "birth_date": "19920710",
        "data": [
            {"date": "20250816002600", "keydata": "62.40", "model": "01000144", "tag": "6021"},
            {"date": "20250816002600", "keydata": "21.40", "model": "01000144", "tag": "6022"},
        ],
        "height": "158",
        "sex": "male",
    }

    rows = to_bigquery_rows("demo", raw_data)
    assert len(rows) == 1

    row = rows[0]
    assert row["weight"] == pytest.approx(62.40)
    assert row["fat_percentage"] == pytest.approx(21.40)
    assert row["tag"] is None
    assert row["value"] is None
