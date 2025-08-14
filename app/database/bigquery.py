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
    errors = bq_client.insert_rows_json(table_id, rows, ignore_unknown_values=True)
    return {"ok": not bool(errors), "errors": errors}

def bq_upsert_profile(user_id: str = "demo") -> Dict[str, Any]:
    """プロフィールをBigQueryに保存/更新（実際のスキーマに合わせた上書き処理）"""
    from app.database.firestore import get_latest_profile
    
    if not bq_client:
        return {"ok": False, "reason": "bq disabled"}

    prof = get_latest_profile(user_id)
    if not prof:
        return {"ok": False, "reason": "no profile in firestore"}

    past_history = ",".join(prof.get("past_history") or [])
    
    # 実際のスキーマに合わせたデータ準備
    # updated_atがISO文字列の場合、TIMESTAMPに変換
    updated_at_str = prof.get("updated_at") or datetime.now(timezone.utc).isoformat()
    if isinstance(updated_at_str, str):
        try:
            # ISO文字列をdatetimeオブジェクトに変換
            if updated_at_str.endswith('Z'):
                updated_at_str = updated_at_str[:-1] + '+00:00'
            updated_at = datetime.fromisoformat(updated_at_str)
        except ValueError:
            updated_at = datetime.now(timezone.utc)
    else:
        updated_at = updated_at_str
    
    row = {
        "user_id": user_id,
        "updated_at": updated_at,  # datetimeオブジェクトとして渡す
        "age": prof.get("age"),
        "sex": prof.get("sex"),
        "height_cm": prof.get("height_cm"),
        "weight_kg": prof.get("weight_kg"),
        "target_weight_kg": prof.get("target_weight_kg"),
        "goal": prof.get("goal"),
        "smoking_status": prof.get("smoking_status"),
        "alcohol_habit": prof.get("alcohol_habit"),
        "past_history": past_history,
        "medications": prof.get("medications"),
        "allergies": prof.get("allergies"),
        "notes": prof.get("notes"),
    }
    
    table_id = f"{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_PROFILES}"
    
    try:
        # MERGE文を使用した上書き処理（実際のスキーマに合わせて調整）
        merge_query = f"""
        MERGE `{table_id}` T
        USING (
            SELECT 
                @user_id as user_id,
                @updated_at as updated_at,
                @age as age,
                @sex as sex,
                @height_cm as height_cm,
                @weight_kg as weight_kg,
                @target_weight_kg as target_weight_kg,
                @goal as goal,
                @smoking_status as smoking_status,
                @alcohol_habit as alcohol_habit,
                @past_history as past_history,
                @medications as medications,
                @allergies as allergies,
                @notes as notes
        ) S
        ON T.user_id = S.user_id
        WHEN MATCHED THEN
            UPDATE SET
                updated_at = S.updated_at,
                age = S.age,
                sex = S.sex,
                height_cm = S.height_cm,
                weight_kg = S.weight_kg,
                target_weight_kg = S.target_weight_kg,
                goal = S.goal,
                smoking_status = S.smoking_status,
                alcohol_habit = S.alcohol_habit,
                past_history = S.past_history,
                medications = S.medications,
                allergies = S.allergies,
                notes = S.notes
        WHEN NOT MATCHED THEN
            INSERT (
                user_id, updated_at, age, sex, height_cm, 
                weight_kg, target_weight_kg, goal, smoking_status, 
                alcohol_habit, past_history, medications, allergies, notes
            )
            VALUES (
                S.user_id, S.updated_at, S.age, S.sex, S.height_cm,
                S.weight_kg, S.target_weight_kg, S.goal, S.smoking_status,
                S.alcohol_habit, S.past_history, S.medications, S.allergies, S.notes
            )
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", row["user_id"]),
                bigquery.ScalarQueryParameter("updated_at", "TIMESTAMP", row["updated_at"]),
                bigquery.ScalarQueryParameter("age", "INT64", row["age"]),
                bigquery.ScalarQueryParameter("sex", "STRING", row["sex"]),
                bigquery.ScalarQueryParameter("height_cm", "FLOAT64", row["height_cm"]),
                bigquery.ScalarQueryParameter("weight_kg", "FLOAT64", row["weight_kg"]),
                bigquery.ScalarQueryParameter("target_weight_kg", "FLOAT64", row["target_weight_kg"]),
                bigquery.ScalarQueryParameter("goal", "STRING", row["goal"]),
                bigquery.ScalarQueryParameter("smoking_status", "STRING", row["smoking_status"]),
                bigquery.ScalarQueryParameter("alcohol_habit", "STRING", row["alcohol_habit"]),
                bigquery.ScalarQueryParameter("past_history", "STRING", row["past_history"]),
                bigquery.ScalarQueryParameter("medications", "STRING", row["medications"]),
                bigquery.ScalarQueryParameter("allergies", "STRING", row["allergies"]),
                bigquery.ScalarQueryParameter("notes", "STRING", row["notes"]),
            ]
        )
        
        query_job = bq_client.query(merge_query, job_config=job_config)
        query_job.result()  # 完了まで待機
        
        return {
            "ok": True, 
            "method": "merge", 
            "rows_affected": query_job.num_dml_affected_rows,
            "user_id": user_id
        }
        
    except Exception as e:
        print(f"[ERROR] MERGE failed, trying DELETE+INSERT: {e}")
        
        try:
            # フォールバック: DELETE + INSERT による上書き処理
            delete_query = f"DELETE FROM `{table_id}` WHERE user_id = @user_id"
            delete_job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("user_id", "STRING", user_id)
                ]
            )
            
            delete_job = bq_client.query(delete_query, job_config=delete_job_config)
            delete_job.result()
            
            # 新しいレコードを挿入（datetimeをISO文字列に変換）
            insert_row = row.copy()
            insert_row["updated_at"] = row["updated_at"].isoformat()
            
            errors = bq_client.insert_rows_json(table_id, [insert_row], ignore_unknown_values=True)
            if errors:
                return {"ok": False, "method": "delete+insert", "errors": errors}
            
            return {
                "ok": True, 
                "method": "delete+insert", 
                "deleted": delete_job.num_dml_affected_rows,
                "user_id": user_id
            }
            
        except Exception as e2:
            return {
                "ok": False, 
                "method": "failed", 
                "merge_error": str(e), 
                "delete_insert_error": str(e2),
                "user_id": user_id
            }

def bq_upsert_fitbit_days(user_id: str, days: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fitbit日次データをBigQueryに保存（日付パーティションごとに上書き）"""
    if not bq_client or not days:
        return {"ok": False, "reason": "bq disabled or empty"}

    def to_int(x):
        try:
            return int(float(x))
        except Exception:
            return 0

    jobs = []
    for d in days:
        if not d.get("date"):
            continue
        date_str = d["date"]                 # "YYYY-MM-DD"
        part = date_str.replace("-", "")     # "YYYYMMDD"
        table_id = f"{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_FITBIT}${part}"

        row = {
            "user_id": user_id,
            "date": date_str,
            "steps_total": to_int(d.get("steps_total", 0)),
            "sleep_line": d.get("sleep_line", ""),
            "spo2_line": d.get("spo2_line", ""),
            "calories_total": to_int(d.get("calories_total", 0)),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }

        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            schema=[
                bigquery.SchemaField("user_id", "STRING"),
                bigquery.SchemaField("date", "DATE"),
                bigquery.SchemaField("steps_total", "INTEGER"),
                bigquery.SchemaField("sleep_line", "STRING"),
                bigquery.SchemaField("spo2_line", "STRING"),
                bigquery.SchemaField("calories_total", "INTEGER"),
                bigquery.SchemaField("ingested_at", "TIMESTAMP"),
            ],
        )

        job = bq_client.load_table_from_json([row], table_id, job_config=job_config)
        jobs.append(job)

    errors = []
    for j in jobs:
        j.result()
        if j.errors:
            errors.extend(j.errors)

    return {"ok": not bool(errors), "errors": errors, "count": len(jobs)}
