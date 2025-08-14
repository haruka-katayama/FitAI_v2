# app/routers/ui.py - 食事画像アップロード部分の修正

from fastapi import APIRouter, HTTPException, Header, File, UploadFile, Form, Query
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from app.models.profile import ProfileIn
from app.models.meal import MealIn
from app.services.meal_service import save_meal_to_stores, to_when_date_str, validate_meal_data
from app.external.openai_client import vision_extract_meal_bytes
from app.database.firestore import user_doc, get_latest_profile
from app.database.bigquery import bq_upsert_profile
from app.config import settings
from app.utils.auth_utils import require_token
import base64
import hashlib
import json
import uuid

router = APIRouter(prefix="/ui", tags=["ui"])

@router.get("/profile")
def ui_profile_get(x_api_token: str | None = Header(None, alias="x-api-token")):
    """プロフィール取得"""
    require_token(x_api_token)
    snap = user_doc("demo").collection("profile").document("latest").get()
    if not snap.exists:
        return {"ok": True, "profile": {}}
    return {"ok": True, "profile": snap.to_dict()}

@router.post("/profile")
def ui_profile(body: ProfileIn, x_api_token: str | None = Header(None, alias="x-api-token")):
    """プロフィール保存"""
    require_token(x_api_token)
    doc = user_doc("demo").collection("profile").document("latest")
    payload = {k: v for k, v in body.dict().items() if v is not None}
    
    # notes から gender/target_weight_kg を補完
    def parse_notes(notes: str | None) -> dict[str, str]:
        out: dict[str, str] = {}
        if not notes:
            return out
        for line in notes.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
        return out

    nmap = parse_notes(payload.get("notes"))
    if "sex" not in payload and "gender" in nmap:
        payload["sex"] = nmap["gender"]
    if "target_weight_kg" not in payload and "target_weight_kg" in nmap:
        try:
            payload["target_weight_kg"] = float(nmap["target_weight_kg"])
        except Exception:
            pass

    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    doc.set(payload, merge=True)
    
    # BigQuery同期
    try:
        bq_res = bq_upsert_profile("demo")
        if not bq_res.get("ok"):
            print(f"[WARN] bq_upsert_profile failed: {bq_res}")
    except Exception as e:
        print(f"[ERROR] bq_upsert_profile exception: {e}")
        bq_res = {"ok": False, "reason": repr(e)}

    return {"ok": True, "bq": bq_res}

@router.get("/profile_latest")
def ui_profile_latest(x_api_token: str | None = Header(None, alias="x-api-token")):
    """最新プロフィール取得"""
    require_token(x_api_token)
    doc = user_doc("demo").collection("profile").document("latest").get()
    return doc.to_dict() or {}

@router.post("/meal")
def ui_meal(body: MealIn, x_api_token: str | None = Header(None, alias="x-api-token")):
    """テキスト食事記録"""
    require_token(x_api_token)

    request_id = str(uuid.uuid4())
    payload = body.dict()
    payload["created_at"] = datetime.now(timezone.utc).isoformat()
    payload["when_date"] = to_when_date_str(body.when)
    payload["source"] = "text"

    # データバリデーション
    validation = validate_meal_data(payload)
    if not validation["valid"]:
        return JSONResponse(
            {
                "ok": False,
                "error": "Validation failed",
                "details": validation["errors"],
                "request_id": request_id,
            },
            status_code=400,
        )

    try:
        save_res = save_meal_to_stores(payload, "demo")
        dedup_key = save_res.get("dedup_key")
        print(f"[INFO] meal saved request_id={request_id} dedup_key={dedup_key}")
        return {
            "ok": save_res["ok"],
            "request_id": request_id,
            "dedup_key": dedup_key,
            "details": save_res,
        }
    except Exception as e:
        print(f"[ERROR] request_id={request_id} Failed to save meal: {e}")
        return JSONResponse(
            {"ok": False, "error": str(e), "request_id": request_id},
            status_code=500,
        )

