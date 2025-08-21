from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from google.api_core.exceptions import BadRequest
from google.cloud import bigquery
from app.database.bigquery import bq_client
from app.config import settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _run_bq_with_fallback(
    primary_sql: str,
    fallback_sql: Optional[str],
    params: List[bigquery.ScalarQueryParameter],
):
    """
    BigQueryを実行。primary_sql が列不存在などで失敗したら fallback_sql を試す。
    fallback_sql が None の場合は例外をそのまま投げる。
    """
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    try:
        return list(bq_client.query(primary_sql, job_config=job_config).result())

    except BadRequest as e:
        # BadRequest では e.errors から詳細メッセージを抽出してスキーマ差異のみフォールバック
        messages = " ".join(err.get("message", "").lower() for err in getattr(e, "errors", []) or [])
        if fallback_sql and (
            "unrecognized name" in messages or "no such field" in messages
        ):
            job_config_fb = bigquery.QueryJobConfig(query_parameters=params)
            return list(bq_client.query(fallback_sql, job_config=job_config_fb).result())
        raise

    except Exception as e:
        # その他の例外は文字列メッセージで簡易判定してスキーマ差異のみフォールバック
        message = str(e).lower()
        if fallback_sql and (
            "unrecognized name" in message or "no such field" in message
        ):
            job_config_fb = bigquery.QueryJobConfig(query_parameters=params)
            return list(bq_client.query(fallback_sql, job_config=job_config_fb).result())
        raise


