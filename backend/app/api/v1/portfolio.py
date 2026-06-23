import asyncio
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.db.session import get_db
from app.models.portfolio import Position, PortfolioSnapshot

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("")
async def get_portfolio():
    """
    Fetch live account + positions from Alpaca.
    The Alpaca SDK is synchronous; we run it in a thread so we never block
    the FastAPI event loop.
    """
    try:
        from app.services.trading_engine.broker import get_account, get_positions
        account, positions = await asyncio.gather(
            asyncio.to_thread(get_account),
            asyncio.to_thread(get_positions),
        )
        return {"account": account, "positions": positions}
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Portfolio fetch error: {e}", exc_info=True)
        return {"account": None, "positions": [], "error": str(e)}


@router.get("/history")
async def get_portfolio_history(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PortfolioSnapshot).order_by(desc(PortfolioSnapshot.recorded_at)).limit(365)
    )
    snaps = result.scalars().all()
    return [
        {
            "ts": str(s.recorded_at),
            "equity": s.equity,
            "day_pnl": s.day_pnl,
            "day_pnl_pct": s.day_pnl_pct,
            "total_pnl": s.total_pnl,
        }
        for s in reversed(snaps)
    ]
