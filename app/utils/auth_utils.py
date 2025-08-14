from fastapi import HTTPException
from app.config import settings

def require_token(x_api_token: str | None):
    """API トークン認証（開発時はバイパス）"""
    # 開発時はトークンチェックをスキップ
    if not settings.UI_API_TOKEN:
        return
    
    if x_api_token != settings.UI_API_TOKEN:
        raise HTTPException(status_code=401, detail="invalid api token")
