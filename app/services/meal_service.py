# app/services/meal_service.py - 修正版（コンフリクト解消済み）

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
from app.database.bigquery import bq_client
from google.cloud import bigquery
from app.config import settings

async def meals_last_n_days(n: int = 7, user_id: str = "demo") -> Dict[str, List[Dict[str, Any]]]:
    """
    直近n日分の食事を日付キーで返す:
    { "YYYY-MM-DD": [ {text,kcal,when,source}, ... ], ... }
    """
    tz_today = datetime.now(timezone.utc).astimezone().date()
    start_date = tz_today - timedelta(days=n - 1)
    end_date = tz_today

    result: Dict[str, List[Dict[str, Any]]] = {}
    if not bq_client:
        return result

    table_id = f"{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_MEALS}"
    query = f"""
        SELECT
            `when`,
            when_date,
            text,
            kcal,
            source,
            image_base64
        FROM `{table_id}`
        WHERE user_id = @user_id
          AND when_date BETWEEN @start_date AND @end_date
        ORDER BY `when`
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    try:
        rows_iter = bq_client.query(query, job_config=job_config)
        for row in rows_iter:
            # when_date があれば isoformat、無ければ when から "YYYY-MM-DD" を生成
            key = (
                row.when_date.isoformat()
                if getattr(row, "when_date", None)
                else (row.when.strftime("%Y-%m-%d") if getattr(row, "when", None) else "")
            )
            result.setdefault(key, []).append(
                {
                    "text": row.text or "",
                    "kcal": row.kcal,
                    "when": row.when.isoformat() if getattr(row, "when", None) else None,
                    "source": row.source,
                }
            )
    except Exception as e:
        print(
            f"[ERROR] BigQuery meals fetch failed: {type(e).__name__}: {e}. query={query}"
        )

    return result

def save_meal_to_stores(meal_data: Dict[str, Any], user_id: str = "demo") -> Dict[str, Any]:
    """食事データをFirestoreとBigQueryに保存（重複排除機能付き）"""
    from app.database.firestore import user_doc

    # 重複排除キーを生成し、保存前に存在チェック
    dedup_key = create_meal_dedup_key(meal_data, user_id)
    meals = user_doc(user_id).collection("meals")
    doc_ref = meals.document(dedup_key)

    try:
        if doc_ref.get().exists:
            # 既に登録済みの場合は保存をスキップ
            return {
                "ok": True,
                "firestore": {"ok": True, "skipped": True},
                "bigquery": {"ok": True, "skipped": True},
                "dedup_key": dedup_key,
                "timestamp_used": None,
                "dedup_info": {
                    "user_id": user_id,
                    "when_date": meal_data["when_date"],
                    "text_preview": meal_data["text"][:50] + "..." if len(meal_data["text"]) > 50 else meal_data["text"]
                }
            }
    except Exception as e:
        # チェックに失敗しても保存は試みる
        print(f"[WARN] Firestore dedup check failed: {e}")

    # 共通のタイムスタンプを生成（重複排除とデータ整合性のため）
    current_time = datetime.now(timezone.utc).isoformat()

    # Firestore保存用データ（created_atを統一、dedup_keyも保持）
    firestore_data = {**meal_data, "created_at": current_time, "dedup_key": dedup_key}

    try:
        # Firestore保存
        doc_ref.set(firestore_data)
        firestore_result = {"ok": True}
    except Exception as e:
        print(f"[ERROR] Firestore meal save failed: {e}")
        firestore_result = {"ok": False, "error": str(e)}

    # BigQuery保存用データ（ingested_atも統一）
    bq_data = {
        "user_id": user_id,
        "when": meal_data["when"],
        "when_date": meal_data["when_date"],
        "text": meal_data["text"],
        "kcal": meal_data.get("kcal"),
        "source": meal_data.get("source", "text"),
        "file_name": meal_data.get("file_name"),
        "mime": meal_data.get("mime"),
        "meal_kind": meal_data.get("meal_kind"),
        "image_digest": meal_data.get("image_digest"),
        "image_base64": meal_data.get("image_base64"),
        "notes": meal_data.get("notes"),
        "ingested_at": current_time,  # 統一されたタイムスタンプを使用
        "created_at": current_time,   # created_atも同じ値に統一
        "dedup_key": dedup_key,       # 重複判定用キーも格納
    }

    try:
        if bq_client:
            table_id = f"{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_MEALS}"

            # 既に同じdedup_keyのレコードが存在するかチェック
            check_query = f"""
                SELECT 1
                FROM `{table_id}`
                WHERE dedup_key = @dedup_key
                LIMIT 1
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("dedup_key", "STRING", dedup_key)]
            )
            check_job = bq_client.query(check_query, job_config=job_config)
            if list(check_job.result()):
                bq_result = {"ok": True, "skipped": True}
            else:
                errors = bq_client.insert_rows_json(
                    table_id, [bq_data], row_ids=[dedup_key], ignore_unknown_values=True
                )

                if errors:
                    # 既に存在する場合（重複エラー）は成功として扱う
                    all_dup = all(
                        all(
                            err.get("reason") == "duplicate" or "already" in err.get("message", "").lower()
                            for err in row.get("errors", [])
                        )
                        for row in errors
                    )
                    bq_result = {"ok": all_dup, "errors": errors, "skipped": all_dup}
                    if not all_dup:
                        print(f"[ERROR] BigQuery meal insert error: {errors}")
                else:
                    bq_result = {"ok": True}
        else:
            bq_result = {"ok": False, "reason": "bq disabled"}
    except Exception as e:
        print(f"[ERROR] BQ meal save failed: {e}")
        bq_result = {"ok": False, "error": str(e)}

    # 結果の統合
    overall_ok = firestore_result.get("ok") and bq_result.get("ok")

    return {
        "ok": overall_ok,
        "firestore": firestore_result,
        "bigquery": bq_result,
        "timestamp_used": current_time,  # デバッグ情報として追加
        "dedup_key": dedup_key,
        "dedup_info": {
            "user_id": user_id,
            "when_date": meal_data["when_date"],
            "text_preview": meal_data["text"][:50] + "..." if len(meal_data["text"]) > 50 else meal_data["text"],
        },
    }

