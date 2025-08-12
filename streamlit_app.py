# app_streamlit.py
import io
import requests
import streamlit as st
from dotenv import load_dotenv
import os
from typing import Optional
from datetime import datetime, date, time, timedelta
import pandas as pd
from google.cloud import bigquery
import builtins
from zoneinfo import ZoneInfo

# ====== .env を読む（UI入力はしない）======
load_dotenv()  # .env を読む

# .env のキー名に合わせて取得
BACKEND_BASE = os.getenv("RUN_BASE_URL", "http://localhost:8080")
UI_API_TOKEN    = os.getenv("UI_API_TOKEN", "")

def require_env():
    missing = []
    if not BACKEND_BASE:
        missing.append("RUN_BASE_URL")
    if not UI_API_TOKEN:
        missing.append("UI_API_TOKEN")
    if missing:
        st.error(f"必要な環境変数がありません: {', '.join(missing)} (.env か実行環境に設定してください)")
        st.stop()

require_env()

# ====== 共通HTTPヘルパ ======
def api_get(path: str):
    url = f"{BACKEND_BASE.rstrip('/')}{path}"
    r = requests.get(url, headers={"x-api-token": UI_API_TOKEN}, timeout=120)
    r.raise_for_status()
    return r.json()

def api_post(path: str, json=None, files=None, data=None):
    url = f"{BACKEND_BASE.rstrip('/')}{path}"
    r = requests.post(url, headers={"x-api-token": UI_API_TOKEN}, json=json, files=files, data=data, timeout=90)
    r.raise_for_status()
    return r.json()

def iso_from_date_time(d: date, t: time) -> str:
    return datetime.combine(d, t).isoformat(timespec="seconds")

def hdr():
    return {"x-api-token": UI_API_TOKEN} if UI_API_TOKEN else {}

api_base = os.environ["RUN_BASE_URL"]  # 必須なので get ではなく []

# === ダッシュボード関数 ===
def render_dashboard_page(current_user_id: str = "demo"):
    st.title("ダッシュボード｜計測結果の推移")
    today = date.today()
    default_start = today - timedelta(days=6)
    start_d, end_d = st.date_input("期間を選択", value=(default_start, today), format="YYYY-MM-DD")
    if isinstance(start_d, (tuple, list)):
        start_d, end_d = start_d[0], start_d[1]

    uid = current_user_id
    with st.spinner("BigQuery からデータ取得中..."):
        df_calorie_diff = df_calorie_difference_analysis(uid, start_d, end_d)
        df_w = df_weight_series(uid, start_d, end_d)

    st.subheader("カロリー収支（消費・摂取カロリー）")
    if not df_calorie_diff.empty:
        # 日本語日付表示に変更
        df_display = df_calorie_diff.copy()
        df_display['日付'] = pd.to_datetime(df_display['date']).dt.strftime('%m/%d')
        
        # consumption_calories と take_in_calories を同じグラフに表示（色指定）
        chart_data = df_display.set_index("日付")[["take_in_calories", "consumption_calories"]]
        chart_data.columns = ["摂取カロリー", "消費カロリー"]
        st.line_chart(chart_data, color=["#0066cc", "#cc0000"])  # 青、赤
    else:
        st.info("カロリーデータなし")
    
    st.subheader("体重変化")
    if not df_calorie_diff.empty and not df_calorie_diff["weight_change_kg"].isna().all():
        # 体重変化の合計を計算
        total_weight_change = df_calorie_diff["weight_change_kg"].sum()
        
        # 表示用テキスト作成
        if total_weight_change > 0:
            change_text = f"+{total_weight_change:.1f}kg増加しました。"
        elif total_weight_change < 0:
            change_text = f"{total_weight_change:.1f}kg減少しました。"
        else:
            change_text = "±0.0kg変化なしでした。"
        
        st.text(change_text)
        
        # 日本語日付表示に変更（棒グラフに変更）
        df_weight_display = df_calorie_diff.copy()
        df_weight_display['日付'] = pd.to_datetime(df_weight_display['date']).dt.strftime('%m/%d')
        st.bar_chart(df_weight_display.set_index("日付")["weight_change_kg"])
    else:
        st.info("体重変化データなし")
    
    st.subheader("体重")
    if not df_w.empty and not df_w["weight_kg"].isna().all():
        # 日本語日付表示に変更
        df_w_display = df_w.copy()
        df_w_display['日付'] = pd.to_datetime(df_w_display['d']).dt.strftime('%m/%d')
        st.line_chart(df_w_display.set_index("日付")["weight_kg"])
    else:
        st.info("体重データなし")
    return

