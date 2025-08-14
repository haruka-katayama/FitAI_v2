from linebot import LineBotApi
from linebot.models import TextSendMessage
from app.config import settings
from typing import Dict, Any

line_bot = LineBotApi(settings.LINE_ACCESS_TOKEN) if settings.LINE_ACCESS_TOKEN else None

def push_line(text: str) -> Dict[str, Any]:
    """LINEメッセージを送信"""
    if not settings.LINE_ACCESS_TOKEN or not settings.LINE_USER_ID:
        return {"sent": False, "reason": "LINE secrets not set"}
    
    try:
        line_bot.push_message(settings.LINE_USER_ID, TextSendMessage(text=text))
        return {"sent": True}
    except Exception as e:
        return {"sent": False, "reason": repr(e)}
