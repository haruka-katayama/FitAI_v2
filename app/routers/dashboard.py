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
        # Health Planetからの体重データ - 最新の測定値のみ取得
        weight_query = f"""
        SELECT
            date,
            weight_kg
        FROM (
            SELECT
                DATE(measured_at) AS date,
                value AS weight_kg,
                ROW_NUMBER() OVER(PARTITION BY DATE(measured_at) ORDER BY measured_at DESC) AS rn
            FROM `{settings.HP_BQ_TABLE}`
            WHERE user_id = @user_id
              AND tag = '6021'  -- 体重
              AND DATE(measured_at) BETWEEN @start_date AND @end_date
        )
        WHERE rn = 1
        ORDER BY date ASC
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
    """BigQuery からダッシュボード用データを取得"""
    if not bq_client:
        return JSONResponse({"ok": False, "error": "BigQuery not configured"}, status_code=500)

    try:
        # カロリー収支と体重変化の取得 (重複データを集約)
        analysis_query = f"""
        SELECT
            date,
            SUM(take_in_calories) AS take_in_calories,
            SUM(consumption_calories) AS consumption_calories,
            AVG(weight_change_kg) AS weight_change_kg
        FROM `{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_CALORIE_DIFF}`
        WHERE user_id = @user_id
          AND date BETWEEN @start_date AND @end_date
        GROUP BY date
        ORDER BY date ASC
        """

        analysis_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ])

        analysis_job = bq_client.query(analysis_query, job_config=analysis_config)
        analysis_rows = list(analysis_job.result())

        analysis_by_date = {
            row.date.strftime("%Y-%m-%d"): {
                "take_in_calories": float(row.take_in_calories) if row.take_in_calories is not None else 0,
                "consumption_calories": float(row.consumption_calories) if row.consumption_calories is not None else 0,
                "weight_change_kg": float(row.weight_change_kg) if row.weight_change_kg is not None else 0,
            }
            for row in analysis_rows
        }

        # 体重データの取得 (1日1つの最新値のみ)
        weight_query = f"""
        SELECT
            date,
            weight_kg
        FROM (
            SELECT
                DATE(measured_at) AS date,
                value AS weight_kg,
                ROW_NUMBER() OVER(PARTITION BY DATE(measured_at) ORDER BY measured_at DESC) AS rn
            FROM `{settings.HP_BQ_TABLE}`
            WHERE user_id = @user_id
              AND tag = '6021'
              AND DATE(measured_at) BETWEEN @start_date AND @end_date
        )
        WHERE rn = 1
        ORDER BY date ASC
        """

        weight_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ])

        weight_job = bq_client.query(weight_query, job_config=weight_config)
        weight_rows = list(weight_job.result())

        weight_by_date = {
            row.date.strftime("%Y-%m-%d"): float(row.weight_kg)
            for row in weight_rows
        }

        # 期間内の全日付リストを作成
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        all_dates = []
        current = start_dt
        while current <= end_dt:
            all_dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

        # 日付ごとのデータ配列を作成
        take_in = []
        consumption = []
        weight_change = []
        weights = []

        for d in all_dates:
            analysis = analysis_by_date.get(d, {})
            take_in.append(analysis.get("take_in_calories", 0))
            consumption.append(analysis.get("consumption_calories", 0))
            weight_change.append(analysis.get("weight_change_kg", 0))
            weights.append(weight_by_date.get(d, 0))

        return {
            "ok": True,
            "data": {
                "dates": all_dates,
                "take_in_calories": take_in,
                "consumption_calories": consumption,
                "weight_change_kg": weight_change,
                "weight_kg": weights,
                "steps_total": [],
            },
        }

    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)