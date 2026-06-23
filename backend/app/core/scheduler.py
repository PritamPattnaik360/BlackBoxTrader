import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config import settings

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


def start():
    from app.tasks.signal_scan import run_signal_scan
    from app.tasks.portfolio_sync import run_portfolio_sync
    from app.tasks.adaptive_optimize import run_adaptive_optimize

    scheduler.add_job(run_signal_scan, "interval", seconds=settings.signal_scan_interval, id="signal_scan", replace_existing=True)
    scheduler.add_job(run_portfolio_sync, "interval", seconds=settings.portfolio_sync_interval, id="portfolio_sync", replace_existing=True)
    # Run a full optimization pass every 6 hours regardless of trade count
    scheduler.add_job(run_adaptive_optimize, "interval", hours=6, id="adaptive_optimize", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started")


def stop():
    if scheduler.running:
        scheduler.shutdown(wait=False)
