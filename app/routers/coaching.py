from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.services.coaching_service import daily_coaching, weekly_coaching, monthly_coaching, build_daily_prompt
from app.external.openai_client import ask_gpt5
from app.external.line_client import push_line
from app.config import settings
import httpx

router = APIRouter(tags=["coaching"])

@router.get("/now")
async def coach_now():
    """今すぐコーチング"""
    # 循環インポートを避けるため、ここで import
    from app.services.fitbit_service import fitbit_today_core
    
    day = await fitbit_today_core()
    prompt = build_daily_prompt(day)
    msg = await ask_gpt5(prompt)
    res = push_line(f"📣 今日のコーチング\n{msg}")
    return {"sent": res, "model": settings.OPENAI_MODEL, "preview": msg}

@router.get("/now_debug")
async def coach_now_debug():
    """デバッグ用コーチング"""
    try:
        # 循環インポートを避けるため、ここで import
        from app.services.fitbit_service import fitbit_today_core
        
        day = await fitbit_today_core()
        prompt = build_daily_prompt(day)
        out = await ask_gpt5(prompt)
        return {"ok": True, "preview": out, "model": settings.OPENAI_MODEL}
    except httpx.HTTPStatusError as e:
        return JSONResponse({"ok": False, "status": e.response.status_code, "body": e.response.text[:1200]}, status_code=500)
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=500)

@router.get("/weekly")
async def coach_weekly(dry: bool = False, show_prompt: bool = False):
    """週次コーチング"""
    try:
        result = await weekly_coaching(dry, show_prompt)
        return result
    except Exception as e:
        return JSONResponse({"ok": False, "where": "coach_weekly", "error": repr(e)}, status_code=500)

@router.get("/monthly")
async def coach_monthly():
    """月次コーチング"""
    try:
        result = await monthly_coaching()
        return result
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=500)
