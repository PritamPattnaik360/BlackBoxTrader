from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.db.session import get_db
from app.models.portfolio import PortfolioSnapshot
from app.models.trade import TradeOrder

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/performance")
async def get_performance(db: AsyncSession = Depends(get_db)):
    snaps_result = await db.execute(
        select(PortfolioSnapshot).order_by(PortfolioSnapshot.recorded_at).limit(365)
    )
    snaps = snaps_result.scalars().all()

    if not snaps:
        return {"message": "No snapshot data yet"}

    equities = [s.equity for s in snaps]
    initial = equities[0]
    current = equities[-1]
    total_return = (current - initial) / initial if initial > 0 else 0

    # Rolling drawdown
    peak = initial
    max_dd = 0.0
    for e in equities:
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Orders stats
    filled_result = await db.execute(
        select(TradeOrder).where(TradeOrder.status == "filled")
    )
    filled = filled_result.scalars().all()
    total_trades = len(filled)

    return {
        "total_return": round(total_return, 4),
        "max_drawdown": round(-max_dd, 4),
        "total_trades": total_trades,
        "current_equity": current,
        "equity_history": [{"ts": str(s.recorded_at), "value": s.equity} for s in snaps],
    }
