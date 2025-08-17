from datetime import datetime, timedelta
import json
from typing import List, Dict, Any
from app.external.healthplanet_client import fetch_innerscan_data, jst_now, format_datetime
from app.database.bigquery import bq_client
from app.config import settings

def parse_innerscan_for_prompt(raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """APIレスポンスをプロンプト用に整形"""
    rows: Dict[str, Dict[str, Any]] = {}
    
    for item in raw_data.get("data", []):
        timestamp = item.get("date")  # "yyyymmddHHMMSS"
        if not timestamp:
            continue
        
        day_key = timestamp[:8]  # YYYYMMDD
        row = rows.setdefault(day_key, {"measured_at": day_key})
        
        tag = item.get("tag")
        value = item.get("keydata")
        if value in (None, ""):
            continue
        
        if tag == "6021":  # 体重(kg)
            row["weight_kg"] = float(value)
        elif tag == "6022":  # 体脂肪率(%)
            row["body_fat_pct"] = float(value)
    
    return [rows[k] for k in sorted(rows.keys())]

def summarize_for_prompt(rows: List[Dict[str, Any]]) -> str:
    """プロンプト用のサマリーテキストを生成"""
    if not rows:
        return "HealthPlanet: 過去7日間に体重・体脂肪の記録はありません。"
    
    lines = []
    for row in rows:
        date_str = f"{row['measured_at'][:4]}-{row['measured_at'][4:6]}-{row['measured_at'][6:8]}"
        weight = f"{row.get('weight_kg'):.1f}kg" if row.get("weight_kg") is not None else "-"
        fat = f"{row.get('body_fat_pct'):.1f}%" if row.get("body_fat_pct") is not None else "-"
        lines.append(f"{date_str}: 体重 {weight}, 体脂肪 {fat}")
    
    return "HealthPlanet 過去7日:\n" + "\n".join(lines)

def to_bigquery_rows(user_id: str, raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """BigQuery用の行データに変換

    同一タイムスタンプの体重(tag:6021)と体脂肪率(tag:6022)を1行にまとめ、
    `weight` と `fat_percentage` に分割格納する。`value` や `tag` は使用しない。
    """
    rows: Dict[str, Dict[str, Any]] = {}
    now = jst_now().isoformat()

    for item in raw_data.get("data", []):
        timestamp = item.get("date")
        value = item.get("keydata")
        if not timestamp or value in (None, ""):
            continue

        measured_at = datetime.strptime(timestamp, "%Y%m%d%H%M%S").isoformat()
        row = rows.setdefault(measured_at, {
            "user_id": user_id,
            "measured_at": measured_at,
            "tag": None,
            "value": None,
            "unit": None,
            "ingested": now,
            "raw": [],
            "weight": None,
            "fat_percentage": None,
        })

        float_value = float(value)
        row["raw"].append(item)

        tag = item.get("tag")
        if tag == "6021":
            row["weight"] = float_value
        elif tag == "6022":
            row["fat_percentage"] = float_value

    result = []
    for row in rows.values():
        row["raw"] = json.dumps(row["raw"], ensure_ascii=False)
        result.append(row)

    return result

async def fetch_last7_data(user_id: str = "demo") -> Dict[str, Any]:
    """過去7日間のHealth Planetデータを取得"""
    today = jst_now().date()
    start = datetime(today.year, today.month, today.day, 0, 0, 0) - timedelta(days=6)
    end = datetime(today.year, today.month, today.day, 23, 59, 59)
    
    return await fetch_innerscan_data(
        user_id=user_id,
        date=1,  # 測定日付
        tag="6021,6022",  # 体重・体脂肪率
        from_dt=format_datetime(start),
        to_dt=format_datetime(end)
    )

def save_to_bigquery(user_id: str, raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """Health PlanetデータをBigQueryに保存"""
    if not bq_client:
        return {"ok": False, "reason": "BigQuery not configured"}
    
    rows = to_bigquery_rows(user_id, raw_data)
    if not rows:
        return {"ok": True, "saved": 0, "reason": "no data"}
    
    errors = bq_client.insert_rows_json(settings.HP_BQ_TABLE, rows)
    if errors:
        return {"ok": False, "errors": errors}
    
    return {"ok": True, "saved": len(rows)}
