# app/database/bigquery.py - 修正版

from google.cloud import bigquery
from google.auth.exceptions import DefaultCredentialsError
from datetime import datetime, timezone, date
from typing import List, Dict, Any
from app.config import settings
import hashlib
import json

# BigQueryクライアントは環境に認証情報がない場合がある。
# その際はNoneとして扱い、アプリケーション全体が起動できるようにする。
try:
    bq_client = bigquery.Client(project=settings.BQ_PROJECT_ID) if settings.BQ_PROJECT_ID else None
except DefaultCredentialsError:
    bq_client = None

def bq_insert_rows(table: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """BigQueryにデータを挿入。

    Streaming insertはネットワーク再送などで同じ行が複数回登録されることが
    あるため、各行の内容からハッシュ値を計算し `row_ids` として指定することで
    BigQuery側での重複排除を行う。
    """
    if not bq_client:
        return {"ok": False, "reason": "bq disabled"}

    table_id = f"{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{table}"

    try:
        row_ids: List[str] = []
        for row in rows:
            # 重複判定に含めないフィールドを拡張
            # タイムスタンプ系とファイル固有情報を除外して、コンテンツベースでハッシュ生成
            row_copy = {
                k: v
                for k, v in row.items()
                if k not in {"ingested_at", "created_at", "file_name", "mime", "updated_at"}
            }
            
            # 特に食事記録の場合、ユーザー、日時、テキスト内容を基準とする
            # これにより同じ食事内容の重複投稿を防ぐ
            if table == settings.BQ_TABLE_MEALS:
                # 食事記録の重複判定キー
                dedup_key = {
                    "user_id": row_copy.get("user_id"),
                    "when_date": row_copy.get("when_date"),
                    "text": row_copy.get("text"),
                    "source": row_copy.get("source"),
                    "meal_kind": row_copy.get("meal_kind"),
                    "image_digest": row_copy.get("image_digest"),
                    "notes": row_copy.get("notes"),
                    # whenは分単位で丸めて、同じ時間帯の重複を防ぐ
                    "when_rounded": row_copy.get("when", "")[:16] if row_copy.get("when") else ""  # YYYY-MM-DDTHH:MM
                }
                row_json = json.dumps(dedup_key, sort_keys=True, ensure_ascii=False)
            else:
                # 他のテーブル用の汎用的な重複判定
                row_json = json.dumps(row_copy, sort_keys=True, ensure_ascii=False)
            
            row_ids.append(hashlib.sha256(row_json.encode()).hexdigest())

        errors = bq_client.insert_rows_json(
            table_id, rows, row_ids=row_ids, ignore_unknown_values=True
        )
        
        result = {"ok": not bool(errors), "errors": errors}
        if not errors:
            print(f"[INFO] Successfully inserted {len(rows)} rows to {table} with deduplication")
        else:
            print(f"[ERROR] BigQuery insert errors: {errors}")
        
        return result
        
    except Exception as e:
        print(f"[ERROR] BigQuery insert failed: {e}")
        return {"ok": False, "error": str(e)}

def bq_upsert_profile(user_id: str = "demo") -> Dict[str, Any]:
    """プロフィールをBigQueryに真のUPSERT処理で保存/更新"""
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
    
    table_id = f"{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_PROFILES}"
    
    try:
        # 1. 既存レコードをチェック
        check_query = f"""
        SELECT COUNT(*) as count
        FROM `{table_id}` 
        WHERE user_id = @user_id
        """
        
        check_job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", user_id)
            ]
        )
        
        check_job = bq_client.query(check_query, job_config=check_job_config)
        result = list(check_job.result())
        record_exists = result[0].count > 0
        
        if record_exists:
            # 2. UPDATEクエリを実行（変更されたカラムのみ更新）
            update_parts = []
            query_params = [bigquery.ScalarQueryParameter("user_id", "STRING", user_id)]
            
            # 各フィールドのUPDATE文を動的に構築
            field_mappings = {
                "age": ("age", "INT64"),
                "sex": ("sex", "STRING"),
                "height_cm": ("height_cm", "FLOAT64"),
                "weight_kg": ("weight_kg", "FLOAT64"),
                "target_weight_kg": ("target_weight_kg", "FLOAT64"),
                "goal": ("goal", "STRING"),
                "smoking_status": ("smoking_status", "STRING"),
                "alcohol_habit": ("alcohol_habit", "STRING"),
                "past_history": ("past_history", "STRING"),
                "medications": ("medications", "STRING"),
                "allergies": ("allergies", "STRING"),
                "notes": ("notes", "STRING"),
                "updated_at": ("updated_at", "TIMESTAMP")
            }
            
            profile_values = {
                "age": prof.get("age"),
                "sex": prof.get("sex"),
                "height_cm": prof.get("height_cm"),
                "weight_kg": prof.get("weight_kg"),
                "target_weight_kg": prof.get("target_weight_kg"),
                "goal": prof.get("goal"),
                "smoking_status": prof.get("smoking_status"),
                "alcohol_habit": prof.get("alcohol_habit"),
                "past_history": past_history_str,
                "medications": prof.get("medications"),
                "allergies": prof.get("allergies"),
                "notes": prof.get("notes"),
                "updated_at": updated_at.isoformat()
            }
            
            param_counter = 0
            for field_name, (column_name, param_type) in field_mappings.items():
                value = profile_values.get(field_name)
                if value is not None:  # Noneでない場合のみ更新
                    param_name = f"param_{param_counter}"
                    if param_type == "TIMESTAMP":
                        # TIMESTAMP型の場合は特別処理
                        update_parts.append(f"{column_name} = TIMESTAMP(@{param_name})")
                        query_params.append(bigquery.ScalarQueryParameter(param_name, "STRING", str(value)))
                    else:
                        update_parts.append(f"{column_name} = @{param_name}")
                        query_params.append(bigquery.ScalarQueryParameter(param_name, param_type, value))
                    param_counter += 1
            
            if update_parts:
                update_query = f"""
                UPDATE `{table_id}` 
                SET {', '.join(update_parts)}
                WHERE user_id = @user_id
                """
                
                update_job_config = bigquery.QueryJobConfig(query_parameters=query_params)
                update_job = bq_client.query(update_query, job_config=update_job_config)
                update_job.result()
                
                return {
                    "ok": True, 
                    "method": "update", 
                    "updated_rows": update_job.num_dml_affected_rows,
                    "updated_fields": len(update_parts),
                    "user_id": user_id
                }
            else:
                return {
                    "ok": True, 
                    "method": "no_changes", 
                    "message": "No fields to update",
                    "user_id": user_id
                }
        
        else:
            # 3. INSERTクエリを実行（新規レコード）
            row = {
                "user_id": user_id,
                "updated_at": updated_at.isoformat(),
                "age": prof.get("age"),
                "sex": prof.get("sex"),
                "height_cm": prof.get("height_cm"),
                "weight_kg": prof.get("weight_kg"),
                "target_weight_kg": prof.get("target_weight_kg"),
                "goal": prof.get("goal"),
                "smoking_status": prof.get("smoking_status"),
                "alcohol_habit": prof.get("alcohol_habit"),
                "past_history": past_history_str,
                "medications": prof.get("medications"),
                "allergies": prof.get("allergies"),
                "notes": prof.get("notes"),
            }
            
            errors = bq_client.insert_rows_json(table_id, [row], ignore_unknown_values=True)
            
            if errors:
                return {"ok": False, "errors": errors}
            
            return {
                "ok": True, 
                "method": "insert", 
                "user_id": user_id,
                "message": "New profile created"
            }
        
    except Exception as e:
        print(f"[ERROR] Profile upsert failed: {e}")
        return {"ok": False, "error": str(e), "user_id": user_id}