# === BigQuery helpers ===
_bq_client = None
def get_bq():
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client()
    return _bq_client

def df_calorie_difference_analysis(user_id: str, start_d: date, end_d: date) -> pd.DataFrame:
    """
    calorie_difference_analysis テーブルからデータを取得
    """
    sql = """
    SELECT date, consumption_calories, take_in_calories, weight_change_kg
    FROM `peak-empire-396108.health_raw.calorie_difference_analysis`
    WHERE DATE(date) BETWEEN @s AND @e
    ORDER BY date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("s","DATE", start_d),
            bigquery.ScalarQueryParameter("e","DATE", end_d),
        ]
    )
    return get_bq().query(sql, job_config=job_config).to_dataframe()

def df_fitbit_daily(user_id: str, start_d: date, end_d: date) -> pd.DataFrame:
    sql = """
    SELECT DATE(date) AS d, steps_total, calories_total
    FROM `peak-empire-396108.health_raw.fitbit_daily`
    WHERE user_id = @uid
      AND DATE(date) BETWEEN @s AND @e
    ORDER BY d
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("uid","STRING", user_id),
            bigquery.ScalarQueryParameter("s","DATE", start_d),
            bigquery.ScalarQueryParameter("e","DATE", end_d),
        ]
    )
    return get_bq().query(sql, job_config=job_config).to_dataframe()

def df_daily_calorie(user_id: str, start_d: date, end_d: date) -> pd.DataFrame:
    sql = """
    SELECT DATE(when_date) AS d, daily_kcal
    FROM `peak-empire-396108.health_raw.daily_calorie_simple`
    WHERE user_id = @uid
      AND DATE(when_date) BETWEEN @s AND @e
    ORDER BY d
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("uid","STRING", user_id),
            bigquery.ScalarQueryParameter("s","DATE", start_d),
            bigquery.ScalarQueryParameter("e","DATE", end_d),
        ]
    )
    return get_bq().query(sql, job_config=job_config).to_dataframe()

def df_weight_series(user_id: str, start_d: date, end_d: date) -> pd.DataFrame:
    """
    profiles に日付列が無い想定でも壊れないように設計：
    1) profiles に d/measurement_date/updated_at/created_at のいずれかがあればそれを使う
    2) 無ければ最新の weight_kg を取得し、期間の各日に同じ値で埋める（フラット線）
    """
    # 1) カラム検出
    cols = get_bq().query("""
      SELECT column_name
      FROM `peak-empire-396108.health_raw`.INFORMATION_SCHEMA.COLUMNS
      WHERE table_name = 'profiles'
    """).to_dataframe()["column_name"].str.lower().tolist()

    date_cols = [c for c in ["d","date","measurement_date","updated_at","created_at"] if c in cols]
    has_date = len(date_cols) > 0

    if has_date:
        dc = date_cols[0]
        sql = f"""
        SELECT DATE({dc}) AS d, weight_kg
        FROM `peak-empire-396108.health_raw.profiles`
        WHERE user_id = @uid AND DATE({dc}) BETWEEN @s AND @e
        ORDER BY d
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("uid","STRING", user_id),
                bigquery.ScalarQueryParameter("s","DATE", start_d),
                bigquery.ScalarQueryParameter("e","DATE", end_d),
            ]
        )
        df = get_bq().query(sql, job_config=job_config).to_dataframe()
        if not df.empty:
            return df

    # 2) 最新 weight_kg を使って日付レンジをフラットで埋める
    df_latest = get_bq().query("""
        SELECT weight_kg
        FROM `peak-empire-396108.health_raw.profiles`
        WHERE user_id = @uid
        ORDER BY weight_kg DESC  -- 日付が無い想定。単に1行取れればOK
        LIMIT 1
    """, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("uid","STRING", user_id)]
    )).to_dataframe()

    latest = float(df_latest.iloc[0]["weight_kg"]) if not df_latest.empty else None
    rng = pd.date_range(start=start_d, end=end_d, freq="D")
    return pd.DataFrame({"d": rng.date, "weight_kg": [latest]*len(rng)})

