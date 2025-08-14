from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.services.coaching_service import daily_coaching

router = APIRouter(tags=["cron"])

@router.get("/daily")
async def cron_daily():
    """日次バッチ処理（クーロン用）"""
    try:
        result = await daily_coaching()
        return result
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=500)
