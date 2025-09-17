# app/routers/ui.py

from fastapi import APIRouter, Header, File, UploadFile, Form, Query
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from typing import Dict, Any
from app.models.meal import MealIn
from app.services.meal_service import save_meal_to_stores, validate_meal_data
from app.external.openai_client import vision_extract_meal_bytes, ask_gpt
from app.config import settings
from app.utils.auth_utils import require_token
from app.utils.date_utils import to_when_date_str
from app.database import get_latest_profile, user_doc, bq_upsert_profile
from app.database.bigquery import bq_client
from google.cloud import bigquery
import hashlib
import uuid
import logging
import base64
from io import BytesIO
try:
    from PIL import Image  # type: ignore
except Exception:  # Pillow optional
    Image = None  # fallback when Pillow is not installed

router = APIRouter(prefix="/ui", tags=["ui"])
logger = logging.getLogger(__name__)

def _round_down_to_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)

def _resolve_user_id(x_user_id: str | None) -> str:
    # 実運用では x-api-token からの復元/検証で user_id を得る。
    # 暫定としてヘッダ優先→なければ "demo"
    return x_user_id or "demo"


def _compress_image_to_limit(data: bytes, mime: str, max_size: int) -> tuple[bytes, str]:
    """画像を max_size 未満になるよう自動圧縮する"""
    if Image is None:
        return data, mime
    try:
        img = Image.open(BytesIO(data))
        img = img.convert("RGB")
        img.thumbnail((1024, 1024))
        for quality in range(95, 19, -5):
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            compressed = buf.getvalue()
            if len(compressed) <= max_size:
                return compressed, "image/jpeg"
        return compressed, "image/jpeg"
    except Exception as e:
        logger.warning(f"[MEAL_IMAGE] auto compression failed: {e}")
        return data, mime