# ====== ページ設定 ======
st.set_page_config(page_title="FitAI", page_icon="icon.png", layout="centered")
st.markdown("<h1 style='text-align: center;'>FitAI</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; font-size:20px;'>ヘルスケア&運動コーチングAI</p>", unsafe_allow_html=True)

# ====== 小ヘルパ ======
def get_profile() -> dict:
    try:
        j = api_get("/ui/profile")
        return (j or {}).get("profile", {})
    except Exception as e:
        st.error(f"プロフィール取得に失敗: {e}")
        return {}

def save_profile(payload: dict):
    try:
        api_post("/ui/profile", json=payload)
        st.success("プロフィールを保存しました。")
        return True
    except requests.HTTPError as e:
        st.error(f"保存失敗: {e.response.text[:400]}")
    except Exception as e:
        st.error(f"保存失敗: {e}")
    return False

def upload_meal_image(when_iso: str, file_bytes: bytes, filename: str, mime: str):
    files = {"file": (filename, io.BytesIO(file_bytes), mime or "image/jpeg")}
    data = {"when": when_iso}
    try:
        return api_post("/ui/meal_image", files=files, data=data)
    except requests.HTTPError as e:
        st.error(f"アップロード失敗: {e.response.text[:600]}")
    except Exception as e:
        st.error(f"アップロード失敗: {e}")
    return None

def run_weekly_coaching(show_prompt=False):
    try:
        j = api_get("/coach/weekly")
        st.success("コーチングを実行しました。")
        if show_prompt and j.get("prompt"):
            with st.expander("実際に送ったプロンプトを見る"):
                st.code(j["prompt"])
        st.subheader("📝 コーチからの提案")
        st.write(j.get("preview") or "プレビューがありませんでした。")
    except requests.HTTPError as e:
        st.error(f"実行失敗: {e.response.text[:800]}")
    except Exception as e:
        st.error(f"実行失敗: {e}")

