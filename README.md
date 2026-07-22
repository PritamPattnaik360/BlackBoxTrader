# BlackBoxTrader

A full-stack algorithmic trading platform: FinBERT-powered news sentiment, a quantitative signal engine, and automated order execution through Alpaca — with paper trading (fake money) on by default and an explicit, confirmation-gated switch to live trading.

> ⚠️ **Disclaimer:** This is a personal/educational project, not financial advice. Algorithmic trading carries real financial risk. Always start with `TRADING_MODE=paper` and understand the code before ever pointing it at a live account. The author and contributors are not responsible for any financial losses incurred using this software.

## Features

- **Sentiment analysis** — local CPU inference on financial news headlines via [FinBERT](https://huggingface.co/ProsusAI/finbert) (no API calls, no data leaves your machine)
- **Quantitative signal & backtesting engine** — pandas/numpy-based strategy simulation
- **Risk management** — configurable per-trade risk %, max position size, drawdown/daily-loss halts
- **Broker integration** — [Alpaca Markets](https://alpaca.markets) for both paper and live trading (same API, one config flag apart)
- **Adaptive/autonomous trading loop** with a dashboard to monitor signals, positions, and orders in real time
- **React + TypeScript frontend** with live charts, portfolio view, and a "type CONFIRM" safety modal before enabling live trading

## Screenshots

| Dashboard — live signals | Dashboard — portfolio | Settings — autopilot & weights |
|---|---|---|
| ![Dashboard signals feed](docs/screenshots/dashboard-signals.png) | ![Dashboard portfolio value and positions](docs/screenshots/dashboard-portfolio.png) | ![Settings page with autopilot toggle and model weights](docs/screenshots/settings.png) |

The autopilot bot scans the watchlist every 5 minutes during market hours, generates BUY/SELL/HOLD signals from a blended sentiment + quant model, and — when enabled — places paper trades automatically. Everything above is fake money via Alpaca's paper sandbox.

## Tech stack

| Layer      | Tech |
|------------|------|
| Backend    | Python 3.13, FastAPI, SQLAlchemy (async), Alembic |
| Database   | SQLite (default, zero-setup) or PostgreSQL |
| NLP        | HuggingFace Transformers + PyTorch (FinBERT, CPU) |
| Trading    | [alpaca-py](https://github.com/alpacahq/alpaca-py) |
| Frontend   | React 18, TypeScript, Vite, TailwindCSS, TanStack Query, Zustand, Recharts / lightweight-charts |

## Prerequisites

- Python 3.13+
- Node.js 18+ and npm
- A free [Alpaca Markets](https://alpaca.markets) account (paper trading API keys are free and instant)
- (Optional) [NewsAPI](https://newsapi.org) and/or [GNews](https://gnews.io) free API keys for live news sentiment
- (Optional) Redis, only needed for real-time WebSocket price streaming — an in-memory fallback is used otherwise

## Getting started

### 1. Clone the repo

```bash
git clone https://github.com/<your-username>/BlackBoxTrader.git
cd BlackBoxTrader
```

### 2. Configure environment variables

```bash
cp .env.example backend/.env
```

Edit `backend/.env` and fill in at minimum your Alpaca keys:

```
ALPACA_API_KEY=your_alpaca_api_key_here
ALPACA_SECRET_KEY=your_alpaca_secret_key_here
TRADING_MODE=paper
```

Leave `TRADING_MODE=paper` unless you know what you're doing — see [Trading modes](#trading-modes) below.

### 3. Backend setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -e ".[dev]"

# Apply database migrations
alembic upgrade head

# (Optional) download FinBERT model weights for sentiment analysis
python ../scripts/download_finbert.py
```

### 4. Frontend setup

```bash
cd frontend
npm install
```

### 5. Run it

The easiest way — starts both backend and frontend together:

```bash
python scripts/run_dev.py
```

Or run them separately:

```bash
# Backend (from backend/)
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8001

# Frontend (from frontend/)
npm run dev
```

Then open:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8001
- Health check: http://localhost:8001/health

## Trading modes

BlackBoxTrader defaults to **paper trading** (simulated money, real market data) and **dry-run execution** — signals are generated but no orders are placed until you explicitly enable execution.

To switch to live trading (real money), you must explicitly confirm via the API or the Settings page in the UI:

```
POST /api/v1/settings/mode
{ "mode": "live", "confirm": true }
```

The frontend requires typing `CONFIRM` in a modal before this takes effect. Do not enable live mode until you've backtested and understand your strategy's risk profile.

## Project structure

```
BlackBoxTrader/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI routes (REST + WebSocket)
│   │   ├── core/             # config, security, shared utilities
│   │   ├── db/                # SQLAlchemy models & Alembic migrations
│   │   ├── models/           # ORM models
│   │   ├── schemas/           # Pydantic schemas
│   │   ├── services/
│   │   │   ├── adaptive/      # self-tuning strategy logic
│   │   │   ├── advisor/       # trade recommendations
│   │   │   ├── backtester/    # strategy backtesting engine
│   │   │   ├── market_data/   # price/data feeds
│   │   │   ├── nlp_engine/    # FinBERT sentiment pipeline
│   │   │   ├── quant_engine/  # signal generation
│   │   │   ├── risk_manager/  # position sizing & halts
│   │   │   └── trading_engine/# broker integration & order execution
│   │   └── tasks/             # scheduled jobs
│   └── tests/
├── frontend/
│   └── src/
│       ├── api/               # API client
│       ├── components/        # feature-organized React components
│       ├── hooks/, store/, types/
│       └── pages/
├── scripts/                    # dev/setup scripts (run_dev.py, download_finbert.py, ...)
└── ecosystem.config.js         # optional PM2 config for running as background services
```

## Running tests

```bash
cd backend
pytest
```

## Optional: running as a background service (PM2)

For longer-running deployments, an included [PM2](https://pm2.keymetrics.io/) config runs both backend and frontend as managed services:

```bash
npm install -g pm2
pm2 start ecosystem.config.js
pm2 save
```

## Security note

`backend/.env` holds your real API keys/secrets and is git-ignored — never commit it. Use `.env.example` as the template. If you fork this repo, double-check `git status` before pushing to make sure no local `.env` file is accidentally staged.

## License

MIT — see [LICENSE](LICENSE).