@router.post("/meal_image")
async def ui_meal_image(
    x_api_token: str | None = Header(None, alias="x-api-token"),
    x_user_id: str | None = Header(None, alias="x-user-id"),
    when: str | None = Form(None),
    memo: str | None = Form(None),
    file: UploadFile | None = File(None),
    dry: bool = Query(False),
):
    """画像食事記録（重複排除機能付き）"""
    require_token(x_api_token)
    user_id = _resolve_user_id(x_user_id)

    request_id = str(uuid.uuid4())
    logger.info(f"[MEAL_IMAGE] start request_id={request_id} user_id={user_id}")

    memo_text = memo.strip() if memo else ""
    memo_value = memo_text or None
    memo_digest = (
        hashlib.sha256(memo_text.encode("utf-8")).hexdigest() if memo_value else None
    )

    processing_time = datetime.now(timezone.utc)
    when_iso = when or processing_time.isoformat(timespec="seconds")

    text: str
    file_name: str | None = None
    mime: str | None = None
    image_digest: str | None = None
    image_base64: str | None = None
    source: str

    if file is None:
        if not memo_value:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Image or memo required",
                    "request_id": request_id,
                },
                status_code=400,
            )

        if dry:
            return {
                "ok": True,
                "stage": "received",
                "file_name": None,
                "size": 0,
                "mime": None,
                "request_id": request_id,
                "memo_only": True,
            }

        if not settings.OPENAI_API_KEY:
            return JSONResponse(
                {"ok": False, "error": "OPENAI_API_KEY not set", "request_id": request_id},
                status_code=500,
            )

        instruction = (
            "以下のユーザーメモのみから食事内容を短い日本語テキストで説明してください。"
            "メモに含まれる料理名を端的に列挙してください。"
            "単体でも複数でも必ず総カロリーを推定し、想定される最大値のみを数字で回答してください。"
            "カロリーの出力形式は「数字 + kcal」としてください。"
            "出力は料理名とカロリーのみ、体言止め、丁寧語不要。"
        )
        prompt = f"{instruction}\n\nユーザーのメモ: {memo_text}"

        try:
            logger.info(f"[MEAL_IMAGE] calling GPT (memo-only), request_id={request_id}")
            text = await ask_gpt(prompt)
            logger.info(f"[MEAL_IMAGE] GPT done, request_id={request_id}")
            text = text.replace(f"ユーザーのメモ: {memo_text}", "").strip()
            if not text:
                text = memo_text
        except Exception as e:
            logger.exception(f"[MEAL_IMAGE] GPT error request_id={request_id}")
            return JSONResponse(
                {"ok": False, "error": str(e), "request_id": request_id},
                status_code=500,
            )

        source = "memo+gpt"
    else:
        data: bytes = await file.read()
        mime = file.content_type or "image/png"

        if len(data) == 0:
            return JSONResponse(
                {"ok": False, "error": "Empty file", "request_id": request_id},
                status_code=400,
            )

        max_size = 1 * 1024 * 1024  # 1MB
        if len(data) > max_size:
            original_size = len(data)
            data, mime = _compress_image_to_limit(data, mime, max_size)
            if len(data) > max_size:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "File too large",
                        "message": "ファイルサイズを1MB未満にしてください",
                        "request_id": request_id,
                    },
                    status_code=400,
                )
            logger.info(
                f"[MEAL_IMAGE] compressed image from {original_size} to {len(data)} bytes"
            )

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

        # フルSHA-256（短縮しない）で画像ダイジェスト
        image_digest = hashlib.sha256(data).hexdigest()

        # 画像圧縮とBase64変換（ダッシュボード表示用）
        try:
            if Image is not None:
                img = Image.open(BytesIO(data))
                img = img.convert("RGB")
                img.thumbnail((512, 512))
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=75)
                image_bytes = buf.getvalue()
            else:
                image_bytes = data  # no compression if Pillow not available
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        except Exception as e:
            logger.warning(f"[MEAL_IMAGE] image compression failed: {e}")

        try:
            logger.info(f"[MEAL_IMAGE] calling OpenAI, request_id={request_id}")
            text = await vision_extract_meal_bytes(data, mime, memo_value)
            logger.info(f"[MEAL_IMAGE] OpenAI done, request_id={request_id}")
            if memo_value:
                text = text.replace(f"ユーザーのメモ: {memo_value}", "").replace(memo_value, "").strip()
        except Exception as e:
            logger.exception(f"[MEAL_IMAGE] OpenAI error request_id={request_id}")
            return JSONResponse(
                {"ok": False, "error": str(e), "request_id": request_id},
                status_code=500,
            )

        file_name = file.filename
        source = "image-bytes+gpt"

    created_at = processing_time.isoformat()
    try:
        when_dt = datetime.fromisoformat(when_iso.replace("Z", "+00:00"))
    except ValueError:
        return JSONResponse(
            {
                "ok": False,
                "error": "Invalid 'when' value",
                "request_id": request_id,
            },
            status_code=400,
        )
    when_minute = _round_down_to_minute(when_dt).isoformat()

    payload = {
        "when": when_iso,
        "when_date": to_when_date_str(when_iso),
        "when_minute": when_minute,
        "text": text,
        "created_at": created_at,
        "source": source,
        "file_name": file_name,
        "mime": mime,
        "image_digest": image_digest,
        "image_base64": image_base64,
        "meal_kind": "other",
        "user_id": user_id,
    }
    if memo_digest:
        payload["memo_digest"] = memo_digest

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

    if len(data) == 0:
        return JSONResponse({"ok": False, "error": "Empty file"}, status_code=400)

    max_size = 1 * 1024 * 1024  # 1MB
    if len(data) > max_size:
        original_size = len(data)
        data, mime = _compress_image_to_limit(data, mime, max_size)
        if len(data) > max_size:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "File too large",
                    "message": "ファイルサイズを1MB未満にしてください",
                },
                status_code=400,
            )
        logger.info(
            f"[MEAL_IMAGE] compressed preview image from {original_size} to {len(data)} bytes"
        )

    if not settings.OPENAI_API_KEY:
        return JSONResponse({"ok": False, "error": "OPENAI_API_KEY not set"}, status_code=500)

    text = await vision_extract_meal_bytes(data, mime)
    return {"ok": True, "preview": text, "size": len(data), "mime": mime}


@router.get("/profile")
def ui_get_profile(
    x_api_token: str | None = Header(None, alias="x-api-token"),
    x_user_id: str | None = Header(None, alias="x-user-id"),
) -> Dict[str, Any]:
    """保存されたユーザープロフィールを取得"""
    require_token(x_api_token)
    user_id = _resolve_user_id(x_user_id)
    profile = get_latest_profile(user_id) or {}

    # BigQueryから最新の体重を取得し、プロフィールに反映
    if bq_client:
        try:
            query = f"""
                SELECT weight
                FROM `{settings.HP_BQ_TABLE}`
                WHERE user_id = @user_id
                ORDER BY measured_at DESC
                LIMIT 1
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("user_id", "STRING", user_id)
                ]
            )
            query_job = bq_client.query(query, job_config=job_config)
            row = next(iter(query_job.result()), None)
            if row and row.weight is not None:
                profile["weight_kg"] = float(row.weight)
        except Exception as e:
            logger.exception("Failed to fetch latest weight: %s", e)

    return {"ok": True, "profile": profile}


@router.post("/profile")
def ui_post_profile(
    body: Dict[str, Any],
    x_api_token: str | None = Header(None, alias="x-api-token"),
    x_user_id: str | None = Header(None, alias="x-user-id"),
) -> Dict[str, Any]:
    """ユーザープロフィールを保存"""
    require_token(x_api_token)
    user_id = _resolve_user_id(x_user_id)

    payload = dict(body)
    payload.setdefault("updated_at", datetime.now(timezone.utc).isoformat())

    try:
        doc_ref = user_doc(user_id).collection("profile").document("latest")
        doc_ref.set(payload)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    bq = bq_upsert_profile(user_id)
    return {"ok": True, "profile": payload, "bq": bq}
