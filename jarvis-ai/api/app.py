"""
Jarvis FastAPI application — chat, WebSocket streaming, TradingView webhooks.
"""
import asyncio
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel

from config.settings import settings
from core.brain import JarvisBrain
from core.memory import memory
from core.scheduler import scheduler
from agents.portfolio import tool_executor

logger = logging.getLogger(__name__)

# One brain per REST call (shared); each WebSocket gets its own
_rest_brain = JarvisBrain(tool_executor=tool_executor)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Jarvis...")
    await memory.connect()
    await _rest_brain.load_memory()   # load durable facts into system prompt
    scheduler.start()
    yield
    # Shutdown
    scheduler.stop()
    await memory.disconnect()
    logger.info("Jarvis shut down.")


app = FastAPI(title="Jarvis AI", version="1.0.0", lifespan=lifespan)


# ── REST Endpoints ───────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    session_id: str


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    response = await _rest_brain.chat(req.message)
    return ChatResponse(response=response, session_id=req.session_id)


@app.post("/api/reset")
async def reset_chat():
    _rest_brain.reset()
    return {"status": "ok"}


@app.get("/api/briefing")
async def get_briefing():
    from agents.briefing import generate_daily_briefing
    text = await generate_daily_briefing()
    return {"briefing": text}


@app.get("/api/portfolio")
async def get_portfolio():
    from agents.portfolio import get_portfolio_summary
    return await get_portfolio_summary()


@app.get("/api/deals")
async def get_deals(stage: str = None):
    return await memory.get_deals(stage=stage)


@app.post("/api/deals")
async def create_deal(deal: dict):
    deal_id = await memory.add_deal(**deal)
    return {"id": deal_id}


@app.put("/api/deals/{deal_id}")
async def update_deal(deal_id: int, updates: dict):
    await memory.update_deal(deal_id, **updates)
    return {"status": "ok"}


# ── TradingView Webhook ──────────────────────────────────────

@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):
    body = await request.body()

    # Verify webhook secret
    secret = settings.tradingview_webhook_secret
    if secret:
        sig = request.headers.get("X-Webhook-Secret", "")
        if not hmac.compare_digest(sig, secret):
            raise HTTPException(status_code=403, detail="Invalid webhook secret")

    payload = await request.json()
    logger.info(f"TradingView alert: {payload}")

    # Let Jarvis analyze the alert
    alert_text = payload.get("message", str(payload))
    brain = JarvisBrain(tool_executor=tool_executor)
    analysis = await brain.chat(
        f"TradingView alert received: {alert_text}. "
        "Check my current positions and tell me if this requires action."
    )
    logger.info(f"Jarvis analysis: {analysis}")
    return {"status": "received", "analysis": analysis}


# ── WebSocket Streaming Chat ─────────────────────────────────

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    brain = JarvisBrain(tool_executor=tool_executor)
    await brain.load_memory()   # each WS session gets fresh memory load
    try:
        while True:
            message = await websocket.receive_text()
            async for token in brain.chat_stream(message):
                await websocket.send_text(token)
            await websocket.send_text("[DONE]")
    except WebSocketDisconnect:
        pass


# ── Voice Endpoints ──────────────────────────────────────────

@app.post("/api/voice/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    """Transcribe audio via Deepgram REST API."""
    if not settings.deepgram_api_key:
        raise HTTPException(status_code=503, detail="Deepgram API key not configured")
    audio_bytes = await audio.read()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&language=en",
            headers={
                "Authorization": f"Token {settings.deepgram_api_key}",
                "Content-Type": audio.content_type or "audio/webm",
            },
            content=audio_bytes,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Deepgram error: {resp.text}")
    data = resp.json()
    transcript = (
        data.get("results", {})
        .get("channels", [{}])[0]
        .get("alternatives", [{}])[0]
        .get("transcript", "")
    )
    return {"transcript": transcript}


class SpeakRequest(BaseModel):
    text: str
    voice_id: str = ""


@app.post("/api/voice/speak")
async def speak_text(req: SpeakRequest):
    """Convert text to speech via ElevenLabs and stream audio."""
    if not settings.elevenlabs_api_key:
        raise HTTPException(status_code=503, detail="ElevenLabs API key not configured")
    voice_id = req.voice_id or settings.elevenlabs_voice_id
    # Truncate very long responses for voice (first 500 chars)
    text = req.text[:600] if len(req.text) > 600 else req.text
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": settings.elevenlabs_api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"ElevenLabs error: {resp.text}")
    return StreamingResponse(
        iter([resp.content]),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline; filename=response.mp3"},
    )


# ── Proactive Notices ────────────────────────────────────────

@app.get("/api/notices")
async def get_notices():
    """Return all undismissed proactive notices (for display on UI load)."""
    return await memory.get_pending_notices()


@app.post("/api/notices/{notice_id}/dismiss")
async def dismiss_notice(notice_id: int):
    await memory.dismiss_notice(notice_id)
    return {"status": "ok"}


# ── Audit Log ────────────────────────────────────────────────

@app.get("/api/audit")
async def get_audit(limit: int = 50):
    """Return recent tool calls and heartbeat actions."""
    return await memory.get_audit_log(limit=limit)


# ── Kill Switch ──────────────────────────────────────────────

class KillSwitchRequest(BaseModel):
    paused: bool


@app.post("/api/kill-switch")
async def kill_switch(req: KillSwitchRequest):
    """Pause or resume all proactive heartbeat behavior."""
    from core.scheduler import set_paused
    set_paused(req.paused)
    state = "paused" if req.paused else "resumed"
    await memory.log_action(action_type="admin", action=f"heartbeat_{state}")
    return {"status": state}


@app.get("/api/kill-switch")
async def kill_switch_status():
    from core.scheduler import is_paused
    return {"paused": is_paused()}


# ── Facts (memory inspection) ────────────────────────────────

@app.get("/api/facts")
async def get_facts():
    """Return all durable facts stored in long-term memory."""
    return await memory.get_all_facts()


# ── Static Web UI ────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse("web/index.html")


@app.get("/health")
async def health():
    from core.scheduler import is_paused
    return {"status": "ok", "version": "1.0.0", "heartbeat_paused": is_paused()}
