from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
from app.database.firestore import user_doc
from app.database.bigquery import bq_insert_rows
from app.config import settings

def to_when_date_str(iso_str: str | None) -> str:
    """ISO8601文字列の先頭10桁(YYYY-MM-DD)を日付キーとして返す"""
    if not iso_str:
        return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    return iso_str[:10]

async def meals_last_n_days(n: int = 7, user_id: str = "demo") -> Dict[str, List[Dict[str, Any]]]:
    """
    直近n日分の食事を日付キーで返す:
    { "YYYY-MM-DD": [ {text,kcal,when,source}, ... ], ... }
    """
    tz_today = datetime.now(timezone.utc).astimezone().date()
    start_date = (tz_today - timedelta(days=n-1)).strftime("%Y-%m-%d")
    end_date   = tz_today.strftime("%Y-%m-%d")

    q = (user_doc(user_id)
         .collection("meals")
         .where("when_date", ">=", start_date)
         .where("when_date", "<=", end_date)
         .order_by("when_date"))

    result: Dict[str, List[Dict[str, Any]]] = {}
    for snap in q.stream():
        d = snap.to_dict()
        key = d.get("when_date") or (d.get("when", "")[:10])
        result.setdefault(key, []).append({
            "text": d.get("text", ""),
            "kcal": d.get("kcal"),
            "when": d.get("when"),
            "source": d.get("source"),
        })
    return result

def save_meal_to_stores(meal_data: Dict[str, Any], user_id: str = "demo") -> Dict[str, Any]:
    """食事データをFirestoreとBigQueryに保存"""
    # Firestore保存
    meals = user_doc(user_id).collection("meals")
    meals.document().set(meal_data)

    # BigQuery保存
    bq_data = {
        "user_id": user_id,
        "when": meal_data["when"],
        "when_date": meal_data["when_date"],
        "text": meal_data["text"],
        "kcal": meal_data.get("kcal"),
        "source": meal_data.get("source", "text"),
        "file_name": meal_data.get("file_name"),
        "mime": meal_data.get("mime"),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    
    bq_result = bq_insert_rows(settings.BQ_TABLE_MEALS, [bq_data])
    if not bq_result.get("ok"):
        print(f"[ERROR] BQ insert meals failed: {bq_result.get('errors')}")
    
    return {"firestore": True, "bigquery": bq_result}
