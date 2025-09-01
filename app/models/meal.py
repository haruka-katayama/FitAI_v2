from pydantic import BaseModel
from typing import Optional

class MealIn(BaseModel):
    when: str                 # "2025-08-10T12:30" など
    text: str
    kcal: Optional[float] = None
    meal_kind: Optional[str] = None     # 朝食/昼食/夕食 など
    image_digest: Optional[str] = None  # 画像内容のダイジェストなど
    notes: Optional[str] = None         # 補足メモ
    
    # Pydantic v2 対応
    def dict(self):
        """Pydantic v1互換のdict()メソッド"""
        return self.model_dump()


class MealUpdate(BaseModel):
    kcal: Optional[float] = None

    def dict(self):
        return self.model_dump()
