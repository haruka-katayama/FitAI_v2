from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from app.external.fitbit_client import get_fitbit_access_token, fitbit_get
from app.database.firestore import user_doc
from app.database.bigquery import bq_upsert_fitbit_days

async def fitbit_day_core(date_str: str, access_token: str) -> Dict[str, Any]:
    """指定日のFitbitデータを取得"""
    base = "https://api.fitbit.com"

    steps_json = await fitbit_get(access_token, f"{base}/1/user/-/activities/steps/date/{date_str}/1d.json")
    steps_total = (steps_json.get("activities-steps", [{}]) or [{}])[0].get("value", "0")

    sleep_json = await fitbit_get(access_token, f"{base}/1.2/user/-/sleep/date/{date_str}.json")
    sleep_line = "データなし"
    if "summary" in sleep_json:
        s = sleep_json["summary"]
        total = s.get("totalMinutesAsleep")
        st = s.get("stages", {})
        sleep_line = f"総睡眠{total}分 (深:{st.get('deep')} / レム:{st.get('rem')} / 浅:{st.get('light')} / 覚醒:{st.get('wake')})"
    elif "sleep" in sleep_json:
        total = sum([x.get("minutesAsleep", 0) for x in sleep_json.get("sleep", [])])
        sleep_line = f"総睡眠{total}分"

    spo2_line = "データなし"
    try:
        spo2_json = await fitbit_get(access_token, f"{base}/1/user/-/spo2/date/{date_str}.json")
        spo2_val = spo2_json.get("value", {}).get("avg")
        if spo2_val:
            spo2_line = f"平均{spo2_val}"
    except Exception:
        pass

    calorie_json = await fitbit_get(access_token, f"{base}/1/user/-/activities/calories/date/{date_str}/1d.json")
    calories_total = (calorie_json.get("activities-calories", [{}]) or [{}])[0].get("value", "0")

    return {"date": date_str, "steps_total": steps_total, "sleep_line": sleep_line,
            "spo2_line": spo2_line, "calories_total": calories_total}

async def fitbit_today_core() -> Dict[str, Any]:
    """今日のFitbitデータを取得"""
    token = await get_fitbit_access_token("demo")
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    return await fitbit_day_core(today, token)

async def fitbit_last_n_days(n: int = 7) -> List[Dict[str, Any]]:
    """直近n日のFitbitデータを取得"""
    local_today = datetime.now(timezone.utc).astimezone().date()
    end_date   = local_today.strftime("%Y-%m-%d")
    start_date = (local_today - timedelta(days=n - 1)).strftime("%Y-%m-%d")

    access = await get_fitbit_access_token("demo")
    base = "https://api.fitbit.com"

    # Steps and calories (bulk fetch)
    steps_json = await fitbit_get(access, f"{base}/1/user/-/activities/steps/date/{start_date}/{end_date}.json")
    cals_json  = await fitbit_get(access, f"{base}/1/user/-/activities/calories/date/{start_date}/{end_date}.json")

    steps_map = {row.get("dateTime"): row.get("value", "0")
                 for row in steps_json.get("activities-steps", [])}
    cals_map  = {row.get("dateTime"): row.get("value", "0")
                 for row in cals_json.get("activities-calories", [])}

    # Sleep data aggregation
    sleep_total_map: Dict[str, int] = {}
    sleep_stage_map: Dict[str, Dict[str, int]] = {}
    try:
        sleep_json = await fitbit_get(access, f"{base}/1.2/user/-/sleep/date/{start_date}/{end_date}.json")
        for log in sleep_json.get("sleep", []):
            day = log.get("dateOfSleep") or (log.get("startTime", "")[:10])
            if not day:
                continue
            mins = int(log.get("minutesAsleep", 0) or 0)
            sleep_total_map[day] = sleep_total_map.get(day, 0) + mins

            summary = ((log.get("levels") or {}).get("summary") or {})
            cur = sleep_stage_map.get(day, {"deep": 0, "rem": 0, "light": 0, "wake": 0})
            for k in ("deep", "rem", "light", "wake"):
                cur[k] += int(((summary.get(k) or {}).get("minutes")) or 0)
            sleep_stage_map[day] = cur
    except Exception:
        pass

    # SpO2 data (per day)
    dates = [(local_today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    spo2_map: Dict[str, float] = {}
    for d in dates:
        try:
            s = await fitbit_get(access, f"{base}/1/user/-/spo2/date/{d}.json")
            val = (s.get("value") or {}).get("avg")
            if val is None and "spo2" in s:
                val = (s.get("spo2") or {}).get("avg")
            if val is not None:
                spo2_map[d] = val
        except Exception:
            pass

    # Format results
    results: List[Dict[str, Any]] = []
    for d in dates:
        steps = steps_map.get(d, "0")
        cals  = cals_map.get(d, "0")

        if d in sleep_total_map:
            stages = sleep_stage_map.get(d)
            if stages and sum(stages.values()) > 0:
                sleep_line = (
                    f"総睡眠{sleep_total_map[d]}分 "
                    f"(深:{stages.get('deep',0)} / レム:{stages.get('rem',0)} / "
                    f"浅:{stages.get('light',0)} / 覚醒:{stages.get('wake',0)})"
                )
            else:
                sleep_line = f"総睡眠{sleep_total_map[d]}分"
        else:
            sleep_line = "データなし"

        spo2_line = f"平均{spo2_map[d]}" if d in spo2_map else "データなし"

        results.append({
            "date": d,
            "steps_total": steps,
            "sleep_line": sleep_line,
            "spo2_line": spo2_line,
            "calories_total": cals,
        })

    return results

def save_fitbit_daily_firestore(user_id: str, day: Dict[str, Any]) -> Dict[str, Any]:
    """Fitbit日次サマリをFirestoreに保存"""
    doc = user_doc(user_id).collection("fitbit_daily").document(day["date"])
    def to_int(x):
        try:
            return int(float(x))
        except Exception:
            return 0
    payload = {
        "date": day["date"],
        "steps_total": to_int(day.get("steps_total", 0)),
        "sleep_line": day.get("sleep_line", ""),
        "spo2_line": day.get("spo2_line", ""),
        "calories_total": to_int(day.get("calories_total", 0)),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    doc.set(payload, merge=True)
    return payload

async def save_last7_fitbit_to_stores(user_id: str = "demo") -> Dict[str, Any]:
    """直近7日を取得し、FirestoreとBigQueryに保存"""
    days = await fitbit_last_n_days(7)

    # Firestore保存
    saved = []
    for d in days:
        saved.append(save_fitbit_daily_firestore(user_id, d))

    # BigQuery保存
    bq_res = bq_upsert_fitbit_days(user_id, days)

    return {"firestore_saved_count": len(saved), "bigquery": bq_res}
