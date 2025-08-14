import asyncio
import base64
import httpx
from datetime import datetime, timezone, timedelta
from app.config import settings
from app.database.firestore import fitbit_token_doc

FITBIT_TOKEN_LOCK = asyncio.Lock()

def get_redirect_uri() -> str:
    """Fitbit OAuth リダイレクトURIを生成"""
    return f"{settings.RUN_BASE_URL.rstrip('/')}/fitbit/auth" if settings.RUN_BASE_URL else ""

async def fitbit_exchange_code(code: str) -> dict:
    """認証コードをアクセストークンに交換"""
    auth = base64.b64encode(f"{settings.FITBIT_CLIENT_ID}:{settings.FITBIT_CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}", 
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "clientId": settings.FITBIT_CLIENT_ID, 
        "grant_type": "authorization_code", 
        "redirect_uri": get_redirect_uri(), 
        "code": code
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post("https://api.fitbit.com/oauth2/token", headers=headers, data=data)
        r.raise_for_status()
        return r.json()

async def fitbit_refresh(refresh_token: str) -> dict:
    """リフレッシュトークンで新しいアクセストークンを取得"""
    auth = base64.b64encode(f"{settings.FITBIT_CLIENT_ID}:{settings.FITBIT_CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}", 
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post("https://api.fitbit.com/oauth2/token", headers=headers, data=data)
        r.raise_for_status()
        return r.json()

async def get_fitbit_access_token(user_id: str = "demo") -> str:
    """Fitbit アクセストークンを返す。期限が近ければ1回だけリフレッシュする（ロック付き）"""
    doc = fitbit_token_doc(user_id)

    def _now_ts() -> int:
        return int(datetime.now(timezone.utc).timestamp())

    snap = doc.get()
    if not snap.exists:
        raise RuntimeError("Fitbit not connected. Open /fitbit/login first.")
    
    tok = snap.to_dict()
    if tok.get("expires_at", 0) > _now_ts() + 120:
        return tok["access_token"]

    async with FITBIT_TOKEN_LOCK:
        snap = doc.get()
        tok = snap.to_dict()
        if tok.get("expires_at", 0) > _now_ts() + 120:
            return tok["access_token"]

        newtok = await fitbit_refresh(tok["refresh_token"])
        expires_at = _now_ts() + int(newtok.get("expires_in", 3600))
        doc.set({
            "access_token": newtok["access_token"],
            "refresh_token": newtok.get("refresh_token", tok["refresh_token"]),
            "token_type": newtok.get("token_type", "Bearer"),
            "scope": newtok.get("scope", tok.get("scope")),
            "user_id": tok.get("user_id"),
            "expires_at": expires_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, merge=True)
        return newtok["access_token"]

async def fitbit_get(access_token: str, url: str) -> dict:
    """FitbitのAPIにGETリクエストを送信"""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()
