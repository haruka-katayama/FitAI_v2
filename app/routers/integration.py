from fastapi import APIRouter
from app.database.firestore import fitbit_token_doc, healthplanet_token_doc

router = APIRouter(prefix="/integration", tags=["integration"])


@router.get("/status")
def integration_status(user_id: str = "demo"):
    """Return integration status for Fitbit and Health Planet."""
    if user_id == "demo":
        return {"fitbit": {"linked": True}, "healthplanet": {"linked": True}}

    fitbit = False
    healthplanet = False
    try:
        fitbit = fitbit_token_doc(user_id).get().exists
    except Exception:
        pass
    try:
        healthplanet = healthplanet_token_doc(user_id).get().exists
    except Exception:
        pass

    return {"fitbit": {"linked": fitbit}, "healthplanet": {"linked": healthplanet}}
