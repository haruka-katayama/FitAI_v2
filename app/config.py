import os
from typing import Optional

class Settings:
    # BigQuery
    BQ_PROJECT_ID: str = os.getenv("BQ_PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    BQ_DATASET: str = os.getenv("BQ_DATASET", "health_raw")
    BQ_TABLE_MEALS: str = os.getenv("BQ_TABLE_MEALS", "meals")
    BQ_TABLE_FITBIT: str = os.getenv("BQ_TABLE_FITBIT", "fitbit_daily")
    BQ_TABLE_MONTHLY: str = os.getenv("BQ_TABLE_MONTHLY", "monthly_reports")
    BQ_TABLE_PROFILES: str = os.getenv("BQ_TABLE_PROFILES", "profiles")
    BQ_LOCATION: str = os.getenv("HP_BQ_LOCATION", "asia-northeast1")
    
    # Health Planet
    HP_BQ_TABLE: str = os.getenv("HP_BQ_TABLE", "peak-empire-396108.health_raw.healthplanet_innerscan")
    HEALTHPLANET_CLIENT_ID: Optional[str] = os.getenv("HEALTHPLANET_CLIENT_ID")
    HEALTHPLANET_CLIENT_SECRET: Optional[str] = os.getenv("HEALTHPLANET_CLIENT_SECRET")
    HEALTHPLANET_SCOPE: str = os.getenv("HEALTHPLANET_SCOPE", "innerscan")
    HP_REDIRECT_URI: str = "https://www.healthplanet.jp/success.html"
    
    # LINE
    LINE_ACCESS_TOKEN: Optional[str] = os.getenv("LINE_ACCESS_TOKEN")
    LINE_USER_ID: Optional[str] = os.getenv("LINE_USER_ID")
    
    # OpenAI - デフォルトをgpt-4oに変更（Chat Completions APIで確実に動作する）
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    
    # Fitbit
    FITBIT_CLIENT_ID: Optional[str] = os.getenv("FITBIT_CLIENT_ID")
    FITBIT_CLIENT_SECRET: Optional[str] = os.getenv("FITBIT_CLIENT_SECRET")
    FITBIT_SCOPE: str = "activity heartrate sleep oxygen_saturation profile"
    
    # App
    RUN_BASE_URL: Optional[str] = os.getenv("RUN_BASE_URL")
    UI_API_TOKEN: str = os.getenv("UI_API_TOKEN", "")

settings = Settings()
