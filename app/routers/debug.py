from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.config import settings
from app.external.openai_client import ask_gpt5
from app.database.firestore import user_doc
from datetime import datetime, timezone
import httpx
import json

router = APIRouter(tags=["debug"])

@router.get("/env")
def debug_env():
    """環境変数確認"""
    return {
        "has_OPENAI_API_KEY": bool(settings.OPENAI_API_KEY),
        "OPENAI_MODEL": settings.OPENAI_MODEL,
        "has_LINE_TOKEN": bool(settings.LINE_ACCESS_TOKEN),
        "RUN_BASE_URL": settings.RUN_BASE_URL,
        "has_FITBIT_CLIENT_ID": bool(settings.FITBIT_CLIENT_ID),
        "has_HEALTHPLANET_CLIENT_ID": bool(settings.HEALTHPLANET_CLIENT_ID),
    }

@router.get("/openai_ping")
async def debug_openai_ping():
    """OpenAI接続テスト（Chat Completions API）"""
    if not settings.OPENAI_API_KEY:
        return JSONResponse({"ok": False, "reason": "OPENAI_API_KEY not set"}, status_code=500)
    
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}", 
        "Content-Type": "application/json"
    }
    
    # Chat Completions API形式に修正
    body = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {
                "role": "user",
                "content": "ping"
            }
        ],
        "max_tokens": 10
    }
    
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body)
    
    ct = r.headers.get("content-type", "").lower()
    if "application/json" in ct:
        try:
            body_text = json.dumps(r.json(), ensure_ascii=False)
        except Exception:
            body_text = r.text
    else:
        body_text = r.text
    
    return {
        "ok": r.is_success,
        "status": r.status_code,
        "headers": {k.lower(): v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit") or k.lower() in ("retry-after", "content-type")},
        "body": body_text[:1200],
    }

@router.get("/test/firestore")
def test_firestore():
    """Firestore接続テスト"""
    doc_ref = user_doc("demo").collection("tests").document()
    payload = {"message": "hello from refactored app", "ts": datetime.now(timezone.utc).isoformat()}
    doc_ref.set(payload)
    return {"status": "written", "doc_id": doc_ref.id, "payload": payload}

@router.get("/test/line")
def test_line():
    """LINE接続テスト"""
    from app.external.line_client import push_line
    return {"endpoint": "test_line", **push_line("✅ Cloud Run からテスト通知です")}
