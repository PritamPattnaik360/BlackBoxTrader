from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
from app.db.session import get_db
from app.models.watchlist import Watchlist
from app.services.market_data.feed import add_ticker

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistAdd(BaseModel):
    ticker: str
    asset_type: str = "stock"


@router.get("")
async def get_watchlist(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Watchlist).where(Watchlist.is_active == True))
    return [{"ticker": w.ticker, "asset_type": w.asset_type} for w in result.scalars().all()]


@router.post("")
async def add_to_watchlist(req: WatchlistAdd, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Watchlist).where(Watchlist.ticker == req.ticker.upper()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"{req.ticker} already in watchlist")
    w = Watchlist(ticker=req.ticker.upper(), asset_type=req.asset_type)
    db.add(w)
    await db.commit()
    await add_ticker(req.ticker.upper())
    return {"added": req.ticker.upper()}


@router.delete("/{ticker}")
async def remove_from_watchlist(ticker: str, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Watchlist).where(Watchlist.ticker == ticker.upper()))
    await db.commit()
    return {"removed": ticker.upper()}
