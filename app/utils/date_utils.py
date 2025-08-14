from datetime import datetime, timezone, timedelta

def to_when_date_str(iso_str: str | None) -> str:
    """ISO8601文字列の先頭10桁(YYYY-MM-DD)を日付キーとして返す"""
    if not iso_str:
        return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    return iso_str[:10]

def jst_now() -> datetime:
    """JST現在時刻を返す"""
    return datetime.now(timezone.utc) + timedelta(hours=9)

def format_datetime_hp(dt: datetime) -> str:
    """Health Planet API用の日時フォーマット（yyyymmddHHMMSS）"""
    return dt.strftime("%Y%m%d%H%M%S")

def get_date_range(days: int) -> tuple[str, str]:
    """指定日数分の日付範囲を取得"""
    today = datetime.now(timezone.utc).astimezone().date()
    end_date = today.strftime("%Y-%m-%d")
    start_date = (today - timedelta(days=days-1)).strftime("%Y-%m-%d")
    return start_date, end_date

def get_jst_date_range(days: int) -> tuple[str, str]:
    """指定日数分の日付範囲を JST で取得"""
    today_jst = jst_now().date()
    end_date = today_jst.strftime("%Y-%m-%d")
    start_date = (today_jst - timedelta(days=days-1)).strftime("%Y-%m-%d")
    return start_date, end_date

def format_date_for_display(date_str: str) -> str:
    """YYYY-MM-DD を表示用フォーマットに変換"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%m月%d日")
    except ValueError:
        return date_str

def is_today(date_str: str, timezone_offset: int = 9) -> bool:
    """指定した日付が今日かどうかを判定"""
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = (datetime.now(timezone.utc) + timedelta(hours=timezone_offset)).date()
        return target_date == today
    except ValueError:
        return False

def days_ago(date_str: str, timezone_offset: int = 9) -> int:
    """指定した日付が何日前かを返す"""
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = (datetime.now(timezone.utc) + timedelta(hours=timezone_offset)).date()
        return (today - target_date).days
    except ValueError:
        return -1
