from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.services.coaching_service import weekly_coaching, monthly_coaching, build_daily_prompt
from app.external.openai_client import ask_gpt
from app.external.line_client import push_line
from app.config import settings
import httpx

router = APIRouter(tags=["coaching"])

CHARACTER_PROMPTS = {
    "A": "あなたはスポーツアニメの熱血主人公のように、明るく前向きな男性コーチです。ユーザーの良い点を全力で褒めて、努力を認め、次につながるポジティブな提案をします。語尾は元気で勢いがあり、『最高だ！』『その調子だ！』などをよく使います。失敗や課題があっても決して否定せず、『これは成長のチャンスだ！』と捉え、ユーザーをやる気にさせる口調で話してください。",
    "B": "あなたはクールで辛辣な男性ライバルキャラのようなコーチです。ユーザーの甘さや怠けを鋭く指摘し、厳しい言葉で発破をかけます。褒めることは少なく、基本は『まだ足りない』『甘えるな』と突き放す口調ですが、最後には『だからこそお前なら変われるはずだ』と奮起させるメッセージを添えます。口調はぶっきらぼうで短めですが、核心を突く口調で話してください。",
    "C": "あなたは優しく穏やかな女性キャラクターで、癒し系のお姉さんコーチです。ユーザーの小さな努力も見逃さずに褒め、『頑張ってるね』『えらいね』と共感します。口調は柔らかく、語尾に『ね』『よ』を多めに使います。改善点を伝えるときも、『こうするともっと楽になるかも』と提案型にして、ユーザーの気持ちを前向きに保つ口調で話してください。",
    "D": "あなたは辛辣で口の悪い女性キャラクターです。ユーザーの甘さや怠けを『ほんとにだらしない』『まだまだね』と厳しく指摘します。口調はツンツンしていて、語尾は『でしょ』『じゃない』など強め。ただし完全に突き放すのではなく、最後に『仕方ないから応援してあげる』『期待してるんだから』などツンデレらしい一言を加える口調で話してください。",
}

@router.get("/now")
async def coach_now():
    """今すぐコーチング"""
    # 循環インポートを避けるため、ここで import
    from app.services.fitbit_service import fitbit_today_core
    
    day = await fitbit_today_core()
    prompt = build_daily_prompt(day)
    msg = await ask_gpt(prompt)
    res = push_line(f"📣 今日のコーチング\n{msg}")
    return {"sent": res, "model": settings.OPENAI_MODEL, "preview": msg}

@router.get("/now_debug")
async def coach_now_debug():
    """デバッグ用コーチング"""
    try:
        # 循環インポートを避けるため、ここで import
        from app.services.fitbit_service import fitbit_today_core
        
        day = await fitbit_today_core()
        prompt = build_daily_prompt(day)
        out = await ask_gpt(prompt)
        return {"ok": True, "preview": out, "model": settings.OPENAI_MODEL}
    except httpx.HTTPStatusError as e:
        return JSONResponse({"ok": False, "status": e.response.status_code, "body": e.response.text[:1200]}, status_code=500)
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=500)

@router.get("/weekly")
async def coach_weekly(
    dry: bool = False,
    show_prompt: bool = False,
    character: str | None = None,
):
    """週次コーチング"""
    try:
        coach_prompt = CHARACTER_PROMPTS.get(character) if character else None
        result = await weekly_coaching(dry, show_prompt, coach_prompt)
        return result
    except Exception as e:
        return JSONResponse({"ok": False, "where": "coach_weekly", "error": repr(e)}, status_code=500)

@router.get("/monthly")
async def coach_monthly():
    """月次コーチング"""
    try:
        result = await monthly_coaching()
        return result
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=500)
