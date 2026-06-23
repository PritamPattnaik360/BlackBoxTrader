import asyncio
import logging
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import date
from app.db.session import get_db
from app.models.backtest import BacktestRun, BacktestResult

router = APIRouter(prefix="/backtest", tags=["backtest"])
logger = logging.getLogger(__name__)


class BacktestRequest(BaseModel):
    tickers: list[str]
    start_date: str
    end_date: str
    initial_capital: float = 100_000.0
    strategy_name: str = "nlp_proxy"
    params: dict | None = None


@router.post("")
async def submit_backtest(req: BacktestRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    run = BacktestRun(
        tickers=req.tickers,
        start_date=date.fromisoformat(req.start_date),
        end_date=date.fromisoformat(req.end_date),
        initial_capital=req.initial_capital,
        strategy_name=req.strategy_name,
        params=req.params,
        status="pending",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    background_tasks.add_task(_run_backtest, run.id, req)
    return {"run_id": run.id, "status": "pending"}


@router.get("/{run_id}")
async def get_backtest_result(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    result_row = await db.execute(select(BacktestResult).where(BacktestResult.run_id == run_id))
    result = result_row.scalar_one_or_none()

    return {
        "run_id": run_id,
        "status": run.status,
        "tickers": run.tickers,
        "start_date": str(run.start_date),
        "end_date": str(run.end_date),
        "strategy_name": run.strategy_name,
        "result": {
            "total_return": result.total_return,
            "cagr": result.cagr,
            "sharpe": result.sharpe,
            "sortino": result.sortino,
            "max_drawdown": result.max_drawdown,
            "calmar": result.calmar,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "total_trades": result.total_trades,
            "equity_curve": result.equity_curve,
            "trade_log": result.trade_log,
        } if result else None,
    }


async def _run_backtest(run_id: int, req: BacktestRequest):
    from app.db.session import AsyncSessionLocal
    from app.services.backtester.engine import run_backtest
    from datetime import datetime, timezone

    async with AsyncSessionLocal() as db:
        run = await db.get(BacktestRun, run_id)
        if not run:
            return
        run.status = "running"
        await db.commit()

        try:
            metrics = await asyncio.to_thread(
                run_backtest,
                req.tickers,
                req.start_date,
                req.end_date,
                req.initial_capital,
                req.strategy_name,
                req.params or {},
            )
            result = BacktestResult(
                run_id=run_id,
                total_return=metrics.get("total_return"),
                cagr=metrics.get("cagr"),
                sharpe=metrics.get("sharpe"),
                sortino=metrics.get("sortino"),
                max_drawdown=metrics.get("max_drawdown"),
                calmar=metrics.get("calmar"),
                win_rate=metrics.get("win_rate"),
                profit_factor=metrics.get("profit_factor"),
                total_trades=metrics.get("total_trades"),
                equity_curve=metrics.get("equity_curve"),
                trade_log=metrics.get("trade_log"),
            )
            db.add(result)
            run.status = "done"
            run.completed_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"Backtest {run_id} failed: {e}")
            run.status = "error"

        await db.commit()
