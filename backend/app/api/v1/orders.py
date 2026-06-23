from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from app.db.session import get_db
from app.models.trade import TradeOrder

router = APIRouter(prefix="/orders", tags=["orders"])


class ManualOrderRequest(BaseModel):
    ticker: str
    side: str  # buy | sell
    qty: float
    order_type: str = "market"  # market | limit | stop
    limit_price: float | None = None
    stop_price: float | None = None


@router.get("")
async def list_orders(limit: int = 100, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TradeOrder).order_by(desc(TradeOrder.submitted_at)).limit(limit)
    )
    orders = result.scalars().all()
    return [
        {
            "id": o.id,
            "alpaca_order_id": o.alpaca_order_id,
            "ticker": o.ticker,
            "side": o.side,
            "order_type": o.order_type,
            "qty": o.qty,
            "status": o.status,
            "filled_qty": o.filled_qty,
            "filled_avg_price": o.filled_avg_price,
            "submitted_at": str(o.submitted_at),
            "filled_at": str(o.filled_at) if o.filled_at else None,
        }
        for o in orders
    ]


@router.post("")
async def place_manual_order(req: ManualOrderRequest, db: AsyncSession = Depends(get_db)):
    try:
        from app.services.trading_engine.broker import submit_market_order
        result = submit_market_order(req.ticker, req.side, req.qty)
        order = TradeOrder(
            alpaca_order_id=result.get("alpaca_order_id"),
            ticker=req.ticker,
            side=req.side,
            order_type=req.order_type,
            qty=req.qty,
            status=result.get("status", "pending"),
        )
        db.add(order)
        await db.commit()
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{order_id}")
async def cancel_order(order_id: str):
    try:
        from app.services.trading_engine.broker import cancel_order
        cancel_order(order_id)
        return {"cancelled": order_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
