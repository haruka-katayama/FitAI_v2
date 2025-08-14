from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class HealthPlanetData(BaseModel):
    measured_at: str
    weight_kg: Optional[float] = None
    body_fat_pct: Optional[float] = None

class HealthPlanetPromptResponse(BaseModel):
    ok: bool
    prompt_snippet: str
    rows: List[HealthPlanetData]
