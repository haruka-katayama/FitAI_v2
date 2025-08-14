import httpx
import base64
from app.config import settings

async def ask_gpt5(text: str) -> str:
    """OpenAI Chat Completions API 呼び出し"""
    if not settings.OPENAI_API_KEY:
        return "（OPENAI_API_KEY が未設定です）"
    
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}", 
        "Content-Type": "application/json"
    }
    
    # Chat Completions API形式に修正
    body = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {
                "role": "user",
                "content": text
            }
        ],
        "max_tokens": 1500,
        "temperature": 0.7
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]

async def vision_extract_meal_bytes(data: bytes, mime: str | None) -> str:
    """画像バイナリを base64 で直接 OpenAI に渡して食事内容を短く要約"""
    if not settings.OPENAI_API_KEY:
        return "（OPENAI_API_KEY が未設定です）"
    
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}", 
        "Content-Type": "application/json"
    }
    instruction = (
        "この食事写真を短い日本語テキストで説明してください。"
        "料理名・主な食材・推定量を簡潔に。可能なら大まかなカロリーも一言で。"
    )
    
    b64 = base64.b64encode(data).decode("utf-8")
    
    # Chat Completions API with Vision形式に修正
    body = {
        "model": "gpt-4o",  # Vision対応モデルを明示的に指定
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": instruction
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime or 'image/jpeg'};base64,{b64}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 500,
        "temperature": 0.3
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body)
        r.raise_for_status()
        j = r.json()
        return j["choices"][0]["message"]["content"]
