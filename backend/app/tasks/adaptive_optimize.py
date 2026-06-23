"""Scheduled adaptive optimization task — runs every 6 hours."""
import logging
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def run_adaptive_optimize():
    try:
        from app.services.adaptive.adaptive_engine import run_optimization
        async with AsyncSessionLocal() as db:
            await run_optimization(db)
    except Exception as e:
        logger.error(f"Scheduled adaptive optimization failed: {e}")
