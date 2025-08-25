# main.py - SPA対応版（完全版）
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pathlib import Path
from datetime import datetime, timezone
import logging
import traceback
import os

# ルーターのインポート
from app.routers import (
    health, ui, fitbit, healthplanet,
    weight, meals, coaching, cron, debug, dashboard, integration
)

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        # 必要に応じてファイルハンドラーも追加
        # logging.FileHandler('/tmp/fitai.log')
    ]
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="FitLine API",
    description="Fitness tracking and coaching application with multi-device support",
    version="2.0.0",
    debug=os.getenv("DEBUG", "false").lower() == "true"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静的ファイルの配信（staticディレクトリが存在する場合）
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# グローバル例外ハンドラー
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """予期しないエラーのハンドリング"""
    logger.error(f"Unhandled exception: {exc}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "error": "Internal server error",
            "detail": str(exc) if app.debug else "An unexpected error occurred"
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """バリデーションエラーのハンドリング"""
    return JSONResponse(
        status_code=422,
        content={
            "ok": False,
            "error": "Validation error",
            "detail": exc.errors()
        }
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP例外のハンドリング"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "error": exc.detail,
            "status_code": exc.status_code
        }
    )

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
app.include_router(integration.router)
app.include_router(dashboard.router)  # ダッシュボード追加

@app.get("/api/health")
def api_health():
    """APIヘルスチェック"""
    return {
        "message": "FitLine API v2.0",
        "services": ["fitbit", "healthplanet", "meals", "coaching"],
        "status": "healthy"
    }

@app.get("/health")
async def enhanced_health_check():
    """強化されたヘルスチェック"""
    try:
        # 各サービスの簡易チェック
        from app.database.firestore import db
        from app.database.bigquery import bq_client
        
        checks = {
            "api": True,
            "firestore": False,
            "bigquery": False,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Firestore接続チェック
        try:
            db.collection("health_check").limit(1).get()
            checks["firestore"] = True
        except Exception as e:
            logger.warning(f"Firestore health check failed: {e}")
        
        # BigQuery接続チェック
        try:
            if bq_client:
                list(bq_client.query("SELECT 1").result())
                checks["bigquery"] = True
        except Exception as e:
            logger.warning(f"BigQuery health check failed: {e}")
        
        return {
            "status": "healthy" if all(checks.values()) else "degraded",
            "checks": checks,
            "version": "2.0.0"
        }
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "version": "2.0.0"
            }
        )

# SPA用のルートエンドポイント
@app.get("/")
async def serve_spa():
    """SPAのメインページ"""
    # 最初にstaticディレクトリのindex.htmlを確認
    static_index = static_dir / "index.html"
    if static_index.exists():
        return FileResponse(static_index)
    
    # 次にルートディレクトリのindex.htmlを確認
    root_index = Path("index.html")
    if root_index.exists():
        return FileResponse(root_index)
    
    # どちらも存在しない場合のフォールバック
    return {
        "message": "FitAI API is running", 
        "version": "2.0.0",
        "note": "Please add index.html or static/index.html for the web app.",
        "api_docs": "/docs",
        "health": "/health"
    }

# manifest.jsonとsw.jsの直接配信
@app.get("/manifest.json")
async def serve_manifest():
    """PWA マニフェスト"""
    manifest_path = static_dir / "manifest.json"
    if manifest_path.exists():
        return FileResponse(manifest_path, media_type="application/json")
    raise HTTPException(status_code=404, detail="Manifest not found")

@app.get("/sw.js")
async def serve_service_worker():
    """Service Worker"""
    sw_path = static_dir / "sw.js"
    if sw_path.exists():
        return FileResponse(sw_path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="Service Worker not found")

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
    
    # 静的ファイルのリクエストの場合（.js, .css, .png等）
    if "." in full_path and not full_path.endswith(".html"):
        # staticディレクトリから探す
        static_file = static_dir / full_path
        if static_file.exists():
            return FileResponse(static_file)
        raise HTTPException(status_code=404, detail="Static file not found")
    
    # SPAルートの場合はindex.htmlを返す
    static_index = static_dir / "index.html"
    if static_index.exists():
        return FileResponse(static_index)
    
    root_index = Path("index.html")
    if root_index.exists():
        return FileResponse(root_index)
    
    # フォールバック
    raise HTTPException(status_code=404, detail="Page not found")

# アプリケーション起動時の処理
@app.on_event("startup")
async def startup_event():
    """アプリケーション起動時の処理"""
    logger.info("FitAI API v2.0 starting up...")
    logger.info(f"Static directory exists: {static_dir.exists()}")
    if static_dir.exists():
        logger.info(f"Static files: {list(static_dir.glob('*'))}")
    logger.info("Startup complete")

@app.on_event("shutdown")
async def shutdown_event():
    """アプリケーション終了時の処理"""
    logger.info("FitAI API v2.0 shutting down...")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=port,
        log_level="info",
        access_log=True
    )
