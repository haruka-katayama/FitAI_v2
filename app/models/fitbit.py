from pydantic import BaseModel
from typing import Optional

class FitbitDayData(BaseModel):
    date: str
    steps_total: str
    sleep_line: str
    spo2_line: str
    calories_total: str

class FitbitSummary(BaseModel):
    steps_sum: int
    calories_sum: int
    count: int
