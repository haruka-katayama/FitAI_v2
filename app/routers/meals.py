from fastapi import APIRouter
from app.services.meal_service import meals_last_n_days

router = APIRouter(tags=["meals"])

@router.get("/last7")
async def meals_last7():
    """過去7日間の食事記録取得"""
    return await meals_last_n_days(7, "demo")
