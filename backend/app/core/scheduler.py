import asyncio
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config import settings

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def _refresh_bias():
    from app.services.strategy import market_bias
    await asyncio.to_thread(market_bias.refresh_bias, True)


def start():
    from app.tasks.signal_scan import run_signal_scan
    from app.tasks.portfolio_sync import run_portfolio_sync
    from app.tasks.adaptive_optimize import run_adaptive_optimize
    from app.tasks.signal_outcome_seeder import run_signal_outcome_seeder
    from app.tasks.day_trade_flatten import run_day_trade_flatten
    from app.services.trading_engine.day_journal import reconcile as reconcile_day_trades

    scheduler.add_job(run_signal_scan, "interval", seconds=settings.signal_scan_interval, id="signal_scan", replace_existing=True)
    scheduler.add_job(run_portfolio_sync, "interval", seconds=settings.portfolio_sync_interval, id="portfolio_sync", replace_existing=True)
    # Run a full optimization pass every 2 hours regardless of trade count
    scheduler.add_job(run_adaptive_optimize, "interval", hours=2, id="adaptive_optimize", replace_existing=True)
    # Convert past signals into LLM training samples every 30 minutes
    scheduler.add_job(run_signal_outcome_seeder, "interval", minutes=30, id="signal_seeder", replace_existing=True)
    # Day trades are never held overnight: flatten at 15:50 ET, retry at 15:56
    scheduler.add_job(run_day_trade_flatten, "cron", day_of_week="mon-fri", hour=15, minute=50,
                      timezone="America/New_York", id="day_trade_flatten", replace_existing=True)
    scheduler.add_job(run_day_trade_flatten, "cron", day_of_week="mon-fri", hour=15, minute=56,
                      timezone="America/New_York", id="day_trade_flatten_retry", replace_existing=True)
    # Close out the day-trade journal (exit price / P&L / reason) and enforce same-day profit-taking
    scheduler.add_job(reconcile_day_trades, "interval", seconds=60, id="day_trade_reconcile", replace_existing=True)
    # Bull/bear bias (SPY trend + VIX) — also computed once at startup
    scheduler.add_job(_refresh_bias, "interval", minutes=30, id="market_bias",
                      replace_existing=True, next_run_time=datetime.now(timezone.utc))
    scheduler.start()
    logger.info("Scheduler started")


def stop():
    if scheduler.running:
        scheduler.shutdown(wait=False)