def bq_upsert_fitbit_days(user_id: str, days: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not bq_client or not days:
        return {"ok": False, "reason": "bq disabled or empty"}

    def to_int(x):
        try:
            return int(float(x))
        except Exception:
            return 0

    table_id = f"{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_FITBIT}"
    
    rows = []
    row_ids = []
    dates: List[date] = []
    for d in days:
        if not d.get("date"):
            continue
        row_date = datetime.strptime(d["date"], "%Y-%m-%d").date()
        row = {
            "user_id": user_id,
            "date": d["date"],                     # "YYYY-MM-DD"
            "steps_total": to_int(d.get("steps_total", 0)),
            "sleep_line": d.get("sleep_line", ""),
            "spo2_line": d.get("spo2_line", ""),
            "calories_total": to_int(d.get("calories_total", 0)),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }
        rows.append(row)
        dates.append(row_date)
        # 同一 user_id + date で同一IDを使う（idempotent）
        row_ids.append(f"{user_id}|{row['date']}")

    if not rows:
        return {"ok": True, "reason": "no data to insert", "count": 0}

    try:
        # 既存の同じ日付の行を削除し、完全な上書きを行う
        delete_query = f"""
        DELETE FROM `{table_id}`
        WHERE user_id = @user_id AND date IN UNNEST(@dates)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
                bigquery.ArrayQueryParameter("dates", "DATE", dates),
            ]
        )
        bq_client.query(delete_query, job_config=job_config).result()

        errors = bq_client.insert_rows_json(
            table_id, rows, row_ids=row_ids, ignore_unknown_values=True
        )
        return {"ok": not bool(errors), "errors": errors, "count": len(rows)}
    except Exception as e:
        print(f"[ERROR] Fitbit upsert failed: {e}")
        return {"ok": False, "error": str(e), "count": 0}

