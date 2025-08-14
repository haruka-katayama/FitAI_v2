from fastapi import APIRouter
from fastapi.responses import RedirectResponse, JSONResponse
from app.external.fitbit_client import get_redirect_uri, fitbit_exchange_code, get_fitbit_access_token
from app.services.fitbit_service import fitbit_today_core, fitbit_last_n_days, save_fitbit_daily_firestore, save_last7_fitbit_to_stores
from app.database.firestore import fitbit_token_doc
from app.external.line_client import push_line
from app.config import settings
from app.database.bigquery import bq_insert_rows
from datetime import datetime, timezone
import urllib.parse
import httpx

router = APIRouter(tags=["fitbit"])

@router.get("/login")
def login_fitbit():
    """Fitbit OAuth認証開始"""
    redirect_uri = get_redirect_uri()
    if not all([settings.FITBIT_CLIENT_ID, settings.FITBIT_CLIENT_SECRET, redirect_uri]):
        return JSONResponse({"error": "FITBIT_* envs or RUN_BASE_URL not set"}, status_code=500)
    
    params = {
        "response_type": "code",
        "client_id": settings.FITBIT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": settings.FITBIT_SCOPE,
        "prompt": "consent",
        "expires_in": "604800",
    }
    url = "https://www.fitbit.com/oauth2/authorize?" + urllib.parse.urlencode(params)
    return RedirectResponse(url)

@router.get("/auth")
async def auth_fitbit(code: str = "", state: str = ""):
    """Fitbit OAuth認証コールバック"""
    if not code:
        return JSONResponse({"ok": False, "error": "code not provided"}, status_code=400)
    
    try:
        token = await fitbit_exchange_code(code)
        now = int(datetime.now(timezone.utc).timestamp())
        expires_at = now + int(token.get("expires_in", 3600))
        
        fitbit_token_doc("demo").set({
            "access_token": token["access_token"],
            "refresh_token": token.get("refresh_token"),
            "token_type": token.get("token_type", "Bearer"),
            "scope": token.get("scope"),
            "user_id": token.get("user_id"),
            "expires_at": expires_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        
        push_line("✅ Fitbit連携が完了しました")
        return RedirectResponse(url="/")
    except httpx.HTTPStatusError as e:
        return JSONResponse({"ok": False, "where": "exchange", "status": e.response.status_code, "body": e.response.text}, status_code=500)
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=500)

@router.get("/today")
async def fitbit_today():
    """今日のFitbitデータ取得"""
    return await fitbit_today_core()

@router.get("/last7")
async def fitbit_last7():
    """過去7日間のFitbitデータ取得"""
    data = await fitbit_last_n_days(7)

    def to_int(x: str) -> int:
        try:
            return int(float(x))
        except Exception:
            return 0

    steps_sum = sum(to_int(d["steps_total"]) for d in data)
    calories_sum = sum(to_int(d["calories_total"]) for d in data)
    return {"days": data, "summary": {"steps_sum": steps_sum, "calories_sum": calories_sum, "count": len(data)}}

@router.post("/save/today")
async def fitbit_save_today():
    """今日のFitbitデータを保存"""
    day = await fitbit_today_core()
    saved = save_fitbit_daily_firestore("demo", day)
    
    try:
        bq_insert_rows(settings.BQ_TABLE_FITBIT, [{
            "user_id": "demo",
            "date": saved["date"],
            "steps_total": saved["steps_total"],
            "sleep_line": saved["sleep_line"],
            "spo2_line": saved["spo2_line"],
            "calories_total": saved["calories_total"],
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }])
    except Exception as e:
        print(f"[WARN] BQ insert (fitbit_save_today) failed: {e}")
    
    return {"ok": True, "saved": saved}

@router.post("/save/last7")
async def fitbit_save_last7():
    """過去7日間のFitbitデータを保存"""
    try:
        res = await save_last7_fitbit_to_stores("demo")
        return {"ok": True, **res}
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=500)
