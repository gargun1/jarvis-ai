"""
Jarvis FastAPI application — chat, WebSocket streaming, TradingView webhooks.
"""
import asyncio
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from config.settings import settings
from core.brain import JarvisBrain
from core.memory import memory
from core.scheduler import scheduler
from agents.portfolio import tool_executor

logger = logging.getLogger(__name__)

# One brain per WebSocket session; shared for REST calls
_rest_brain = JarvisBrain(tool_executor=tool_executor)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Jarvis...")
    await memory.connect()
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
    try:
        while True:
            message = await websocket.receive_text()
            async for token in brain.chat_stream(message):
                await websocket.send_text(token)
            await websocket.send_text("[DONE]")
    except WebSocketDisconnect:
        pass


# ── Static Web UI ────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse("web/index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
