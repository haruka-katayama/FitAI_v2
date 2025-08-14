from fastapi import APIRouter

router = APIRouter()

@router.get("/")
def health():
    """ヘルスチェックエンドポイント"""
    return {"ok": True, "service": "fitline-fastapi", "version": "2.0.0"}
