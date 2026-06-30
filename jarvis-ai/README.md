# Jarvis AI

Personal investment and business intelligence assistant. Powered by Claude Sonnet.

**Watches:** IBKR · Binance · Bitget · TradingView  
**Delivers:** Chat · Morning briefing · Voice · Deal pipeline

---

## Quick Start

### 1. Push to GitHub

```bash
cd jarvis-ai
git init
git add .
git commit -m "Initial Jarvis setup"
git remote add origin https://github.com/YOUR_USERNAME/jarvis-ai.git
git push -u origin main
```

> ⚠️ Make sure `.env` is in `.gitignore` — it already is. Never push your `.env`.

---

### 2. Configure

```bash
cp .env.example .env
nano .env   # Fill in your API keys
```

**Required keys to get started:**
- `ANTHROPIC_API_KEY` — get at console.anthropic.com
- At least one broker: `BINANCE_API_KEY` + `BINANCE_API_SECRET`, or Bitget keys

**IBKR:** Requires TWS or IB Gateway running and accepting API connections.  
Set `IBKR_HOST`, `IBKR_PORT` (7496=live, 7497=paper), `IBKR_CLIENT_ID`.

---

### 3. Run Locally (Dev)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Start with Docker (includes Postgres)
docker compose up

# Or run directly (set DATABASE_URL to a local Postgres)
python main.py serve
```

Open `http://localhost:8000`

---

### 4. Deploy to VPS

```bash
# On your VPS (Ubuntu 22.04):
curl -O https://raw.githubusercontent.com/YOUR_USERNAME/jarvis-ai/main/deploy/setup.sh
bash setup.sh

# Then follow the printed instructions to clone, configure, and start
```

Jarvis runs behind nginx on port 80/443. WebSockets are proxied automatically.

---

## Usage

### Web Chat (default)
Open `http://your-vps-ip:8000` — streaming chat UI with quick-action buttons.

### Terminal Chat
```bash
python main.py chat
```

### Voice Mode
```bash
python main.py voice
# Speak → Deepgram transcribes → Claude responds → ElevenLabs reads aloud
```

### Morning Briefing (on-demand)
```bash
python main.py briefing
```
Or hit `GET /api/briefing` — also runs automatically at `BRIEFING_TIME` in `.env`.

### TradingView Webhooks
Point your TradingView alert webhook to:
```
POST http://your-vps-ip/webhook/tradingview
Header: X-Webhook-Secret: <your TRADINGVIEW_WEBHOOK_SECRET>
```
Jarvis will receive the alert, check your positions, and log analysis.

---

## Architecture

```
jarvis-ai/
├── main.py               # CLI entry point (serve / chat / voice / briefing)
├── config/settings.py    # All config from .env
├── core/
│   ├── brain.py          # Claude API + tool-use agentic loop
│   ├── memory.py         # PostgreSQL: snapshots, deals, KPIs
│   └── scheduler.py      # APScheduler: briefings, snapshots
├── connectors/
│   ├── ibkr.py           # Interactive Brokers via ib_insync
│   ├── binance.py        # Binance spot + futures
│   ├── bitget.py         # Bitget spot + futures
│   └── market.py         # Stocks (yfinance) + crypto (CoinGecko)
├── agents/
│   ├── portfolio.py      # Tool executor (routes Claude tool calls → connectors)
│   └── briefing.py       # Daily and weekly briefing generation
├── voice/
│   ├── stt.py            # Deepgram streaming STT
│   └── tts.py            # ElevenLabs TTS
├── api/app.py            # FastAPI: REST + WebSocket + TradingView webhook
├── web/index.html        # Minimal dark-mode chat UI
└── deploy/
    ├── nginx.conf        # Reverse proxy config
    └── setup.sh          # VPS bootstrap script
```

---

## API Keys You'll Need

| Service | URL | Notes |
|---|---|---|
| Anthropic | console.anthropic.com | Required |
| Binance | binance.com/api-management | Read-only is fine |
| Bitget | bitget.com/api-management | Read + passphrase |
| Deepgram | console.deepgram.com | Voice only |
| ElevenLabs | elevenlabs.io | Voice only |
| IBKR | Enable API in TWS settings | Needs local TWS running |

---

## IBKR on VPS

IBKR TWS/Gateway is a desktop app — it needs to run somewhere with a GUI (your local machine or a VPS with VNC). To connect from a headless VPS:

**Option A — Run locally, tunnel to VPS:**
```bash
# On your local machine (run TWS first):
ssh -R 7497:127.0.0.1:7497 user@your-vps-ip
# Set IBKR_HOST=127.0.0.1 in .env on VPS
```

**Option B — IB Gateway on VPS with IBC (headless):**
See [IBC docs](https://github.com/IbcAlpha/IBC) for automated headless IB Gateway.

---

## Extending Jarvis

Add a new data source:
1. Create `connectors/myconnector.py`
2. Add a tool definition in `core/brain.py` → `TOOLS`
3. Route it in `agents/portfolio.py` → `tool_executor`

Add a new scheduled job:
```python
# core/scheduler.py
self.scheduler.add_job(my_async_fn, CronTrigger(hour=10, minute=0), id="my_job")
```
