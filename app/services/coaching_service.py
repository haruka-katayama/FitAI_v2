from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.external.openai_client import ask_gpt5
from app.external.line_client import push_line
from app.services.meal_service import meals_last_n_days
from app.database.firestore import get_latest_profile, user_doc
from app.database.bigquery import bq_upsert_profile, bq_insert_rows, bq_client
from app.config import settings

def build_daily_prompt(day: Dict[str, Any]) -> str:
    """日次コーチング用プロンプトを生成"""
    date = day.get("date", "")
    steps = day.get("steps_total", "0")
    sleep_line = day.get("sleep_line", "データなし")
    calories = day.get("calories_total", "0")
    spo2_line = day.get("spo2_line", "データなし")
    
    return f"""今日は {date}。Fitbit の今日のデータは:
- 歩数: {steps}
- 睡眠: {sleep_line}
- SpO₂: {spo2_line}
- 消費カロリー: {calories}

あなたはヘルスケア&エクササイズのプロコーチです。
500文字以内で今日の状態を要約し、明日に向けて1〜3つの具体的アクションを日本語で提案してください。"""

def build_weekly_prompt(days: List[Dict[str, Any]], meals_by_day: Dict[str, List[Dict[str, Any]]], profile: Optional[Dict[str, Any]] = None) -> str:
    """コーチング用プロンプトを生成"""
    # 週次本文
    lines = []
    for d in days:
        day_key = d["date"]
        meals = meals_by_day.get(day_key, [])
        meal_snippets = []
        for m in meals[:2]:
            kcal_val = m.get("kcal")
            kcal_part = f"（~{int(kcal_val)}kcal）" if isinstance(kcal_val, (int, float)) else ""
            text = (m.get("text") or "").strip()
            if text:
                meal_snippets.append(f"・{text}{kcal_part}")
        meal_block = "\n".join(meal_snippets) if meal_snippets else "（食事記録なし）"

        lines.append(
            f"{d['date']}: 歩数{d['steps_total']}, 睡眠{d['sleep_line']}, "
            f"SpO₂{d['spo2_line']}, カロリー{d['calories_total']}\n"
            f"  食事:\n{meal_block}"
        )
    body = "\n".join(lines)

    # プロフィール付帯情報
    prof_lines = []
    if profile:
        def add(label: str, key: str, transform=lambda x: x):
            v = profile.get(key)
            if v not in (None, "", []):
                prof_lines.append(f"- {label}: {transform(v)}")

        add("運動目的", "goal")
        add("年齢", "age")
        add("性別", "sex")
        add("身長(cm)", "height_cm")
        add("現体重(kg)", "weight_kg")
        add("目標体重(kg)", "target_weight_kg")
        add("喫煙状況", "smoking_status")
        add("飲酒習慣", "alcohol_habit")

        if isinstance(profile.get("past_history"), list) and profile["past_history"]:
            mapping = {
                "hypertension": "高血圧", "diabetes": "糖尿病", "cad": "心疾患",
                "stroke": "脳卒中", "dyslipidemia": "脂質異常症",
                "kidney": "腎疾患", "liver": "肝疾患", "asthma": "喘息", "other": "その他",
            }
            j = ", ".join(mapping.get(x, x) for x in profile["past_history"])
            prof_lines.append(f"- 既往歴: {j}")

        add("服薬", "medications")
        add("アレルギー", "allergies")

    profile_block = "\n".join(prof_lines) if prof_lines else "（プロフィール未設定）"

    return f"""過去7日間のヘルスデータと食事記録です:
{body}

[プロフィール抜粋]
{profile_block}

あなたはヘルスケア&栄養のプロコーチです。
すべての分析と提案は、ここまでに記載されたユーザーのプロフィール（年齢、性別、身長、体重、目標体重、運動目的、嗜好、既往歴、生活習慣、過去7日間のデータ）を必ず参照して行ってください。
返答は以下の構成を必須とします。
1.良かった点
　 - ユーザーのデータの中で特に良かった行動や結果を挙げ、その理由を数値や専門知識で説明する
2.課題点
　 - 改善すべき具体的な行動や習慣を挙げ、その課題が何によって引き起こされているのかを説明する
3.原因分析
　 - 課題が発生した背景を、活動量・栄養・睡眠・生活習慣などの観点から分析する
4.改善提案
　 - 食事：摂取エネルギー(kcal)とPFCバランスの数値、具体的食材・料理例を提示
　 - 運動：種目名・回数・セット数・時間・負荷を明記
　 - 睡眠・生活習慣：行動内容と時間帯、環境条件を明記
　 - 必ず「なぜそれが有効か」を生理学・栄養学・運動生理学的根拠とともに説明する
5.明日のアクションプラン
　 - 食事・運動・睡眠のそれぞれについて、再現性が高く今すぐ実行できる内容を提案する
すべて日本語で、専門性・個別性・具体性を重視して作成してください。"""

async def daily_coaching() -> Dict[str, Any]:
    """日次コーチングを実行"""
    try:
        # 循環インポートを避けるため、ここで import
        from app.services.fitbit_service import fitbit_today_core, save_fitbit_daily_firestore
        
        # 今日のFitbitデータ取得
        day = await fitbit_today_core()
        
        # Firestore保存
        saved = save_fitbit_daily_firestore("demo", day)
        
        # BigQuery保存
        try:
            bq_insert_rows(settings.BQ_TABLE_FITBIT, [{
                "user_id": "demo",
                "date": saved["date"],
                "steps_total": saved["steps_total"],
                "sleep_line": saved["sleep_line"],
                "spo2_line": saved["spo2_line"],
                "calories_total": saved["calories_total"],
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }])
        except Exception as e:
            print(f"[WARN] BQ insert (daily_coaching) failed: {e}")
        
        # GPTでコーチング生成
        prompt = build_daily_prompt(day)
        msg = await ask_gpt5(prompt)
        
        # LINE送信
        res = push_line(f"⏰ 毎日のコーチング\n{msg}")
        
        return {"ok": True, "sent": res, "preview": msg, "saved": saved}
    except Exception as e:
        push_line(f"⚠️ cronエラー: {e}")
        return {"ok": False, "error": str(e)}

