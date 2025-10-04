from fastapi import APIRouter
from app.database.firestore import fitbit_token_doc, healthplanet_token_doc

router = APIRouter(prefix="/integration", tags=["integration"])


def _doc_exists(doc_ref) -> bool:
    """Safely determine whether a Firestore document exists."""
    try:
        if doc_ref is None:
            return False
        snapshot = doc_ref.get()
        return bool(getattr(snapshot, "exists", False))
    except Exception:
        return False


@router.get("/status")
def integration_status(user_id: str = "demo"):
    """Return integration status for Fitbit and Health Planet."""
    try:
        fitbit_doc = fitbit_token_doc(user_id)
    except Exception:
        fitbit_doc = None

    try:
        healthplanet_doc = healthplanet_token_doc(user_id)
    except Exception:
        healthplanet_doc = None

    fitbit = _doc_exists(fitbit_doc)
    healthplanet = _doc_exists(healthplanet_doc)

    return {"fitbit": {"linked": fitbit}, "healthplanet": {"linked": healthplanet}}
