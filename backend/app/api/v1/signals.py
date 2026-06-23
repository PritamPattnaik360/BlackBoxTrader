from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.db.session import get_db
from app.models.signal import Signal

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
async def list_signals(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Signal).order_by(desc(Signal.created_at)).limit(limit)
    )
    sigs = result.scalars().all()
    return [
        {
            "id": s.id,
            "ticker": s.ticker,
            "composite_score": s.composite_score,
            "confidence": s.confidence,
            "direction": s.direction,
            "source_count": s.source_count,
            "news_score": s.news_score,
            "reddit_score": s.reddit_score,
            "raw_headlines": s.raw_headlines,
            "created_at": str(s.created_at),
        }
        for s in sigs
    ]


@router.post("/scan")
async def trigger_scan(background_tasks: BackgroundTasks):
    from app.tasks.signal_scan import run_signal_scan
    background_tasks.add_task(run_signal_scan)
    return {"status": "scan triggered"}
