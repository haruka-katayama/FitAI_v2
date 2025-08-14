from pydantic import BaseModel
from typing import Optional, List, Literal

class ProfileIn(BaseModel):
    age: Optional[int] = None
    sex: Optional[Literal["male", "female", "other"]] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None           # 現体重
    target_weight_kg: Optional[float] = None    # 目標体重
    goal: Optional[str] = None                  # 運動目的
    notes: Optional[str] = None                 # 任意
    smoking_status: Optional[Literal["never", "former", "current"]] = None  # 喫煙状況
    alcohol_habit: Optional[Literal["none", "social", "moderate", "heavy"]] = None  # 飲酒習慣
    past_history: Optional[List[Literal[
        "hypertension", "diabetes", "cad", "stroke", "dyslipidemia", "kidney", "liver", "asthma", "other"
    ]]] = None  # 既往歴
    medications: Optional[str] = None  # 現在の服薬
    allergies: Optional[str] = None    # アレルギー
    
    # Pydantic v2 対応
    def dict(self):
        """Pydantic v1互換のdict()メソッド"""
        return self.model_dump()
