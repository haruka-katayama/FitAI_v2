# app/services/meal_service.py - 修正版

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
    """食事データをFirestoreとBigQueryに保存（重複排除機能付き）"""
    
    # 共通のタイムスタンプを生成（重複排除とデータ整合性のため）
    current_time = datetime.now(timezone.utc).isoformat()
    
    # Firestore保存用データ（created_atを統一）
    firestore_data = {**meal_data, "created_at": current_time}
    
    try:
        # Firestore保存
        meals = user_doc(user_id).collection("meals")
        meals.document().set(firestore_data)
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
        "notes": meal_data.get("notes"),
        "ingested_at": current_time,  # 統一されたタイムスタンプを使用
        "created_at": current_time,   # created_atも同じ値に統一
    }

    try:
        bq_result = bq_insert_rows(settings.BQ_TABLE_MEALS, [bq_data])
        if not bq_result.get("ok"):
            print(f"[WARN] BQ insert meals failed: {bq_result.get('errors')}")
            
            # エラーの詳細をログ出力
            errors = bq_result.get("errors", [])
            for error in errors:
                print(f"[ERROR] BigQuery meal insert error: {error}")
                
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
        "dedup_info": {
            "user_id": user_id,
            "when_date": meal_data["when_date"],
            "text_preview": meal_data["text"][:50] + "..." if len(meal_data["text"]) > 50 else meal_data["text"]
        }
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
        "source": meal_data.get("source"),
        "meal_kind": meal_data.get("meal_kind"),
        "image_digest": meal_data.get("image_digest"),
        "notes": meal_data.get("notes"),
        # 時刻は分単位で丸める（秒の違いによる重複を防ぐ）
        "when_rounded": meal_data.get("when", "")[:16] if meal_data.get("when") else ""
    }
    
    # JSONシリアライズしてハッシュ化
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
    str_fields = ["meal_kind", "image_digest", "notes"]
    for field in str_fields:
        if meal_data.get(field) is not None and not isinstance(meal_data.get(field), str):
            errors.append(f"{field} must be a string")

    # テキストの長さチェック
    text = meal_data.get("text", "")
    if len(text) > 1000:  # 制限を設定
        errors.append("text is too long (max 1000 characters)")

    notes = meal_data.get("notes") or ""
    if len(notes) > 1000:
        errors.append("notes is too long (max 1000 characters)")
    
    return {"valid": len(errors) == 0, "errors": errors}

# 統計・分析用のヘルパー関数
def get_meal_stats(user_id: str = "demo", days: int = 7) -> Dict[str, Any]:
    """食事記録の統計情報を取得"""
    import asyncio
    
    async def _get_stats():
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
            "calories_coverage": calorie_count / total_meals if total_meals > 0 else 0
        }
    
    return asyncio.run(_get_stats())
