from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from app.external.healthplanet_client import fetch_innerscan_data, get_access_token, jst_now, format_datetime
from app.database.firestore import user_doc

def get_manual_weight(user_id: str = "demo") -> Optional[Dict[str, Any]]:
    """Firestoreから手入力体重を取得"""
    doc = (
        user_doc(user_id)
        .collection("profile")
        .document("latest")
        .get()
    )
    if not doc.exists:
        return None
    
    data = doc.to_dict() or {}
    weight = data.get("weight_kg")
    if weight is None:
        return None
    
    return {
        "weight_kg": float(weight),
        "updated_at": data.get("updated_at", jst_now().isoformat()),
    }

def pick_latest_weight_from_hp_data(raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Health PlanetのAPIレスポンスから最新の体重データを抽出"""
    latest = None
    for item in raw_data.get("data", []):
        if item.get("tag") != "6021":  # 体重のタグ
            continue
        
        timestamp = item.get("date")  # yyyymmddHHMMSS
        weight = item.get("keydata")
        
        if not timestamp or weight in (None, ""):
            continue
        
        if (latest is None) or (timestamp > latest["date"]):
            latest = {"date": timestamp, "weight_kg": float(weight)}
    
    return latest

async def get_current_weight(user_id: str = "demo", days: int = 1) -> Dict[str, Any]:
    """
    現在の体重を取得（Health Planet優先、なければ手入力値）
    
    Returns:
        {
            "value_kg": float | None,
            "source": "healthplanet" | "manual" | "none",
            "hp": {"found": bool, "date": str, "weight_kg": float},
            "manual": {"found": bool, "weight_kg": float, "updated_at": str}
        }
    """
    # Health Planetから直近のデータを取得
    hp_found = False
    hp_payload = {"found": False}
    
    try:
        access = get_access_token(user_id)
        if access:
            today = jst_now().date()
            start = datetime(today.year, today.month, today.day, 0, 0, 0) - timedelta(days=days-1)
            end = datetime(today.year, today.month, today.day, 23, 59, 59)
            
            raw_data = await fetch_innerscan_data(
                user_id=user_id,
                date=1,  # 測定日付
                tag="6021",  # 体重
                from_dt=format_datetime(start),
                to_dt=format_datetime(end)
            )
            
            latest = pick_latest_weight_from_hp_data(raw_data)
            if latest:
                hp_found = True
                hp_payload = {
                    "found": True,
                    "date": latest["date"][:8],  # YYYYMMDD
                    "weight_kg": latest["weight_kg"],
                }
    except Exception:
        pass
    
    # 手入力データを取得
    manual = get_manual_weight(user_id)
    manual_payload = {"found": bool(manual), **(manual or {})}
    
    # 優先ロジック：Health Planetがあれば優先、なければ手入力
    if hp_found:
        return {
            "value_kg": hp_payload["weight_kg"],
            "source": "healthplanet",
            "hp": hp_payload,
            "manual": manual_payload,
        }
    
    if manual:
        return {
            "value_kg": manual["weight_kg"],
            "source": "manual",
            "hp": hp_payload,
            "manual": manual_payload,
        }
    
    return {
        "value_kg": None,
        "source": "none",
        "hp": hp_payload,
        "manual": manual_payload,
    }
