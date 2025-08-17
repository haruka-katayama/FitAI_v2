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

    # 体重・体脂肪率が同一タイムスタンプで1行に統合される
    assert len(rows) == 1

    row = rows[0]
    # 基本カラム
    assert row["user_id"] == "demo"
    assert row["measured_at"].startswith("2025-08-16T00:26:00")
    assert "raw" in row  # raw の型はスキーマ依存のため存在のみ確認

    # 値のマッピング
    assert row["weight"] == pytest.approx(62.40)
    assert row["fat_percentage"] == pytest.approx(21.40)

    # 実装では tag/value は出力しない想定（存在しないことを確認）
    assert "tag" not in row
    assert "value" not in row