# =========================
# ① ユーザー情報ページ
# =========================
def _render_page_profile():
    st.header("あなたの情報を入力してください")
    prof = get_profile()

    # 表示用⇔内部コードのマップ
    sex_display_opts = ["", "男性", "女性", "その他"]
    sex_code_for_display = {"": None, "男性": "male", "女性": "female", "その他": "other"}
    display_for_code = {"male": "男性", "female": "女性", "other": "その他", "": ""}

    # 既存プロフィールの性別コード(male/female/other)を表示用に変換
    current_sex_display = display_for_code.get(str(prof.get("sex") or ""), "")

    with st.form("profile_form"):
        col1, col2 = st.columns(2, vertical_alignment="center")

        # ---- 左カラム（ここに目標体重を移動）----
        with col1:
            age = st.number_input("年齢", 0, 120, int(prof.get("age") or 0), step=1)
            sex_display = st.selectbox("性別", sex_display_opts,
                                       index=sex_display_opts.index(current_sex_display))
            height_cm = st.number_input("身長 (cm)", 0.0, 300.0, float(prof.get("height_cm") or 0.0), step=0.1)
            weight_kg = st.number_input("現体重 (kg)", 0.0, 500.0, float(prof.get("weight_kg") or 0.0), step=0.1)
            # ← ここに移動
            target_weight_kg = st.number_input("目標体重 (kg)", 0.0, 500.0,
                                               float(prof.get("target_weight_kg") or 0.0), step=0.1)

        # ---- 右カラム（目標体重は削除して、残りを詰める）----
        with col2:
            goal = st.text_area("運動目的（自由記述）", value=str(prof.get("goal") or ""),
                                placeholder="例）減量と体力向上。週3回の有酸素＋軽い筋トレ")
            allergies = st.text_input("アレルギー情報", value=str(prof.get("allergies") or ""),
                                      placeholder="例）そば、ピーナッツ")

        # 喫煙/飲酒（週あたり頻度）
        freq_opts = ["なし", "1〜3日", "4〜6日", "毎日"]
        smoke_ui = st.selectbox("喫煙頻度（週あたり）", freq_opts,
                                index=freq_opts.index(prof.get("smoke_ui", prof.get("smoking_ui", "なし"))) if prof else 0)
        drink_ui = st.selectbox("飲酒頻度（週あたり）", freq_opts,
                                index=freq_opts.index(prof.get("alcohol_ui", "なし")) if prof else 0)

        # 既往歴（複数選択）
        disease_labels = [
            "高血圧","糖尿病","心疾患","脳卒中（脳梗塞・脳出血）","気管支喘息","慢性閉塞性肺疾患（COPD）",
            "胃潰瘍・十二指腸潰瘍","肝炎（B型・C型）","慢性腎不全","悪性腫瘍（がん）","骨粗鬆症",
            "関節リウマチ","うつ病","てんかん","薬剤アレルギー","その他"
        ]
        prev = set()
        existing = prof.get("past_history", [])
        if isinstance(existing, list):
            eng2jp = {
                "hypertension":"高血圧","diabetes":"糖尿病","cad":"心疾患","stroke":"脳卒中（脳梗塞・脳出血）",
                "asthma":"気管支喘息","copd":"慢性閉塞性肺疾患（COPD）","ulcer":"胃潰瘍・十二指腸潰瘍",
                "hepatitis":"肝炎（B型・C型）","kidney":"慢性腎不全","cancer":"悪性腫瘍（がん）",
                "osteoporosis":"骨粗鬆症","ra":"関節リウマチ","depression":"うつ病","epilepsy":"てんかん",
                "drug_allergy":"薬剤アレルギー","other":"その他"
            }
            for x in existing:
                prev.add(eng2jp.get(str(x), str(x)))
        selected = st.multiselect("既往歴（該当を選択※複数選択可）", disease_labels,
                                  default=sorted(list(prev)) if prev else [])

        medications = st.text_area("現在の服薬内容", value=str(prof.get("medications") or ""),
                                   placeholder="例）降圧薬（アムロジピン5mg）朝1錠 など")

        submitted = st.form_submit_button("保存する", use_container_width=True)

        if submitted:
            # マッピング（この中だけで使用）
            smoke_map = {"なし":"never","1〜3日":"current","4〜6日":"current","毎日":"current"}
            drink_map = {"なし":"none","1〜3日":"social","4〜6日":"moderate","毎日":"heavy"}
            jp2eng = {
                "高血圧":"hypertension","糖尿病":"diabetes","心疾患":"cad","脳卒中（脳梗塞・脳出血）":"stroke",
                "気管支喘息":"asthma","慢性閉塞性肺疾患（COPD）":"copd","胃潰瘍・十二指腸潰瘍":"ulcer",
                "肝炎（B型・C型）":"hepatitis","慢性腎不全":"kidney","悪性腫瘍（がん）":"cancer",
                "骨粗鬆症":"osteoporosis","関節リウマチ":"ra","うつ病":"depression","てんかん":"epilepsy",
                "薬剤アレルギー":"drug_allergy","その他":"other"
            }
            past_history_codes = [jp2eng.get(x, "other") for x in selected]

            payload = {
                "age": int(age) if age else None,
                # 表示値 → バックエンドのコード（male/female/other）へ
                "sex": sex_code_for_display.get(sex_display) or None,
                "height_cm": float(height_cm) if height_cm else None,
                "weight_kg": float(weight_kg) if weight_kg else None,
                "target_weight_kg": float(target_weight_kg) if target_weight_kg else None,
                "goal": goal or None,
                "smoking_status": smoke_map.get(smoke_ui, "never"),
                "alcohol_habit":  drink_map.get(drink_ui, "none"),
                "past_history": past_history_codes or None,
                "medications": medications or None,
                "allergies": allergies or None,
            }
            payload = {k: v for k, v in payload.items() if v not in (None, "", [])}
            save_profile(payload)
            pass

