from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from google.cloud import bigquery
from app.database.bigquery import bq_client
from app.config import settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/fitbit")
async def get_fitbit_dashboard_data(
    start_date: str = Query(..., description="開始日 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="終了日 (YYYY-MM-DD)"),
    user_id: str = Query("demo", description="ユーザーID")
):
    """Fitbitダッシュボード用データを取得"""
    if not bq_client:
        return JSONResponse({"ok": False, "error": "BigQuery not configured"}, status_code=500)
    
    try:
        # Fitbitデータクエリ
        fitbit_query = f"""
        SELECT 
            date,
            steps_total,
            calories_total,
            sleep_line,
            spo2_line
        FROM `{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_FITBIT}`
        WHERE user_id = @user_id
          AND date BETWEEN @start_date AND @end_date
        ORDER BY date ASC
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )
        
        query_job = bq_client.query(fitbit_query, job_config=job_config)
        results = list(query_job.result())
        
        # データを整形
        data = {
            "dates": [],
            "steps_total": [],
            "calories_total": [],
            "sleep_data": [],
            "spo2_data": []
        }
        
        for row in results:
            data["dates"].append(row.date.strftime("%Y-%m-%d"))
            data["steps_total"].append(int(row.steps_total) if row.steps_total else 0)
            data["calories_total"].append(int(row.calories_total) if row.calories_total else 0)
            data["sleep_data"].append(row.sleep_line or "データなし")
            data["spo2_data"].append(row.spo2_line or "データなし")
        
        return {"ok": True, "data": data}
        
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.get("/meals")
async def get_meals_dashboard_data(
    start_date: str = Query(..., description="開始日 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="終了日 (YYYY-MM-DD)"),
    user_id: str = Query("demo", description="ユーザーID")
):
    """食事ダッシュボード用データを取得"""
    if not bq_client:
        return JSONResponse({"ok": False, "error": "BigQuery not configured"}, status_code=500)
    
    try:
        # 食事データクエリ
        meals_query = f"""
        SELECT 
            when_date,
            text,
            kcal,
            source
        FROM `{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_MEALS}`
        WHERE user_id = @user_id
          AND when_date BETWEEN @start_date AND @end_date
        ORDER BY when_date ASC, when ASC
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )
        
        query_job = bq_client.query(meals_query, job_config=job_config)
        results = list(query_job.result())
        
        # 日付別にグループ化
        meals_by_date: Dict[str, List[Dict[str, Any]]] = {}
        daily_calories: Dict[str, float] = {}
        
        for row in results:
            date_str = row.when_date.strftime("%Y-%m-%d")
            
            if date_str not in meals_by_date:
                meals_by_date[date_str] = []
                daily_calories[date_str] = 0
            
            meal_data = {
                "text": row.text,
                "kcal": float(row.kcal) if row.kcal else None,
                "source": row.source
            }
            
            meals_by_date[date_str].append(meal_data)
            
            if row.kcal:
                daily_calories[date_str] += float(row.kcal)
        
        # 期間内の全日付でカロリーデータを準備
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        dates = []
        take_in_calories = []
        
        current_date = start_dt
        while current_date <= end_dt:
            date_str = current_date.strftime("%Y-%m-%d")
            dates.append(date_str)
            take_in_calories.append(daily_calories.get(date_str, 0))
            current_date += timedelta(days=1)
        
        return {
            "ok": True,
            "data": {
                "dates": dates,
                "take_in_calories": take_in_calories,
                "meals_by_date": meals_by_date
            }
        }
        
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.get("/weight")
async def get_weight_dashboard_data(
    start_date: str = Query(..., description="開始日 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="終了日 (YYYY-MM-DD)"),
    user_id: str = Query("demo", description="ユーザーID")
):
    """体重ダッシュボード用データを取得"""
    if not bq_client:
        return JSONResponse({"ok": False, "error": "BigQuery not configured"}, status_code=500)
    
    try:
        # Health Planetからの体重データ
        weight_query = f"""
        SELECT 
            DATE(measured_at) as date,
            value as weight_kg
        FROM `{settings.HP_BQ_TABLE}`
        WHERE user_id = @user_id
          AND tag = '6021'  -- 体重
          AND DATE(measured_at) BETWEEN @start_date AND @end_date
        ORDER BY measured_at ASC
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )
        
        query_job = bq_client.query(weight_query, job_config=job_config)
        results = list(query_job.result())
        
        # データを整形
        dates = []
        weights = []
        
        for row in results:
            dates.append(row.date.strftime("%Y-%m-%d"))
            weights.append(float(row.weight_kg))
        
        return {
            "ok": True,
            "data": {
                "dates": dates,
                "weight_kg": weights
            }
        }
        
    except Exception as e:
        # Health Planetデータがない場合は空のデータを返す
        return {
            "ok": True,
            "data": {
                "dates": [],
                "weight_kg": []
            }
        }

@router.get("/summary")
async def get_dashboard_summary(
    start_date: str = Query(..., description="開始日 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="終了日 (YYYY-MM-DD)"),
    user_id: str = Query("demo", description="ユーザーID")
):
    """ダッシュボード統合データを取得"""
    try:
        # 各エンドポイントからデータを取得
        fitbit_response = await get_fitbit_dashboard_data(start_date, end_date, user_id)
        meals_response = await get_meals_dashboard_data(start_date, end_date, user_id)
        weight_response = await get_weight_dashboard_data(start_date, end_date, user_id)
        
        # レスポンスが JSONResponse の場合はエラー
        if isinstance(fitbit_response, JSONResponse) or isinstance(meals_response, JSONResponse) or isinstance(weight_response, JSONResponse):
            return JSONResponse({"ok": False, "error": "Failed to fetch some data"}, status_code=500)
        
        if not all([fitbit_response.get("ok"), meals_response.get("ok"), weight_response.get("ok")]):
            return JSONResponse({"ok": False, "error": "Failed to fetch some data"}, status_code=500)
        
        # 統合データの作成
        fitbit = fitbit_response["data"]
        meals = meals_response["data"]
        weight = weight_response["data"]
        
        # 期間内の全日付を作成
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        all_dates = []
        current_date = start_dt
        while current_date <= end_dt:
            all_dates.append(current_date.strftime("%Y-%m-%d"))
            current_date += timedelta(days=1)
        
        # データをマージ
        consumption_calories = []
        take_in_calories = []
        weight_changes = []
        weights = []
        
        # Fitbitデータをインデックス化
        fitbit_by_date = {date: {"steps": steps, "calories": cals} 
                         for date, steps, cals in zip(fitbit["dates"], fitbit["steps_total"], fitbit["calories_total"])}
        
        # 食事データをインデックス化
        meals_by_date = {date: cals for date, cals in zip(meals["dates"], meals["take_in_calories"])}
        
        # 体重データをインデックス化
        weight_by_date = {date: weight_val for date, weight_val in zip(weight["dates"], weight["weight_kg"])}
        
        previous_weight = None
        last_known_weight = None
        
        for date in all_dates:
            # 消費カロリー
            consumption_calories.append(fitbit_by_date.get(date, {}).get("calories", 0))
            
            # 摂取カロリー
            take_in_calories.append(meals_by_date.get(date, 0))
            
            # 体重処理
            if date in weight_by_date:
                current_weight = weight_by_date[date]
                last_known_weight = current_weight
            else:
                current_weight = last_known_weight  # 最後に知られている体重を使用
            
            weights.append(current_weight if current_weight is not None else 0)
            
            # 体重変化計算
            if previous_weight is not None and current_weight is not None:
                weight_changes.append(current_weight - previous_weight)
            else:
                weight_changes.append(0)
            
            if current_weight is not None:
                previous_weight = current_weight
        
        return {
            "ok": True,
            "data": {
                "dates": all_dates,
                "consumption_calories": consumption_calories,
                "take_in_calories": take_in_calories,
                "weight_change_kg": weight_changes,
                "weight_kg": weights,
                "steps_total": [fitbit_by_date.get(date, {}).get("steps", 0) for date in all_dates]
            }
        }
        
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
