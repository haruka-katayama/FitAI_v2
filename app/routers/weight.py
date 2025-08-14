from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.services.weight_service import get_current_weight

router = APIRouter(prefix="/weight", tags=["weight"])

@router.get("/current")
async def current_weight(user_id: str = "demo", days: int = 1):
    """
    現在の体重を取得（Health Planet優先、なければ手入力値）
    
    Args:
        user_id: ユーザーID
        days: 検索対象日数（1=当日のみ）
    
    Returns:
        体重データと取得元情報
    """
    try:
        result = await get_current_weight(user_id, days)
        return result
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
