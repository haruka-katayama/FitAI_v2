from datetime import datetime, timedelta
from typing import List, Dict, Any
import json

from google.cloud import bigquery

from app.external.healthplanet_client import fetch_innerscan_data, jst_now, format_datetime
from app.database.bigquery import bq_client
from app.config import settings

# ---- CONFIG: BigQuery の raw フィールドの型に合わせて切替 ----
# "string" なら raw は JSON 文字列で保存
# "record" なら raw は ネイティブな配列/オブジェクト（RECORD/JSON）で保存
RAW_FIELD_MODE = "string"  # or "record"
# -------------------------------------------------------------

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
    """
    BigQuery用の行データに変換。
    同一タイムスタンプの体重(tag:6021)と体脂肪率(tag:6022)を1行にまとめ、
    weight / fat_percentage に格納する。tag / value は集計列としては使用しない。
    """
    # measured_at(ISO8601) をキーに集約
    rows: Dict[str, Dict[str, Any]] = {}
    now_iso = jst_now().isoformat()

    for item in raw_data.get("data", []):
        timestamp = item.get("date")
        value = item.get("keydata")
        if not timestamp or value in (None, ""):
            continue

        measured_at_iso = datetime.strptime(timestamp, "%Y%m%d%H%M%S").isoformat()
        row = rows.setdefault(
            measured_at_iso,
            {
                "user_id": user_id,
                "measured_at": measured_at_iso,
                "ingested": now_iso,
                # まとめ先
                "weight": None,
                "fat_percentage": None,
                # raw は後でモードに応じて整形
                "raw": [],
            },
        )

        # 値の割当て
        try:
            float_value = float(value)
        except (TypeError, ValueError):
            # 数値化できないものはスキップ
            continue

        tag = item.get("tag")
        if tag == "6021":
            row["weight"] = float_value
        elif tag == "6022":
            row["fat_percentage"] = float_value

        # 元データを保持（あとで string/record に変換）
        row["raw"].append(item)

    # BigQuery 送信用に raw をモードに合わせて整形
    result: List[Dict[str, Any]] = []
    for r in rows.values():
        if RAW_FIELD_MODE == "string":
            r["raw"] = json.dumps(r["raw"], ensure_ascii=False)
        else:  # "record"
            # RECORD/JSON 型に合わせてそのまま配列で渡す
            # テーブルのスキーマ（REPEATED RECORD or JSON）に適合している必要があります
            pass
        result.append(r)

    return result

async def fetch_last7_data(user_id: str = "demo") -> Dict[str, Any]:
    """過去7日間のHealth Planetデータを取得"""
    today = jst_now().date()
    start = datetime(today.year, today.month, today.day, 0, 0, 0) - timedelta(days=6)
    end = datetime(today.year, today.month, today.day, 23, 59, 59)
    
    return await fetch_innerscan_data(
        user_id=user_id,
        date=1,                 # 測定日付
        tag="6021,6022",        # 体重・体脂肪率
        from_dt=format_datetime(start),
        to_dt=format_datetime(end),
    )

def save_to_bigquery(user_id: str, raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """Health PlanetデータをBigQueryに保存"""
    if not bq_client:
        return {"ok": False, "reason": "BigQuery not configured"}

    rows = to_bigquery_rows(user_id, raw_data)
    if not rows:
        return {"ok": True, "saved": 0, "reason": "no data"}

    measured_ats = [r["measured_at"] for r in rows]
    try:
        query = f"""
        SELECT FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%S', measured_at) AS measured_at
        FROM `{settings.HP_BQ_TABLE}`
        WHERE user_id = @user_id
          AND FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%S', measured_at) IN UNNEST(@measured_ats)
        """
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ArrayQueryParameter("measured_ats", "STRING", measured_ats),
        ])
        existing_job = bq_client.query(query, job_config=job_config)
        existing = {row.measured_at for row in existing_job.result()}
        rows = [r for r in rows if r["measured_at"] not in existing]
    except Exception as e:
        print(f"[WARN] failed to check existing rows: {e}")

    if not rows:
        return {"ok": True, "saved": 0, "reason": "duplicate"}

    errors = bq_client.insert_rows_json(settings.HP_BQ_TABLE, rows)
    if errors:
        return {"ok": False, "errors": errors}

    return {"ok": True, "saved": len(rows)}