@router.post("/meal_image")
async def ui_meal_image_no_store(
    x_api_token: str | None = Header(None, alias="x-api-token"),
    when: str | None = Form(None),
    file: UploadFile = File(...),
    dry: bool = Query(False),
):
    """画像食事記録（重複排除機能付き）"""
    require_token(x_api_token)

    request_id = str(uuid.uuid4())
    data: bytes = await file.read()
    mime = file.content_type or "image/png"

    # Dry runモード（テスト用）
    if dry:
        return {
            "ok": True,
            "stage": "received",
            "file_name": file.filename,
            "size": len(data),
            "mime": mime,
            "request_id": request_id,
        }

    # OpenAI API キー確認
    if not settings.OPENAI_API_KEY:
        return JSONResponse(
            {
                "ok": False,
                "where": "openai_api_key",
                "error": "OPENAI_API_KEY not set",
                "request_id": request_id,
            },
            status_code=500,
        )

    # 処理開始時刻を記録（一貫性のため）
    processing_start_time = datetime.now(timezone.utc)
    when_iso = when or processing_start_time.isoformat(timespec="seconds")

    # 重複チェック用のキーを事前に生成
    dedup_preview_data = {
        "user_id": "demo",
        "when_date": to_when_date_str(when_iso),
        "when_rounded": when_iso[:16],  # 分単位で丸める
        "file_size": len(data),
        "mime": mime,
    }

    # 画像のハッシュを生成（同じ画像の重複投稿検知用）
    image_hash = hashlib.sha256(data).hexdigest()[:16]  # 短縮版
    dedup_preview_data["image_hash"] = image_hash

    try:
        # 画像をOpenAI APIに送信してテキスト化
        print(
            f"[INFO] Processing meal image: {file.filename}, size: {len(data)} bytes, request_id={request_id}"
        )
        text = await vision_extract_meal_bytes(data, mime)
        print(f"[INFO] OpenAI response: {text[:100]}... request_id={request_id}")

    except Exception as e:
        print(f"[ERROR] request_id={request_id} OpenAI processing failed: {e}")
        return JSONResponse(
            {"ok": False, "where": "openai", "error": repr(e), "request_id": request_id},
            status_code=500,
        )

    # 保存用データの準備（統一されたタイムスタンプを使用）
    save_timestamp = processing_start_time.isoformat()

    payload = {
        "when": when_iso,
        "when_date": to_when_date_str(when_iso),
        "text": text,
        "created_at": save_timestamp,  # 統一されたタイムスタンプ
        "source": "image-bytes+gpt",
        "file_name": file.filename,
        "mime": mime,
        "image_hash": image_hash,  # 重複検知用のハッシュを追加
        "processing_metadata": {
            "file_size": len(data),
            "processing_duration_ms": int(
                (datetime.now(timezone.utc) - processing_start_time).total_seconds() * 1000
            ),
        },
    }

    # データバリデーション
    validation = validate_meal_data(payload)
    if not validation["valid"]:
        return JSONResponse(
            {
                "ok": False,
                "where": "validation",
                "error": "Invalid data",
                "details": validation["errors"],
                "request_id": request_id,
            },
            status_code=400,
        )

    try:
        # データベースに保存
        print(f"[INFO] Saving meal data to stores... request_id={request_id}")
        save_res = save_meal_to_stores(payload, "demo")
        dedup_key = save_res.get("dedup_key")

        # 保存結果をログ出力（デバッグ用）
        print(
            f"[INFO] Save result request_id={request_id} dedup_key={dedup_key} - Overall: {save_res.get('ok')}, Firestore: {save_res.get('firestore', {}).get('ok')}, BigQuery: {save_res.get('bigquery', {}).get('ok')}"
        )

    except Exception as e:
        print(f"[ERROR] request_id={request_id} Storage operation failed: {e}")
        return JSONResponse(
            {"ok": False, "where": "storage", "error": repr(e), "request_id": request_id},
            status_code=500,
        )

    # BigQuery保存が失敗した場合の処理
    bq_result = save_res.get("bigquery", {})
    if not bq_result.get("ok"):
        bq_errors = bq_result.get("errors", [])
        error_msg = bq_result.get("error", "Unknown BigQuery error")

        print(f"[ERROR] request_id={request_id} BigQuery save failed: {error_msg}")
        if bq_errors:
            print(f"[ERROR] request_id={request_id} BigQuery errors detail: {bq_errors}")

        # BigQuery失敗でもプレビューは返す（ユーザー体験のため）
        return JSONResponse(
            {
                "ok": False,
                "where": "bigquery_storage",
                "error": f"BigQuery save failed: {error_msg}",
                "preview": text,
                "firestore_ok": save_res.get("firestore", {}).get("ok"),
                "bigquery_errors": bq_errors,
                "request_id": request_id,
                "dedup_key": dedup_key,
            },
            status_code=500,
        )

    # Firestore保存が失敗した場合は警告ログのみ（処理は継続）
    if not save_res.get("firestore", {}).get("ok"):
        firestore_error = save_res.get("firestore", {}).get("error")
        print(f"[WARN] request_id={request_id} Firestore meal save failed: {firestore_error}")

    # 成功レスポンス
    return {
        "ok": True,
        "preview": text,
        "saved_to": {
            "firestore": save_res.get("firestore", {}).get("ok"),
            "bigquery": save_res.get("bigquery", {}).get("ok"),
        },
        "image_hash": image_hash,
        "dedup_key": dedup_key,
        "request_id": request_id,
        "processing_time_ms": payload["processing_metadata"]["processing_duration_ms"],
    }

# デバッグ用エンドポイント
@router.get("/meal_debug/recent")
def ui_meal_debug_recent(
    x_api_token: str | None = Header(None, alias="x-api-token"),
    limit: int = Query(10)
):
    """最近の食事記録をデバッグ用に取得"""
    require_token(x_api_token)
    
    try:
        # Firestoreから最近の食事記録を取得
        meals_ref = user_doc("demo").collection("meals").order_by("created_at", direction="DESCENDING").limit(limit)
        meals = []
        
        for doc in meals_ref.stream():
            meal_data = doc.to_dict()
            meals.append({
                "id": doc.id,
                "when": meal_data.get("when"),
                "text": meal_data.get("text", "")[:100],  # 最初の100文字のみ
                "source": meal_data.get("source"),
                "created_at": meal_data.get("created_at"),
                "image_hash": meal_data.get("image_hash"),
            })
        
        return {"ok": True, "meals": meals, "count": len(meals)}
        
    except Exception as e:
        print(f"[ERROR] Debug query failed: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
