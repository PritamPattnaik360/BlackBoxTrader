"""One-shot setup: run DB migrations and seed the watchlist with default symbols."""
import asyncio
import subprocess
import sys
import os

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]


def run_migrations():
    print("Running database migrations...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Migration output: {result.stdout}")
        print(f"Migration error: {result.stderr}")
        # Non-fatal — tables may already exist
    else:
        print("Migrations applied successfully")


async def seed_watchlist():
    sys.path.insert(0, BACKEND_DIR)
    from app.db.session import AsyncSessionLocal, engine
    from app.db.base import Base
    from app.models.watchlist import Watchlist
    from sqlalchemy import select

    # Create tables if migrations haven't run
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        for ticker in DEFAULT_TICKERS:
            existing = await db.execute(select(Watchlist).where(Watchlist.ticker == ticker))
            if not existing.scalar_one_or_none():
                db.add(Watchlist(ticker=ticker, asset_type="stock"))
                print(f"Added {ticker} to watchlist")
            else:
                print(f"{ticker} already in watchlist")
        await db.commit()

    print("\nBootstrap complete!")
    print(f"Default watchlist: {', '.join(DEFAULT_TICKERS)}")
    print("\nNext steps:")
    print("1. Copy .env.example to backend/.env and fill in your API keys")
    print("2. Run: python scripts/run_dev.py")


if __name__ == "__main__":
    os.chdir(BACKEND_DIR)
    run_migrations()
    asyncio.run(seed_watchlist())