def create_meal_dedup_key(meal_data: Dict[str, Any], user_id: str) -> str:
    """食事データの重複排除キーを生成"""
    import hashlib
    import json
    
    # 重複排除用のキーフィールドのみ抽出
    dedup_fields = {
        "user_id": user_id,
        "when_date": meal_data.get("when_date"),
        "text": meal_data.get("text"),
        # 時刻は分単位で丸める（秒の違いによる重複を防ぐ）
        "when_rounded": meal_data.get("when", "")[:16] if meal_data.get("when") else ""
    }
    # 画像ハッシュがあれば重複判定に含める
    if meal_data.get("image_digest"):
        dedup_fields["image_digest"] = meal_data["image_digest"]
    if meal_data.get("memo_digest"):
        dedup_fields["memo_digest"] = meal_data["memo_digest"]
    
    key_json = json.dumps(dedup_fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(key_json.encode()).hexdigest()

def validate_meal_data(meal_data: Dict[str, Any]) -> Dict[str, Any]:
    """食事データのバリデーション"""
    errors = []
    
    # 必須フィールドのチェック
    required_fields = ["when", "when_date", "text"]
    for field in required_fields:
        if not meal_data.get(field):
            errors.append(f"Missing required field: {field}")
    
    # データ型のチェック
    if meal_data.get("kcal") is not None:
        try:
            float(meal_data["kcal"])
        except (ValueError, TypeError):
            errors.append("kcal must be a valid number")

    # 文字列型のチェック
    str_fields = [
        "meal_kind",
        "image_digest",
        "notes",
        "image_base64",
        "memo_digest",
    ]
    for field in str_fields:
        if meal_data.get(field) is not None and not isinstance(meal_data.get(field), str):
            errors.append(f"{field} must be a string")

    # テキストの長さチェック
    text = meal_data.get("text", "")
    if len(text) > 1000:
        errors.append("text is too long (max 1000 characters)")

    notes = meal_data.get("notes") or ""
    if len(notes) > 1000:
        errors.append("notes is too long (max 1000 characters)")
    
    return {"valid": len(errors) == 0, "errors": errors}

# 統計・分析用のヘルパー関数
async def get_meal_stats(user_id: str = "demo", days: int = 7) -> Dict[str, Any]:
    """食事記録の統計情報を取得

    コールサイトは ``await get_meal_stats(...)`` として利用する。
    """
    meals_map = await meals_last_n_days(days, user_id)

    total_meals = sum(len(meals) for meals in meals_map.values())
    total_days = len(meals_map)

    # カロリー統計
    total_calories = 0
    calorie_count = 0

    for day_meals in meals_map.values():
        for meal in day_meals:
            if meal.get("kcal"):
                total_calories += float(meal["kcal"])
                calorie_count += 1

    avg_calories_per_meal = total_calories / calorie_count if calorie_count > 0 else 0
    avg_calories_per_day = total_calories / total_days if total_days > 0 else 0

    return {
        "period_days": days,
        "total_meals": total_meals,
        "avg_meals_per_day": total_meals / total_days if total_days > 0 else 0,
        "total_calories": total_calories,
        "avg_calories_per_meal": avg_calories_per_meal,
        "avg_calories_per_day": avg_calories_per_day,
        "meals_with_calories": calorie_count,
        "calories_coverage": calorie_count / total_meals if total_meals > 0 else 0,
    }

def get_meal_stats_sync(user_id: str = "demo", days: int = 7) -> Dict[str, Any]:
    """同期コンテキストから食事記録の統計情報を取得"""
    import asyncio
    return asyncio.run(get_meal_stats(user_id, days))
