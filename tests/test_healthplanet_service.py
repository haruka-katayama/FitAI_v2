import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types import SimpleNamespace

from app.services.healthplanet_service import to_bigquery_rows, save_to_bigquery


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


def test_save_to_bigquery_skips_existing(monkeypatch):
    raw_data = {
        "data": [
            {"date": "20250101000000", "keydata": "60", "tag": "6021"},
            {"date": "20250102000000", "keydata": "61", "tag": "6021"},
        ]
    }

    inserted = []

    class DummyQueryJob:
        def result(self):
            return [SimpleNamespace(measured_at="2025-01-01T00:00:00")]

    class DummyClient:
        def query(self, *args, **kwargs):
            return DummyQueryJob()

        def insert_rows_json(self, table, rows):
            inserted.extend(rows)
            return []

    dummy = DummyClient()
    monkeypatch.setattr("app.services.healthplanet_service.bq_client", dummy)

    result = save_to_bigquery("demo", raw_data)

    assert result["ok"] is True
    assert result["saved"] == 1
    assert len(inserted) == 1
    assert inserted[0]["measured_at"] == "2025-01-02T00:00:00"