@router.get("/fitbit")
async def get_fitbit_dashboard_data(
    start_date: str = Query(..., description="開始日 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="終了日 (YYYY-MM-DD)"),
    user_id: str = Query("demo", description="ユーザーID"),
):
    """Fitbitダッシュボード用データを取得"""
    if not bq_client:
        return JSONResponse({"ok": False, "error": "BigQuery not configured"}, status_code=500)

    try:
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

        params = [
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]

        rows = _run_bq_with_fallback(fitbit_query, None, params)

        data = {"dates": [], "steps_total": [], "calories_total": [], "sleep_data": [], "spo2_data": []}
        for row in rows:
            data["dates"].append(row.date.strftime("%Y-%m-%d"))
            data["steps_total"].append(int(row.steps_total) if row.steps_total is not None else 0)
            data["calories_total"].append(int(row.calories_total) if row.calories_total is not None else 0)
            data["sleep_data"].append(row.sleep_line or "データなし")
            data["spo2_data"].append(row.spo2_line or "データなし")

        return {"ok": True, "data": data}

    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/meals")
async def get_meals_dashboard_data(
    start_date: str = Query(..., description="開始日 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="終了日 (YYYY-MM-DD)"),
    user_id: str = Query("demo", description="ユーザーID"),
):
    """食事ダッシュボード用データを取得"""
    if not bq_client:
        return JSONResponse({"ok": False, "error": "BigQuery not configured"}, status_code=500)

    try:
        meals_query = f"""
        SELECT
            when_date,
            image_base64,
            kcal
        FROM `{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_MEALS_DASHBOARD}`
        WHERE user_id = @user_id
          AND when_date BETWEEN @start_date AND @end_date
        ORDER BY when_date DESC
        """

        params = [
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]

        results = _run_bq_with_fallback(meals_query, None, params)

        meals_by_date: Dict[str, List[Dict[str, Any]]] = {}
        daily_calories: Dict[str, float] = {}

        for row in results:
            date_obj = row.when_date  # DATE
            date_str = date_obj.strftime("%Y-%m-%d")
            meal_data = {
                "image_base64": getattr(row, "image_base64", None),
                "kcal": float(row.kcal) if row.kcal is not None else None,
            }

            if date_str not in meals_by_date:
                meals_by_date[date_str] = []
                daily_calories[date_str] = 0.0

            meals_by_date[date_str].append(meal_data)

            # 0kcal も正しく集計（None のみ無視）
            if meal_data["kcal"] is not None:
                daily_calories[date_str] += meal_data["kcal"]

        # 期間の全日付を網羅
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

        dates: List[str] = []
        take_in_calories: List[float] = []
        cur = start_dt
        while cur <= end_dt:
            ds = cur.strftime("%Y-%m-%d")
            dates.append(ds)
            take_in_calories.append(daily_calories.get(ds, 0.0))
            cur += timedelta(days=1)

        return {
            "ok": True,
            "data": {
                "dates": dates,
                "take_in_calories": take_in_calories,
                "meals_by_date": meals_by_date,
            },
        }

    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/weight")
async def get_weight_dashboard_data(
    start_date: str = Query(..., description="開始日 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="終了日 (YYYY-MM-DD)"),
    user_id: str = Query("demo", description="ユーザーID"),
):
    """体重ダッシュボード用データを取得"""
    if not bq_client:
        return JSONResponse({"ok": False, "error": "BigQuery not configured"}, status_code=500)

    try:
        weight_query = f"""
        SELECT
            date,
            weight AS weight_kg,
            fat_percentage
        FROM (
            SELECT
                DATE(measured_at) AS date,
                weight,
                fat_percentage,
                ROW_NUMBER() OVER(PARTITION BY DATE(measured_at) ORDER BY measured_at DESC) AS rn
            FROM `{settings.HP_BQ_TABLE}`
            WHERE user_id = @user_id
              AND DATE(measured_at) BETWEEN @start_date AND @end_date
        )
        WHERE rn = 1
        ORDER BY date ASC
        """

        params = [
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]

        results = _run_bq_with_fallback(weight_query, None, params)

        dates: List[str] = []
        weights: List[Optional[float]] = []
        fats: List[Optional[float]] = []

        for row in results:
            dates.append(row.date.strftime("%Y-%m-%d"))
            weights.append(float(row.weight_kg) if row.weight_kg is not None else None)
            fats.append(float(row.fat_percentage) if row.fat_percentage is not None else None)

        return {"ok": True, "data": {"dates": dates, "weight_kg": weights, "fat_percentage": fats}}

    except Exception:
        # データが無い場合は空を返す
        return {"ok": True, "data": {"dates": [], "weight_kg": [], "fat_percentage": []}}


@router.get("/summary")
async def get_dashboard_summary(
    start_date: str = Query(..., description="開始日 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="終了日 (YYYY-MM-DD)"),
    user_id: str = Query("demo", description="ユーザーID"),
):
    """BigQuery からダッシュボード用サマリデータを取得"""
    if not bq_client:
        return JSONResponse({"ok": False, "error": "BigQuery not configured"}, status_code=500)

    try:
        # カロリー収支 & 体重変化（重複を日付で集約）
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
        params_common = [
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
        analysis_rows = _run_bq_with_fallback(analysis_query, None, params_common)

        analysis_by_date = {
            row.date.strftime("%Y-%m-%d"): {
                "take_in_calories": float(row.take_in_calories) if row.take_in_calories is not None else 0.0,
                "consumption_calories": float(row.consumption_calories) if row.consumption_calories is not None else 0.0,
                "weight_change_kg": float(row.weight_change_kg) if row.weight_change_kg is not None else 0.0,
            }
            for row in analysis_rows
        }

        # 体重・体脂肪（1日1件、最新）
        weight_query = f"""
        SELECT
            date,
            weight AS weight_kg,
            fat_percentage
        FROM (
            SELECT
                DATE(measured_at) AS date,
                weight,
                fat_percentage,
                ROW_NUMBER() OVER(PARTITION BY DATE(measured_at) ORDER BY measured_at DESC) AS rn
            FROM `{settings.HP_BQ_TABLE}`
            WHERE user_id = @user_id
              AND DATE(measured_at) BETWEEN @start_date AND @end_date
        )
        WHERE rn = 1
        ORDER BY date ASC
        """
        weight_rows = _run_bq_with_fallback(weight_query, None, params_common)

        weight_by_date = {
            row.date.strftime("%Y-%m-%d"): float(row.weight_kg) if row.weight_kg is not None else None
            for row in weight_rows
        }
        fat_by_date = {
            row.date.strftime("%Y-%m-%d"): float(row.fat_percentage) if row.fat_percentage is not None else None
            for row in weight_rows
        }

        # 歩数
        steps_query = f"""
        SELECT
            date,
            steps_total
        FROM `{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_FITBIT}`
        WHERE user_id = @user_id
          AND date BETWEEN @start_date AND @end_date
        ORDER BY date ASC
        """
        steps_rows = _run_bq_with_fallback(steps_query, None, params_common)
        steps_by_date = {
            row.date.strftime("%Y-%m-%d"): int(row.steps_total) if row.steps_total is not None else 0
            for row in steps_rows
        }

        meals_query = f"""
        SELECT
            when_date,
            image_base64,
            kcal
        FROM `{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_MEALS_DASHBOARD}`
        WHERE user_id = @user_id
          AND when_date BETWEEN @start_date AND @end_date
        ORDER BY when_date DESC, `when` DESC
        """
        meals_rows = _run_bq_with_fallback(meals_query, None, params_common)

        meals_by_date: Dict[str, List[Dict[str, Any]]] = {}
        for row in meals_rows:
            ds = row.when_date.strftime("%Y-%m-%d")
            meals_by_date.setdefault(ds, []).append(
                {
                    "image_base64": getattr(row, "image_base64", None),
                    "kcal": float(row.kcal) if row.kcal is not None else None,
                }
            )

        # 期間内の全日付リスト
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        all_dates: List[str] = []
        cur = start_dt
        while cur <= end_dt:
            all_dates.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)

        # 日別配列を整形
        take_in = []
        consumption = []
        weight_change = []
        weights = []
        fats = []
        steps = []

        for d in all_dates:
            a = analysis_by_date.get(d, {})
            take_in.append(a.get("take_in_calories", 0.0))
            consumption.append(a.get("consumption_calories", 0.0))
            weight_change.append(a.get("weight_change_kg", 0.0))
            weights.append(weight_by_date.get(d, None))
            fats.append(fat_by_date.get(d, None))
            steps.append(steps_by_date.get(d, 0))

        return {
            "ok": True,
            "data": {
                "dates": all_dates,
                "take_in_calories": take_in,
                "consumption_calories": consumption,
                "weight_change_kg": weight_change,
                "weight_kg": weights,
                "fat_percentage": fats,
                "steps_total": steps,
                "meals_by_date": meals_by_date,
            },
        }

    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