# =========================
# ② 食事画像アップロード
# =========================
def _render_page_meal():
    st.header("食事の画像をアップロードしてください")
    st.caption("※ 画像はサーバに保存せず、OpenAIに直接渡して要約テキストのみ保存します。")

    labels = ["朝ごはん", "昼ごはん", "夜ごはん", "その他"]
    tabs = st.tabs(labels)

    meal_kind_map = {0: "breakfast", 1: "lunch", 2: "dinner", 3: "other"}

    for i, tab in enumerate(tabs):
        with tab:
            st.subheader(labels[i])
            c1, c2 = st.columns(2)
            with c1:
                d = st.date_input("日付", value=date.today(), key=f"date_{i}")
            with c2:
                default_time = datetime.now(ZoneInfo("Asia/Tokyo")).time().replace(second=0, microsecond=0)
                t = st.time_input("時刻", value=default_time, key=f"time_{i}")

            file = st.file_uploader("画像を選択（jpg/png/webp）", type=["jpg","jpeg","png","webp"], key=f"uploader_{i}")
            memo = st.text_input("メモ（任意）", key=f"memo_{i}", placeholder="例）外食。唐揚げ定食のご飯少なめ など")

            if st.button("この食事を登録する", key=f"submit_{i}", use_container_width=True, disabled=not file):
                when_iso = iso_from_date_time(d, t)
                uploaded = upload_meal_image(when_iso, file.read(), file.name, file.type or "image/jpeg")
                if uploaded:
                    st.success("アップロード完了")
                    if uploaded.get("preview"):
                        st.write("📝 画像要約")
                        st.write(uploaded["preview"])
                    if memo.strip():
                        try:
                            api_post("/ui/meal", json={"when": when_iso, "text": f"[{meal_kind_map[i]}] {memo}", "kcal": None})
                            st.info("メモも登録しました。")
                        except Exception as e:
                            st.warning(f"メモ保存に失敗（スキップ）: {e}")

    st.divider()
    pass
    
# =========================
# ③ コーチング
# =========================
def _render_page_coaching():
    st.header("AIコーチングからアドバイスを受ける")
    st.write(
        "直近7日間の Fitbit データと食事記録、ユーザー情報（年齢/性別/身長/現体重/目標体重/運動目的/既往歴/服薬/アレルギー/喫煙・飲酒頻度）を含めて FitAI に依頼します。"
    )

    show_prompt = st.checkbox("送信プロンプトを表示", value=False)

    if st.button("コーチングを実行する", type="primary", use_container_width=True):
        with st.spinner("実行中..."):
            try:
                params = {"show_prompt": "1"} if show_prompt else {}
                resp = requests.get(f"{api_base}/coach/weekly", params=params, timeout=120).json()
            except Exception as e:
                st.error(f"実行失敗: {e}")
                st.stop()

        # ↑ ここは still inside "if st.button"
        if not resp.get("ok"):
            st.error(f"実行失敗: {resp}")
        else:
            st.success("コーチングを実行しました。")

            preview = resp.get("preview") or ""
            if preview:
                st.markdown(preview)

            if show_prompt:
                prompt_text = resp.get("prompt", "")
                if prompt_text:
                    st.text_area("送信プロンプト", value=prompt_text, height=400)
                else:
                    st.warning("送信プロンプトが取得できませんでした。")
    st.divider()
    pass

    #st.caption("バックエンド `/coach/weekly` を呼び出します。")
    #st.caption(f"BACKEND_BASE={BACKEND_BASE}")
    #st.caption(f"x-api-token(有無)={'あり' if bool(UI_API_TOKEN) else 'なし'}")

# =========================
# ダッシュボード
# =========================
def _render_page_dashboard():
    render_dashboard_page(current_user_id="demo")

# =========================
# ページ制御
# =========================
page = st.sidebar.radio(
    "ページ",
    ["ユーザー情報入力", "食事画像アップロード", "AIコーチング", "ダッシュボード"],
    index=0
)

_dispatch = {
    "ユーザー情報入力": _render_page_profile,
    "食事画像アップロード": _render_page_meal,
    "AIコーチング": _render_page_coaching,
    "ダッシュボード": _render_page_dashboard,
}

# 存在しないキーでも落ちないようgetで取得
_render = _dispatch.get(page)
if _render:
    _render()
else:
    st.error(f"未対応のページです: {page}")