async def weekly_coaching(dry: bool = False, show_prompt: bool = False) -> Dict[str, Any]:
    """コーチングを実行"""
    try:
        # 循環インポートを避けるため、ここで import
        from app.services.fitbit_service import fitbit_last_n_days, save_fitbit_daily_firestore
        from app.database.bigquery import bq_upsert_fitbit_days
        
        # 直近7日 Fitbit
        days = await fitbit_last_n_days(7)
        
        # Firestore保存
        saved = [save_fitbit_daily_firestore("demo", d) for d in days]
        
        # BigQuery保存
        bq_fitbit = bq_upsert_fitbit_days("demo", days)
        bq_prof   = bq_upsert_profile("demo")
        
        # 週次プロンプト準備
        meals_map = await meals_last_n_days(7, "demo")
        profile   = get_latest_profile("demo")
        prompt    = build_weekly_prompt(days, meals_map, profile)
        
        print("\n=== WEEKLY PROMPT ===\n", prompt, "\n=== END PROMPT ===\n")
        
        # dry=1 の時は生成＆LINE送信をスキップ
        msg = "(dry run) no OpenAI call"
        send_res = {"sent": False, "reason": "dry"}
        if not dry:
            try:
                msg = await ask_gpt5(prompt)
            except Exception as e:
                print(f"[ERROR] OpenAI failed: {e}")
                msg = f"(OpenAI error) {e}"
            
            try:
                send_res = push_line(f"🗓️ AIコーチのアドバイス\n{msg}")
            except Exception as e:
                print(f"[WARN] LINE push failed: {e}")
                send_res = {"sent": False, "reason": repr(e)}
        
        resp = {
            "ok": True,
            "dry": dry,
            "saved_count": len(saved),
            "bq_fitbit": bq_fitbit,
            "bq_profile": bq_prof,
            "model": settings.OPENAI_MODEL,
            "sent": send_res,
            "preview": msg,
            "meals_keys": list(meals_map.keys()),
            "profile_used": bool(profile),
        }
        if show_prompt:
            resp["prompt"] = prompt
        
        return resp
        
    except Exception as e:
        print(f"[FATAL] weekly_coaching error: {e}")
        return {"ok": False, "where": "weekly_coaching", "error": str(e)}

async def monthly_coaching() -> Dict[str, Any]:
    """月次コーチングを実行"""
    if not bq_client:
        return {"ok": False, "error": "BigQuery not configured"}

    def q(sql: str):
        return list(bq_client.query(sql).result())

    fitbit_sql = f"""
    WITH d AS (
      SELECT DATE(date) AS d, steps_total, calories_total
      FROM `{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_FITBIT}`
      WHERE user_id='demo'
        AND date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 29 DAY) AND CURRENT_DATE()
    )
    SELECT COUNT(*) days, AVG(steps_total) avg_steps, MIN(steps_total) min_steps, MAX(steps_total) max_steps,
           AVG(calories_total) avg_cal, MIN(calories_total) min_cal, MAX(calories_total) max_cal
    FROM d
    """

    meals_sql = f"""
    SELECT when_date, text
    FROM `{settings.BQ_PROJECT_ID}.{settings.BQ_DATASET}.{settings.BQ_TABLE_MEALS}`
    WHERE user_id='demo'
      AND when_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 29 DAY) AND CURRENT_DATE()
    ORDER BY when_date DESC
    LIMIT 10
    """

    fb = q(fitbit_sql)[0]
    meals = q(meals_sql)

    meal_lines = "\n".join([f"- {r['when_date']}: {r['text']}" for r in meals])
    month_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m")
    prompt = f"""
あなたはヘルスケア＆栄養のプロコーチです。以下は{month_str}の30日分ダイジェストです。

[活動・消費]
- 期間日数: {int(fb['days'])}日
- 歩数: 平均 {int(fb['avg_steps'])}、最小 {int(fb['min_steps'])}、最大 {int(fb['max_steps'])}
- 消費カロリー: 平均 {int(fb['avg_cal'])}、最小 {int(fb['min_cal'])}、最大 {int(fb['max_cal'])}

[食事（代表10件）]
{meal_lines}

お願い：
1) この30日を「良かった点／改善点／注意すべき兆候」に分けて要約（300〜500字）
2) 来月の具体アクションを最大5つ（食事・運動・睡眠の観点で）
3) 実行チェックリスト（5箇条、短く）
"""

    monthly_text = await ask_gpt5(prompt)

    # Firestore保存
    user_doc("demo").collection("coach_monthly").document(month_str).set({
        "month": month_str,
        "text": monthly_text,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "avg_steps": int(fb['avg_steps']), "min_steps": int(fb['min_steps']), "max_steps": int(fb['max_steps']),
            "avg_cal": int(fb['avg_cal']), "min_cal": int(fb['min_cal']), "max_cal": int(fb['max_cal']),
        }
    }, merge=True)

    # BigQuery保存
    try:
        bq_insert_rows(settings.BQ_TABLE_MONTHLY, [{
            "user_id": "demo",
            "month": month_str,
            "summary_text": monthly_text,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }])
    except Exception:
        pass

    push_line(f"📅 {month_str} の振り返りができました！")
    return {"ok": True, "month": month_str, "preview": monthly_text[:400]}
