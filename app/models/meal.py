from pydantic import BaseModel
from typing import Optional

class MealIn(BaseModel):
    when: str                 # "2025-08-10T12:30" など
    text: str
    kcal: Optional[float] = None
    
    # Pydantic v2 対応
    def dict(self):
        """Pydantic v1互換のdict()メソッド"""
        return self.model_dump()
