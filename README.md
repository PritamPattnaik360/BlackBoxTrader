# BlackBoxTrader

BlackBoxTrader is a self-hosted, full-stack algorithmic trading platform. It scans a
watchlist of stocks, generates buy/sell signals from a blend of technical, quantitative,
and news/sentiment analysis, sizes and manages risk on positions, and can trade
autonomously (paper or live) through Alpaca Markets. A React dashboard exposes signals,
positions, orders, backtests, and an AI advisor chat for the whole system.

> **Trading involves risk.** Live trading is disabled by default (`TRADING_MODE=paper`).
> Only switch to `live` once you've tested thoroughly with paper trading and understand
> the risk settings described below.

## How it works

```
┌─────────────┐      ┌──────────────────────────────────────────────┐      ┌────────────┐
│  Market data│      │                  Backend (FastAPI)            │      │  Frontend  │
│  - Alpaca   │─────▶│  quant_engine  → technical/momentum/mean-rev  │◀────▶│  (React +  │
│  - yfinance │      │  nlp_engine    → news + Reddit + FinBERT       │      │  Vite)     │
│  - News/    │      │  signal_combiner → weighted composite signal  │      │            │
│    Reddit   │      │  risk_manager  → position sizing, stop-loss,  │      │  Dashboard │
└─────────────┘      │                  drawdown/loss halts          │      │  Signals   │
                     │  trading_engine → order execution (Alpaca)    │      │  Portfolio │
                     │  adaptive      → learns from trade outcomes,  │      │  Orders    │
                     │                  tunes signal weights/regime  │      │  Backtest  │
                     │  advisor       → local LLM (Ollama) chat/Q&A  │      │  Settings  │
                     │  backtester    → vectorbt-based strategy test │      │  AI Advisor│
                     └──────────────────────────────────────────────┘      └────────────┘
```

- **Signal generation** (`backend/app/services/quant_engine`): technical indicators
  (RSI, MACD, Bollinger Bands, EMAs via `pandas-ta`), momentum, mean-reversion, trendline,
  and intraday strategies are combined by `signal_combiner.py` into one composite signal
  per ticker, with Kelly-criterion-based position sizing.
- **Sentiment** (`backend/app/services/nlp_engine`): fetches news (NewsAPI/GNews) and
  Reddit posts, scores them with FinBERT (`ProsusAI/finbert`), and aggregates into a
  sentiment score that feeds the composite signal.
- **Risk management** (`backend/app/services/risk_manager`): per-trade risk %, max
  position size, max open positions, portfolio drawdown halt, and daily-loss halt.
- **Trading engine** (`backend/app/services/trading_engine`): places/tracks orders via
  the Alpaca API (stocks + options), can run fully autonomously or in "dry run" mode.
- **Adaptive learning** (`backend/app/services/adaptive`): tracks the outcome of past
  signals, detects market regime, and re-optimizes signal weights over time.
- **AI advisor** (`backend/app/services/advisor`): a chat assistant grounded in your
  live portfolio/signal context, powered by a local Ollama LLM (no cloud API key
  needed) — optionally fine-tuned on your own trade history (`scripts/finetune_llm.py`).
- **Backtester** (`backend/app/services/backtester`): runs the same strategies against
  historical data using `vectorbt`.
- **Scheduler** (`backend/app/core/scheduler.py`, APScheduler): periodically scans for
  signals, syncs the portfolio with the broker, and polls order status.

Data is stored in SQLite by default (no external DB required); Postgres/Redis are
supported as optional upgrades.

## Tech stack

