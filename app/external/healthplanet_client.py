import httpx
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from app.config import settings
from app.database.firestore import healthplanet_token_doc

def get_access_token(user_id: str = "demo") -> Optional[str]:
    """Health Planetアクセストークンを取得"""
    snap = healthplanet_token_doc(user_id).get()
    if not snap.exists:
        return None
    return (snap.to_dict() or {}).get("access_token")

def jst_now() -> datetime:
    """JST現在時刻を返す"""
    return datetime.now(timezone.utc) + timedelta(hours=9)

def format_datetime(dt: datetime) -> str:
    """Health Planet API用の日時フォーマット（yyyymmddHHMMSS）"""
    return dt.strftime("%Y%m%d%H%M%S")

def is_env_configured() -> bool:
    """環境変数が設定されているかチェック"""
    return bool(settings.HEALTHPLANET_CLIENT_ID and settings.HEALTHPLANET_CLIENT_SECRET)

def get_oauth_url() -> str:
    """OAuth認証URLを生成"""
    if not is_env_configured():
        raise ValueError("Health Planet credentials not configured")
    
    params = {
        "client_id": settings.HEALTHPLANET_CLIENT_ID,
        "redirect_uri": settings.HP_REDIRECT_URI,
        "scope": settings.HEALTHPLANET_SCOPE,
        "response_type": "code",
    }
    return "https://www.healthplanet.jp/oauth/auth?" + urllib.parse.urlencode(params)

async def exchange_code_for_token(code: str) -> Dict[str, Any]:
    """認証コードをアクセストークンに交換"""
    if not is_env_configured():
        raise ValueError("Health Planet credentials not configured")
    
    data = {
        "client_id": settings.HEALTHPLANET_CLIENT_ID,
        "client_secret": settings.HEALTHPLANET_CLIENT_SECRET,
        "redirect_uri": settings.HP_REDIRECT_URI,
        "code": code,
        "grant_type": "authorization_code",
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post("https://www.healthplanet.jp/oauth/token", data=data)
        r.raise_for_status()
        return r.json()

async def fetch_innerscan_data(
    user_id: str = "demo",
    date: int = 1,
    tag: str = "6021,6022",
    from_dt: Optional[str] = None,
    to_dt: Optional[str] = None
) -> Dict[str, Any]:
    """体組成データを取得"""
    access = get_access_token(user_id)
    if not access:
        raise ValueError("Health Planet not connected")
    
    params = {"access_token": access, "date": str(date), "tag": tag}
    if from_dt:
        params["from"] = from_dt
    if to_dt:
        params["to"] = to_dt
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get("https://www.healthplanet.jp/status/innerscan.json", params=params)
        r.raise_for_status()
        return r.json()
