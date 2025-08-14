from fastapi import APIRouter, Form
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from app.external.healthplanet_client import (
    get_oauth_url, exchange_code_for_token, is_env_configured, jst_now
)
from app.database.firestore import healthplanet_token_doc  # 修正: 正しいインポート
from app.services.healthplanet_service import (
    fetch_last7_data, parse_innerscan_for_prompt, 
    summarize_for_prompt, save_to_bigquery
)
from app.config import settings

router = APIRouter(prefix="/healthplanet", tags=["healthplanet"])

@router.get("/login")
def login_healthplanet():
    """Health Planet OAuth認証開始"""
    if not is_env_configured():
        return JSONResponse(
            {"error": "Set HEALTHPLANET_CLIENT_ID / HEALTHPLANET_CLIENT_SECRET"},
            status_code=500,
        )
    
    try:
        url = get_oauth_url()
        return RedirectResponse(url)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/code")
def code_input_form():
    """認証コード入力フォーム"""
    return HTMLResponse("""
        <form method="post" action="/healthplanet/auth" style="font-family:system-ui;">
          <label>Paste code from success.html:</label><br/>
          <input name="code" placeholder="code" style="width:360px;padding:6px;margin-top:6px;" />
          <button type="submit" style="margin-left:8px;padding:6px 12px;">Submit</button>
        </form>
    """)

@router.get("/auth")
async def auth_healthplanet_get(code: str = ""):
    """OAuth認証コールバック（GET）"""
    return await _exchange_and_store(code)

@router.post("/auth")
async def auth_healthplanet_post(code: str = Form("")):
    """OAuth認証コールバック（POST）"""
    return await _exchange_and_store(code)

async def _exchange_and_store(code: str):
    """認証コードをトークンに交換してFirestoreに保存"""
    if not code:
        return JSONResponse({"ok": False, "error": "code not provided"}, status_code=400)
    
    if not is_env_configured():
        return JSONResponse({"ok": False, "error": "env not set"}, status_code=500)

    try:
        token = await exchange_code_for_token(code)
        
        # Firestore保存
        healthplanet_token_doc("demo").set({
            "access_token": token.get("access_token"),
            "token_type": token.get("token_type", "Bearer"),
            "scope": settings.HEALTHPLANET_SCOPE,
            "raw": token,
            "updated_at": jst_now().isoformat(),
        })
        
        return RedirectResponse(url="/healthplanet/status")
    
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.get("/innerscan/last7")
async def innerscan_last7(user_id: str = "demo"):
    """過去7日間の体組成データ取得"""
    try:
        data = await fetch_last7_data(user_id)
        return data
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.get("/innerscan/last7/prompt")
async def innerscan_last7_prompt(user_id: str = "demo"):
    """過去7日間データのプロンプト用サマリー"""
    try:
        raw_data = await fetch_last7_data(user_id)
        rows = parse_innerscan_for_prompt(raw_data)
        prompt_snippet = summarize_for_prompt(rows)
        
        return {
            "ok": True,
            "prompt_snippet": prompt_snippet,
            "rows": rows
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.post("/innerscan/last7/save_bq")
async def innerscan_last7_save_bq(user_id: str = "demo"):
    """過去7日間データをBigQueryに保存"""
    try:
        raw_data = await fetch_last7_data(user_id)
        result = save_to_bigquery(user_id, raw_data)
        
        if not result["ok"]:
            return JSONResponse(result, status_code=500)
        
        return result
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.get("/status")
def status():
    """Health Planet連携状況確認"""
    return {
        "ok": True,
        "endpoints": {
            "login": "/healthplanet/login",
            "callback": "/healthplanet/auth (GET/POST)",
            "code_form": "/healthplanet/code",
            "last7": "/healthplanet/innerscan/last7",
            "last7_prompt": "/healthplanet/innerscan/last7/prompt",
            "last7_save_bq": "/healthplanet/innerscan/last7/save_bq (POST)",
        },
        "bq": {"table": settings.HP_BQ_TABLE, "location": settings.BQ_LOCATION},
    }
