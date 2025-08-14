# app/services/meal_service.py - 修正版

import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, Any
from app.database.firestore import user_doc
from app.database.bigquery import bq_client
from app.config import settings
import uuid
import logging

logger = logging.getLogger(__name__)

def generate_meal_row_id(payload: dict) -> str:
    """
    食事データの一意キー（row_id）を生成
    内容ベースのハッシュで重複投稿を防ぐ
    """
    # 正規化用のキーフィールド
    key = {
        "user_id": payload.get("user_id", ""),
        "when": payload.get("when", ""),  # ISO8601形式
        "meal_kind": payload.get("meal_kind", ""),
        "image_digest": payload.get("image_digest") or payload.get("image_sha256") or "",
        "notes": (payload.get("notes") or "").strip(),
    }
    
    # JSON化（キー順でソート、セパレータ統一）
    s = json.dumps(key, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def to_when_date_str(iso_str: str | None) -> str:
    """ISO8601文字列の先頭10桁(YYYY-MM-DD)を日付キーとして返す"""
    if not iso_str:
        return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    return iso_str[:10]

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
    
    # テキストの長さチェック
    text = meal_data.get("text", "")
    if len(text) > 1000:
        errors.append("text is too long (max 1000 characters)")
    
    notes = meal_data.get("notes") or ""
    if len(notes) > 1000:
        errors.append("notes is too long (max 1000 characters)")
    
    return {"valid": len(errors) == 0, "errors": errors}

def save_meal_to_stores(meal_data: Dict[str, Any], user_id: str = "demo") -> Dict[str, Any]:
    """
    食事データをFirestoreとBigQueryに保存（重複排除機能付き）
    """
    request_id = str(uuid.uuid4())
    
    # row_idを生成（重複排除用）
    meal_data_for_hash = {
        "user_id": user_id,
        "when": meal_data.get("when"),
        "meal_kind": meal_data.get("meal_kind", ""),
        "image_digest": meal_data.get("image_digest", ""),
        "notes": meal_data.get("notes", ""),
    }
    row_id = generate_meal_row_id(meal_data_for_hash)
    
    logger.info(f"[MEAL_SAVE] request_id={request_id}, row_id={row_id}, user_id={user_id}")
    
    # BigQuery保存（row_idsで重複排除）
    bq_result = {"ok": False, "reason": "not attempted"}
    if bq_client:
        try:
            table_id = f"{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_MEALS}"
            
            # データ準備
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
                "ingested_at": datetime.now(timezone.utc).isoformat(),
                "created_at": meal_data.get("created_at", datetime.now(timezone.utc).isoformat()),
                "request_id": request_id,
                "row_id": row_id,
            }
            
            # row_idsを指定して挿入
            errors = bq_client.insert_rows_json(
                table_id, 
                [bq_data], 
                row_ids=[row_id],  # ここが重要：BigQueryが重複をチェック
                ignore_unknown_values=True
            )
            
            if errors:
                # 重複エラーの場合は成功として扱う
                is_duplicate = any(
                    any(
                        err.get("reason") == "duplicate" or 
                        "already exists" in err.get("message", "").lower()
                        for err in row.get("errors", [])
                    )
                    for row in errors
                )
                
                if is_duplicate:
                    logger.info(f"[MEAL_SAVE] Duplicate detected, row_id={row_id}, treating as success")
                    bq_result = {"ok": True, "inserted": False, "reason": "duplicate"}
                else:
                    logger.error(f"[MEAL_SAVE] BigQuery error: {errors}")
                    bq_result = {"ok": False, "errors": errors}
            else:
                logger.info(f"[MEAL_SAVE] Successfully inserted, row_id={row_id}")
                bq_result = {"ok": True, "inserted": True}
                
        except Exception as e:
            logger.error(f"[MEAL_SAVE] BigQuery exception: {e}")
            bq_result = {"ok": False, "error": str(e)}
    else:
        bq_result = {"ok": False, "reason": "bq disabled"}
    
    # Firestore保存（オプション・参照用）
    firestore_result = {"ok": False}
    try:
        doc_ref = user_doc(user_id).collection("meals").document()
        firestore_data = {
            **meal_data,
            "row_id": row_id,
            "request_id": request_id,
        }
        doc_ref.set(firestore_data)
        firestore_result = {"ok": True, "doc_id": doc_ref.id}
    except Exception as e:
        logger.error(f"[MEAL_SAVE] Firestore error: {e}")
        firestore_result = {"ok": False, "error": str(e)}
    
    # 総合結果を返す
    return {
        "ok": bq_result.get("ok", False),
        "row_id": row_id,
        "request_id": request_id,
        "bigquery": bq_result,
        "firestore": firestore_result,
        "inserted": bq_result.get("inserted", False),
    }
