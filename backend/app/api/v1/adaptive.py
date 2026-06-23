"""
Adaptive learning API — exposes current parameters, evolution history,
performance stats, and manual controls.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.session import get_db
from app.services.adaptive import adaptive_engine

router = APIRouter(prefix="/adaptive", tags=["adaptive"])


@router.get("/params")
async def get_params():
    """Current adaptive parameter values vs defaults."""
    params = []
    for name, default in adaptive_engine.DEFAULTS.items():
        current = adaptive_engine.get_param(name)
        params.append({
            "name": name,
            "current": round(current, 6),
            "default": default,
            "delta": round(current - default, 6),
            "generation": adaptive_engine._current_generation,
        })
    return {
        "params": params,
        "regime": adaptive_engine.get_regime(),
        "generation": adaptive_engine._current_generation,
    }


@router.get("/history")
async def get_history(limit: int = 100, db: AsyncSession = Depends(get_db)):
    """Parameter evolution over generations for charting."""
    from app.models.adaptive import AdaptiveParam

    result = await db.execute(
        select(AdaptiveParam)
        .order_by(AdaptiveParam.generation.desc(), AdaptiveParam.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()

    # Re-shape into generation snapshots: {gen: {param: value, ...}}
    by_gen: dict[int, dict] = {}
    for row in rows:
        gen = row.generation
        if gen not in by_gen:
            by_gen[gen] = {"generation": gen, "created_at": row.created_at.isoformat() if row.created_at else None}
        by_gen[gen][row.name] = row.value

    return sorted(by_gen.values(), key=lambda x: x["generation"])


@router.get("/performance")
async def get_performance(db: AsyncSession = Depends(get_db)):
    """Signal accuracy stats computed from the last 100 outcomes."""
    from app.models.adaptive import SignalOutcome
    import math

    result = await db.execute(
        select(SignalOutcome).order_by(SignalOutcome.created_at.desc()).limit(100)
    )
    outcomes = result.scalars().all()

    if not outcomes:
        return {"total_outcomes": 0, "message": "No outcomes recorded yet"}

    buys  = [o for o in outcomes if o.signal_direction == "BUY"]
    sells = [o for o in outcomes if o.signal_direction == "SELL"]

    def acc(lst):
        return round(sum(1 for o in lst if o.was_correct) / len(lst), 3) if lst else None

    pnls = [o.pnl_pct for o in outcomes]
    mean_pnl = sum(pnls) / len(pnls)
    variance = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
    std_pnl  = math.sqrt(variance) if variance > 0 else 1e-9
    sharpe   = round(mean_pnl / std_pnl, 3)

    return {
        "total_outcomes": len(outcomes),
        "win_rate":       acc(outcomes),
        "buy_accuracy":   acc(buys),
        "sell_accuracy":  acc(sells),
        "recent_sharpe":  sharpe,
        "avg_pnl_pct":    round(mean_pnl, 4),
        "current_regime": adaptive_engine.get_regime(),
    }


@router.get("/events")
async def get_events(limit: int = 30, db: AsyncSession = Depends(get_db)):
    """Recent adaptation events log."""
    from app.models.adaptive import AdaptiveEvent

    result = await db.execute(
        select(AdaptiveEvent)
        .order_by(AdaptiveEvent.created_at.desc())
        .limit(limit)
    )
    events = result.scalars().all()
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "description": e.description,
            "data": e.data,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]


@router.post("/optimize")
async def trigger_optimization(db: AsyncSession = Depends(get_db)):
    """Manually trigger one optimization pass."""
    try:
        await adaptive_engine.run_optimization(db)
        return {"status": "ok", "generation": adaptive_engine._current_generation}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/reset")
async def reset_params(db: AsyncSession = Depends(get_db)):
    """Reset all adaptive parameters back to factory defaults."""
    await adaptive_engine.reset_to_defaults(db)
    return {"status": "ok", "params": adaptive_engine.DEFAULTS}
