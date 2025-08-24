from google.cloud import firestore
from google.auth.exceptions import DefaultCredentialsError
from typing import Dict, Any, Optional

try:
    db = firestore.Client()
except DefaultCredentialsError:
    db = None

def user_doc(user_id: str = "demo"):
    """ユーザードキュメントの参照を返す"""
    if not db:
        raise RuntimeError("Firestore client is not configured")
    return db.collection("users").document(user_id)

def get_latest_profile(user_id: str = "demo") -> Dict[str, Any]:
    """最新プロフィールを取得"""
    if not db:
        return {}
    snap = user_doc(user_id).collection("profile").document("latest").get()
    return snap.to_dict() if snap.exists else {}

def fitbit_token_doc(user_id: str = "demo"):
    """Fitbitトークンドキュメントの参照を返す"""
    if not db:
        raise RuntimeError("Firestore client is not configured")
    return user_doc(user_id).collection("private").document("fitbit_oauth")

def healthplanet_token_doc(user_id: str = "demo"):
    """Health Planetトークンドキュメントの参照を返す"""
    if not db:
        raise RuntimeError("Firestore client is not configured")
    return user_doc(user_id).collection("private").document("healthplanet_oauth")


def _coach_settings_doc(user_id: str = "demo"):
    """コーチ設定ドキュメントの参照を返す"""
    if not db:
        raise RuntimeError("Firestore client is not configured")
    return user_doc(user_id).collection("private").document("settings")


def get_coach_character(user_id: str = "demo") -> Optional[str]:
    """選択中のコーチキャラクターを取得"""
    if not db:
        return None
    snap = _coach_settings_doc(user_id).get()
    if snap.exists:
        data = snap.to_dict() or {}
        return data.get("coach_character")
    return None


def set_coach_character(character: str, user_id: str = "demo") -> None:
    """コーチキャラクターを保存"""
    if not db:
        return
    _coach_settings_doc(user_id).set({"coach_character": character}, merge=True)
