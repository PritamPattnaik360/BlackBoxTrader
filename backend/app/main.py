import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import router as v1_router
from app.api.ws.stream import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


_DEFAULT_WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "JPM", "SPY", "QQQ",
]


async def _seed_watchlist_if_empty() -> list[str]:
    """Populate watchlist with a diversified default set if it has no entries."""
    from app.db.session import AsyncSessionLocal
    from app.models.watchlist import Watchlist
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Watchlist).where(Watchlist.is_active == True))
        existing = [w.ticker for w in result.scalars().all()]
        if existing:
            return existing
        for ticker in _DEFAULT_WATCHLIST:
            db.add(Watchlist(ticker=ticker, asset_type="stock", is_active=True))
        await db.commit()
        logger.info(f"Seeded default watchlist: {_DEFAULT_WATCHLIST}")
        return _DEFAULT_WATCHLIST


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("BlackBoxTrader starting...")

    # Run DB migrations
    try:
        import subprocess, sys, os
        backend_dir = os.path.dirname(os.path.dirname(__file__))
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend_dir, check=True, capture_output=True)
        logger.info("Database migrations applied")
    except Exception as e:
        logger.warning(f"Migration failed (may already be current): {e}")

    # Load adaptive learning parameters from DB
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.adaptive.adaptive_engine import load_from_db
        async with AsyncSessionLocal() as db:
            await load_from_db(db)
    except Exception as e:
        logger.warning(f"Adaptive params not loaded (will use defaults): {e}")

    # Seed default watchlist if empty, then start market data stream
    try:
        tickers = await _seed_watchlist_if_empty()
        from app.services.market_data.feed import start_stream
        if tickers:
            await start_stream(tickers)
    except Exception as e:
        logger.warning(f"Market data stream not started: {e}")

    # Auto-enable autonomous paper trading if configured
    from app.config import settings
    if settings.auto_start_autonomous:
        try:
            from app.services.trading_engine.executor import enable_autonomous
            enable_autonomous()
            logger.info("Auto-start: autonomous paper trading ENABLED")
        except Exception as e:
            logger.warning(f"Could not auto-enable autonomous mode: {e}")

    # Start scheduler
    try:
        from app.core.scheduler import start
        start()
    except Exception as e:
        logger.warning(f"Scheduler not started: {e}")

    logger.info("BlackBoxTrader ready")
    yield

    # Shutdown
    from app.core.scheduler import stop
    stop()
    try:
        from app.services.market_data.feed import stop_stream
        await stop_stream()
    except Exception:
        pass
    logger.info("BlackBoxTrader stopped")


app = FastAPI(title="BlackBoxTrader", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    from app.config import settings
    from app.services.trading_engine.executor import is_dry_run
    return {
        "status": "ok",
        "trading_mode": settings.trading_mode,
        "execution": "dry_run" if is_dry_run() else "live",
    }
