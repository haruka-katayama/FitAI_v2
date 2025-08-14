from google.cloud import bigquery
from datetime import datetime, timezone
from typing import List, Dict, Any
from app.config import settings

bq_client = bigquery.Client(project=settings.BQ_PROJECT_ID) if settings.BQ_PROJECT_ID else None

def bq_insert_rows(table: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """BigQueryにデータを挿入"""
    if not bq_client:
        return {"ok": False, "reason": "bq disabled"}
    
    table_id = f"{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{table}"
    
    try:
        errors = bq_client.insert_rows_json(table_id, rows, ignore_unknown_values=True)
        return {"ok": not bool(errors), "errors": errors}
    except Exception as e:
        print(f"[ERROR] BigQuery insert failed: {e}")
        return {"ok": False, "error": str(e)}

def bq_upsert_profile(user_id: str = "demo") -> Dict[str, Any]:
    """プロフィールをBigQueryに保存/更新"""
    from app.database.firestore import get_latest_profile
    
    if not bq_client:
        return {"ok": False, "reason": "bq disabled"}

    prof = get_latest_profile(user_id)
    if not prof:
        return {"ok": False, "reason": "no profile in firestore"}

    # 既往歴をカンマ区切り文字列に変換
    past_history = prof.get("past_history")
    if isinstance(past_history, list):
        past_history_str = ",".join(past_history)
    else:
        past_history_str = past_history or ""
    
    # updated_atの処理
    updated_at_str = prof.get("updated_at") or datetime.now(timezone.utc).isoformat()
    if isinstance(updated_at_str, str):
        try:
            if updated_at_str.endswith('Z'):
                updated_at_str = updated_at_str[:-1] + '+00:00'
            updated_at = datetime.fromisoformat(updated_at_str)
        except ValueError:
            updated_at = datetime.now(timezone.utc)
    else:
        updated_at = updated_at_str
    
    # BigQueryのprofilesテーブルに合わせたデータ構造
    row = {
        "user_id": user_id,
        "updated_at": updated_at.isoformat(),  # ISO文字列として送信
        "age": prof.get("age"),
        "sex": prof.get("sex"),
        "height_cm": prof.get("height_cm"),
        "weight_kg": prof.get("weight_kg"),
        "target_weight_kg": prof.get("target_weight_kg"),
        "goal": prof.get("goal"),
        "smoking_status": prof.get("smoking_status"),
        "alcohol_habit": prof.get("alcohol_habit"),
        "past_history": past_history_str,  # 文字列として保存
        "medications": prof.get("medications"),
        "allergies": prof.get("allergies"),
        "notes": prof.get("notes"),
    }
    
    table_id = f"{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_PROFILES}"
    
    try:
        # まず既存レコードを削除
        delete_query = f"DELETE FROM `{table_id}` WHERE user_id = @user_id"
        delete_job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", user_id)
            ]
        )
        
        delete_job = bq_client.query(delete_query, job_config=delete_job_config)
        delete_job.result()
        
        # 新しいレコードを挿入
        errors = bq_client.insert_rows_json(table_id, [row], ignore_unknown_values=True)
        
        if errors:
            return {"ok": False, "errors": errors}
        
        return {
            "ok": True, 
            "method": "delete+insert", 
            "deleted": delete_job.num_dml_affected_rows,
            "user_id": user_id
        }
        
    except Exception as e:
        print(f"[ERROR] Profile upsert failed: {e}")
        return {"ok": False, "error": str(e), "user_id": user_id}

def bq_upsert_fitbit_days(user_id: str, days: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fitbit日次データをBigQueryに保存（標準のINSERTを使用）"""
    if not bq_client or not days:
        return {"ok": False, "reason": "bq disabled or empty"}

    def to_int(x):
        try:
            return int(float(x))
        except Exception:
            return 0

    table_id = f"{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_FITBIT}"
    
    rows = []
    for d in days:
        if not d.get("date"):
            continue
            
        row = {
            "user_id": user_id,
            "date": d["date"],  # "YYYY-MM-DD"
            "steps_total": to_int(d.get("steps_total", 0)),
            "sleep_line": d.get("sleep_line", ""),
            "spo2_line": d.get("spo2_line", ""),
            "calories_total": to_int(d.get("calories_total", 0)),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }
        rows.append(row)

    if not rows:
        return {"ok": True, "reason": "no data to insert", "count": 0}

    try:
        # 既存データを削除してから挿入（UPSERT的な動作）
        dates_to_delete = [row["date"] for row in rows]
        date_list = "', '".join(dates_to_delete)
        delete_query = f"""
        DELETE FROM `{table_id}` 
        WHERE user_id = '{user_id}' 
          AND date IN ('{date_list}')
        """
        
        delete_job = bq_client.query(delete_query)
        delete_job.result()
        
        # 新しいデータを挿入
        errors = bq_client.insert_rows_json(table_id, rows, ignore_unknown_values=True)
        
        return {
            "ok": not bool(errors), 
            "errors": errors, 
            "count": len(rows),
            "deleted": delete_job.num_dml_affected_rows
        }
        
    except Exception as e:
        print(f"[ERROR] Fitbit upsert failed: {e}")
        return {"ok": False, "error": str(e), "count": 0}
