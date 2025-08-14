from google.cloud import firestore
from typing import Dict, Any

db = firestore.Client()

def user_doc(user_id: str = "demo"):
    """ユーザードキュメントの参照を返す"""
    return db.collection("users").document(user_id)

def get_latest_profile(user_id: str = "demo") -> Dict[str, Any]:
    """最新プロフィールを取得"""
    snap = user_doc(user_id).collection("profile").document("latest").get()
    return snap.to_dict() if snap.exists else {}

def fitbit_token_doc(user_id: str = "demo"):
    """Fitbitトークンドキュメントの参照を返す"""
    return user_doc(user_id).collection("private").document("fitbit_oauth")

def healthplanet_token_doc(user_id: str = "demo"):
    """Health Planetトークンドキュメントの参照を返す"""
    return user_doc(user_id).collection("private").document("healthplanet_oauth")