| Layer     | Stack |
|-----------|-------|
| Backend   | Python 3.13, FastAPI, SQLAlchemy (async) + Alembic, APScheduler, `alpaca-py`, `yfinance`, `transformers`/`torch` (FinBERT), `vectorbt`, `pandas`/`numpy`/`scipy`, `PyPortfolioOpt` |
| Frontend  | React 18 + TypeScript, Vite, Tailwind CSS, TanStack Query, Zustand, `lightweight-charts`, `recharts` |
| Database  | SQLite (default, zero-config) or PostgreSQL (`asyncpg`) |
| Cache     | In-memory (default) or Redis, for real-time price streaming |
| AI advisor| [Ollama](https://ollama.com) running locally (e.g. `llama3.2:3b`) — no cloud LLM key required |
| Process mgmt | PM2 (optional, via `ecosystem.config.js`) for running both services as background daemons |

## Prerequisites

- **Python 3.13+**
- **Node.js 18+** and npm
- A free **[Alpaca Markets](https://alpaca.markets)** account (paper trading keys are free)
- Optional: **[Ollama](https://ollama.com/download)** for the AI advisor chat
- Optional: free **[NewsAPI](https://newsapi.org)** / **[GNews](https://gnews.io)** keys for news sentiment
- Optional: Redis (only needed for real-time WebSocket price streaming at scale)

## Setup

### 1. Clone and configure environment

```bash
git clone <this-repo>
cd BlackBoxTrader
cp .env.example backend/.env
```

Edit `backend/.env` and fill in at least your Alpaca paper-trading keys:

```
ALPACA_API_KEY=your_alpaca_api_key_here
ALPACA_SECRET_KEY=your_alpaca_secret_key_here
TRADING_MODE=paper
```

`USE_SQLITE=true` and `USE_REDIS=false` are the safe, zero-install defaults — leave
them as-is unless you want to run Postgres/Redis yourself.

### 2. Backend install

```bash
cd backend
pip install -e ".[dev]"
```

### 3. Frontend install

```bash
cd frontend
npm install
```

### 4. (Optional) FinBERT sentiment model

News/Reddit sentiment scoring needs the FinBERT weights downloaded once (~440MB):

```bash
python scripts/download_finbert.py
```

If you skip this, the app still runs — sentiment scoring is simply degraded/unavailable
until the model is downloaded.

### 5. (Optional) AI advisor (local LLM)

Install [Ollama](https://ollama.com/download), then pull a small model:

```bash
ollama pull llama3.2:3b
```

Ollama runs as a local service on `http://localhost:11434`. If it isn't running, the
advisor chat just returns a friendly "Ollama is not running" message — the rest of the
app is unaffected. You can later fine-tune a custom model on your own trade history
with `python scripts/finetune_llm.py`.

### 6. Database migrations + seed data

```bash
python scripts/bootstrap.py
```

This applies Alembic migrations and seeds a default watchlist
(`AAPL, MSFT, GOOGL, AMZN, NVDA`). The backend also auto-applies migrations and seeds a
broader default watchlist on startup, so this step is optional but recommended for a
clean first run.

## Running it

### Option A — one command (recommended for local dev)

```bash
python scripts/run_dev.py
```

Starts the backend (`uvicorn --reload`, port 8000) and frontend (`vite`, port 5173)
together, and shuts both down cleanly on Ctrl+C.

### Option B — run each service manually

```bash
# Terminal 1 — backend
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# or: start.cmd  (Windows)

# Terminal 2 — frontend
cd frontend
npm run dev
# or: run.cmd  (Windows)
```

### Option C — PM2 (background services, e.g. for always-on paper trading)

```bash
npm install -g pm2
pm2 start ecosystem.config.js
pm2 save        # persist across reboots
pm2 logs        # tail backend.log / frontend.log
pm2 stop all
```

Once running:

- **Frontend UI:** http://localhost:5173
- **Backend API + docs (Swagger):** http://localhost:8000/docs
- **Health check:** http://localhost:8000/health

## Enabling autonomous trading

Autonomous mode is off by default — signals are generated but no orders are placed
(`dry_run`). You can:

- Toggle it on from the **Settings** page in the UI, or
- Set `AUTO_START_AUTONOMOUS=true` in `backend/.env` to enable it automatically on
  backend startup.

Always verify behavior with `TRADING_MODE=paper` before ever considering `live`.

## Configuration reference

All settings live in `backend/.env` (see `.env.example` for the full annotated list) and
are loaded via `backend/app/config.py`. Key risk knobs (all optional, sensible defaults
provided):

| Variable | Default | Meaning |
|---|---|---|
| `RISK_PER_TRADE_PCT` | 0.01 | Fraction of equity risked per trade |
| `MAX_POSITION_PCT` | 0.10 | Max fraction of portfolio in one position |
| `MAX_DRAWDOWN_HALT_PCT` | 0.15 | Halt trading if drawdown from peak exceeds this |
| `DAILY_LOSS_HALT_PCT` | 0.05 | Halt trading if today's P&L falls below this |
| `MAX_OPEN_POSITIONS` | 20 | Cap on concurrent open positions |

## Project layout

```
backend/
  app/
    api/v1/          REST endpoints (portfolio, orders, signals, watchlist, backtest, ...)
    api/ws/           WebSocket streaming endpoints
    core/scheduler.py APScheduler jobs (signal scan, portfolio sync, order polling)
    services/
      quant_engine/   Technical/momentum/mean-reversion/trendline signals, position sizing
      nlp_engine/     News + Reddit fetchers, FinBERT sentiment, aggregation
      risk_manager/   Position sizing, stop-loss, portfolio limits
      trading_engine/ Alpaca broker integration, order executor, options
      adaptive/       Regime detection, performance tracking, parameter optimization
      advisor/        LLM chat advisor (Ollama), context builder, fine-tuning support
      backtester/     vectorbt-based historical strategy backtesting
      market_data/    Alpaca/yfinance clients, caching, live feed
    models/           SQLAlchemy models
    db/migrations/    Alembic migrations
  tests/              Pytest unit tests
frontend/
  src/
    pages/            Dashboard, Signals, Portfolio, Orders, Backtest, Settings
    components/       adaptive/advisor/autonomous panels, layout (sidebar/topbar)
    api/              Typed API client functions per resource
    store/            Zustand global state
    hooks/            useWebSocket for live updates
scripts/
  bootstrap.py        Run migrations + seed watchlist
  run_dev.py           Run backend + frontend together
  download_finbert.py  Download FinBERT model weights
  finetune_llm.py      Fine-tune a local Ollama model on your trade history
```

## Running tests

```bash
cd backend
pytest
```

## Troubleshooting

- **"Migration failed" on startup** — usually harmless if tables already exist; check
  `backend/blackbox.db` was created and re-run `python scripts/bootstrap.py` if unsure.
- **No sentiment scores** — run `python scripts/download_finbert.py` and confirm
  `NEWSAPI_KEY`/`GNEWS_API_KEY` are set.
- **Advisor chat says Ollama isn't running** — install/start Ollama and
  `ollama pull llama3.2:3b`.
- **No live price updates** — this is expected without Redis; the in-memory cache still
  polls on the configured intervals. Set `USE_REDIS=true` with a running Redis instance
  for WebSocket streaming.
