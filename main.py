# main.py - SPA対応版
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import os

# ルーターのインポート
from app.routers import (
    health, ui, fitbit, healthplanet, 
    weight, meals, coaching, cron, debug
)

app = FastAPI(
    title="FitLine API",
    description="Fitness tracking and coaching application with multi-device support",
    version="2.0.0"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静的ファイルの配信（フロントエンド用）
static_dir = Path("static")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

# APIルーター登録（パス順序重要）
app.include_router(health.router)
app.include_router(ui.router)
app.include_router(fitbit.router, prefix="/fitbit")
app.include_router(healthplanet.router)
app.include_router(weight.router)
app.include_router(meals.router, prefix="/meals")
app.include_router(coaching.router, prefix="/coach")
app.include_router(cron.router, prefix="/cron")
app.include_router(debug.router, prefix="/debug")

@app.get("/api/health")
def api_health():
    """APIヘルスチェック"""
    return {
        "message": "FitLine API v2.0",
        "services": ["fitbit", "healthplanet", "meals", "coaching"],
        "status": "healthy"
    }

# SPA用のルートエンドポイント
@app.get("/")
async def serve_spa():
    """SPAのメインページ"""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    
    # index.htmlが存在しない場合のフォールバック
    return {"message": "FitAI API is running. Please add static/index.html for the web app."}

# SPA用のキャッチオール ルート（最後に配置）
@app.get("/{full_path:path}")
async def serve_spa_routes(request: Request, full_path: str):
    """
    SPAのためのキャッチオールルート
    APIパス以外はすべてindex.htmlにリダイレクト
    """
    # APIパスの場合は404を返す
    api_paths = [
        "api/", "ui/", "fitbit/", "healthplanet/", "weight/", 
        "meals/", "coach/", "cron/", "debug/", "docs", "redoc", "openapi.json"
    ]
    
    if any(full_path.startswith(path) for path in api_paths):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    
    # 静的ファイルのリクエストの場合
    if full_path.startswith("static/"):
        raise HTTPException(status_code=404, detail="Static file not found")
    
    # SPAルートの場合はindex.htmlを返す
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    
    # フォールバック
    raise HTTPException(status_code=404, detail="Page not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)