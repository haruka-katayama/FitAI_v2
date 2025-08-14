# app/routers/ui.py

from fastapi import APIRouter, Header, File, UploadFile, Form, Query
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from app.models.meal import MealIn
from app.services.meal_service import save_meal_to_stores, validate_meal_data
from app.external.openai_client import vision_extract_meal_bytes
from app.config import settings
from app.utils.auth_utils import require_token
from app.utils.date_utils import to_when_date_str
import hashlib
import uuid
import logging

router = APIRouter(prefix="/ui", tags=["ui"])
logger = logging.getLogger(__name__)

def _round_down_to_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)

def _resolve_user_id(x_user_id: str | None) -> str:
    # 実運用では x-api-token からの復元/検証で user_id を得る。
    # 暫定としてヘッダ優先→なければ "demo"
    return x_user_id or "demo"

@router.post("/meal_image")
async def ui_meal_image(
    x_api_token: str | None = Header(None, alias="x-api-token"),
    x_user_id: str | None = Header(None, alias="x-user-id"),
    when: str | None = Form(None),
    file: UploadFile = File(...),
    dry: bool = Query(False),
):
    """画像食事記録（重複排除機能付き）"""
    require_token(x_api_token)
    user_id = _resolve_user_id(x_user_id)

    request_id = str(uuid.uuid4())
    logger.info(f"[MEAL_IMAGE] start request_id={request_id} user_id={user_id}")

    data: bytes = await file.read()
    mime = file.content_type or "image/png"

    if dry:
        return {
            "ok": True,
            "stage": "received",
            "file_name": file.filename,
            "size": len(data),
            "mime": mime,
            "request_id": request_id,
        }

    if not settings.OPENAI_API_KEY:
        return JSONResponse(
            {"ok": False, "error": "OPENAI_API_KEY not set", "request_id": request_id},
            status_code=500,
        )

    processing_time = datetime.now(timezone.utc)
    when_iso = when or processing_time.isoformat(timespec="seconds")

    # フルSHA-256（短縮しない）で画像ダイジェスト
    image_digest = hashlib.sha256(data).hexdigest()

    try:
        logger.info(f"[MEAL_IMAGE] calling OpenAI, request_id={request_id}")
        text = await vision_extract_meal_bytes(data, mime)
        logger.info(f"[MEAL_IMAGE] OpenAI done, request_id={request_id}")
    except Exception as e:
        logger.exception(f"[MEAL_IMAGE] OpenAI error request_id={request_id}")
        return JSONResponse(
            {"ok": False, "error": str(e), "request_id": request_id},
            status_code=500,
        )

    # 一貫したタイムスタンプと丸め
    created_at = processing_time.isoformat()
    when_dt = datetime.fromisoformat(when_iso.replace("Z", "+00:00"))
    when_minute = _round_down_to_minute(when_dt).isoformat()

    payload = {
        "when": when_iso,
        "when_date": to_when_date_str(when_iso),
        "when_minute": when_minute,  # サービス層の重複キー素材に使える
        "text": text,
        "created_at": created_at,
        "source": "image-bytes+gpt",
        "file_name": file.filename,
        "mime": mime,
        "image_digest": image_digest,   # ←一本化（短縮版は使わない）
        "meal_kind": "other",
        "notes": "",
        "user_id": user_id,             # ← payloadにも入れておく
    }

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
        save_res = save_meal_to_stores(payload, user_id)
        if not save_res["ok"]:
            logger.error(f"[MEAL_IMAGE] save failed {save_res}, request_id={request_id}")
            return JSONResponse(
                {"ok": False, "error": "Failed to save meal data", "details": save_res, "request_id": request_id},
                status_code=500,
            )

        skipped = save_res.get("firestore", {}).get("skipped")
        resp = {
            "ok": True,
            "dedup_key": save_res["dedup_key"],
            "request_id": request_id,
            "inserted": not skipped,
            "preview": text,
        }
        if skipped:
            resp["message"] = "既に登録済みのデータです（重複をスキップしました）"

        logger.info(f"[MEAL_IMAGE] success dedup_key={save_res['dedup_key']} request_id={request_id}")
        return resp

    except Exception as e:
        logger.exception(f"[MEAL_IMAGE] unexpected error request_id={request_id}")
        return JSONResponse({"ok": False, "error": str(e), "request_id": request_id}, status_code=500)

@router.post("/meal")
def ui_meal(
    body: MealIn,
    x_api_token: str | None = Header(None, alias="x-api-token"),
    x_user_id: str | None = Header(None, alias="x-user-id"),
):
    """テキスト食事記録（重複排除機能付き）"""
    require_token(x_api_token)
    user_id = _resolve_user_id(x_user_id)

    request_id = str(uuid.uuid4())
    logger.info(f"[MEAL_TEXT] start request_id={request_id} user_id={user_id}")

    payload = body.dict()
    payload["created_at"] = datetime.now(timezone.utc).isoformat()
    payload["when_date"] = to_when_date_str(body.when)
    payload["source"] = "text"
    payload["user_id"] = user_id

    validation = validate_meal_data(payload)
    if not validation["valid"]:
        return JSONResponse(
            {"ok": False, "error": "Validation failed", "details": validation["errors"], "request_id": request_id},
            status_code=400,
        )

    try:
        save_res = save_meal_to_stores(payload, user_id)
        skipped = save_res.get("firestore", {}).get("skipped")
        resp = {
            "ok": save_res["ok"],
            "dedup_key": save_res["dedup_key"],
            "request_id": request_id,
            "inserted": not skipped,
        }
        if skipped:
            resp["message"] = "既に登録済みのデータです（重複をスキップしました）"

        logger.info(f"[MEAL_TEXT] done dedup_key={save_res['dedup_key']} request_id={request_id}")
        return resp

    except Exception as e:
        logger.exception(f"[MEAL_TEXT] error request_id={request_id}")
        return JSONResponse({"ok": False, "error": str(e), "request_id": request_id}, status_code=500)

# ⭐ プレビュー専用：保存なし
@router.post("/meal_image/preview")
async def ui_meal_image_preview(
    x_api_token: str | None = Header(None, alias="x-api-token"),
    file: UploadFile = File(...),
):
    require_token(x_api_token)
    data: bytes = await file.read()
    mime = file.content_type or "image/png"

    if not settings.OPENAI_API_KEY:
        return JSONResponse({"ok": False, "error": "OPENAI_API_KEY not set"}, status_code=500)

    text = await vision_extract_meal_bytes(data, mime)
    return {"ok": True, "preview": text, "size": len(data), "mime": mime}
