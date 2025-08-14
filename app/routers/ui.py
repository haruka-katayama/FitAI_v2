from fastapi import APIRouter, HTTPException, Header, File, UploadFile, Form, Query
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from app.models.profile import ProfileIn
from app.models.meal import MealIn
from app.services.meal_service import save_meal_to_stores, to_when_date_str  # 修正: インポート追加
from app.external.openai_client import vision_extract_meal_bytes
from app.database.firestore import user_doc, get_latest_profile
from app.database.bigquery import bq_upsert_profile
from app.config import settings
from app.utils.auth_utils import require_token
import base64

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
    
    try:
        bq_res = bq_upsert_profile("demo")
        if not bq_res.get("ok"):
            print(f"[ERROR] bq_upsert_profile failed: {bq_res}")
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
    
    payload = body.dict()
    payload["created_at"] = datetime.now(timezone.utc).isoformat()
    payload["when_date"] = to_when_date_str(body.when)
    payload["source"] = "text"
    
    save_meal_to_stores(payload, "demo")
    return {"ok": True}

@router.post("/meal_image")
async def ui_meal_image_no_store(
    x_api_token: str | None = Header(None, alias="x-api-token"),
    when: str | None = Form(None),
    file: UploadFile = File(...),
    dry: bool = Query(False),
):
    """画像食事記録"""
    require_token(x_api_token)

    data: bytes = await file.read()
    mime = file.content_type or "image/png"

    if dry:
        return {
            "ok": True,
            "stage": "received",
            "file_name": file.filename,
            "size": len(data),
            "mime": mime,
        }

    if not settings.OPENAI_API_KEY:
        return JSONResponse({"ok": False, "error": "OPENAI_API_KEY not set"}, status_code=500)

    # 画像→OpenAI
    try:
        text = await vision_extract_meal_bytes(data, mime)
    except Exception as e:
        return JSONResponse({"ok": False, "where": "openai", "error": repr(e)}, status_code=500)
    
    try:
        when_iso = when or datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = {
            "when": when_iso,
            "when_date": to_when_date_str(when_iso),
            "text": text,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": "image-bytes+gpt",
            "file_name": file.filename,
            "mime": mime,
        }
        save_meal_to_stores(payload, "demo")
    except Exception as e:
        return JSONResponse({"ok": False, "where": "firestore", "error": repr(e),
                             "preview": text}, status_code=500)
    
    return {"ok": True, "preview": text}
