from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.config import settings
from app.services.trading_engine import broker as broker_module
from app.services.trading_engine.executor import (
    enable_live_execution, disable_live_execution,
    enable_autonomous, disable_autonomous,
    is_autonomous, is_dry_run,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class ModeSwitch(BaseModel):
    mode: str         # paper | live
    confirm: bool = False
    enable_execution: bool = False


@router.get("/mode")
async def get_mode():
    return {
        "trading_mode":   settings.trading_mode,
        "execution_live": not is_dry_run(),
        "autonomous":     is_autonomous(),
        "alpaca_base_url": settings.alpaca_base_url,
    }


class AutonomousSwitch(BaseModel):
    enabled: bool
    confirm: bool = False   # required when enabling in live mode


@router.post("/autonomous")
async def set_autonomous(req: AutonomousSwitch):
    """
    Enable or disable autonomous trading.
    Enabling turns off dry-run so paper orders are actually submitted.
    When in live mode, confirm=true is required.
    """
    if req.enabled and settings.trading_mode == "live" and not req.confirm:
        raise HTTPException(
            status_code=400,
            detail="Enabling autonomous mode in LIVE trading requires confirm=true.",
        )
    if req.enabled:
        enable_autonomous()
    else:
        disable_autonomous()
    return {
        "autonomous":     is_autonomous(),
        "execution_live": not is_dry_run(),
        "trading_mode":   settings.trading_mode,
    }


@router.post("/mode")
async def set_mode(req: ModeSwitch):
    if req.mode not in ("paper", "live"):
        raise HTTPException(status_code=400, detail="mode must be 'paper' or 'live'")
    if req.mode == "live" and not req.confirm:
        raise HTTPException(
            status_code=400,
            detail="Switching to live mode requires confirm=true. Real money will be used.",
        )

    settings.trading_mode = req.mode
    broker_module.reset_client()

    if req.enable_execution:
        if req.mode == "live" and not req.confirm:
            raise HTTPException(status_code=400, detail="Cannot enable live execution without confirm=true")
        enable_live_execution()
    else:
        disable_live_execution()

    return {
        "trading_mode": settings.trading_mode,
        "execution_live": req.enable_execution,
        "message": f"Switched to {req.mode} mode",
    }


@router.get("/risk")
async def get_risk_settings():
    return {
        "risk_per_trade_pct": settings.risk_per_trade_pct,
        "max_position_pct": settings.max_position_pct,
        "max_drawdown_halt_pct": settings.max_drawdown_halt_pct,
        "daily_loss_halt_pct": settings.daily_loss_halt_pct,
        "max_open_positions": settings.max_open_positions,
        "buy_signal_threshold": settings.buy_signal_threshold,
        "sell_signal_threshold": settings.sell_signal_threshold,
    }


class RiskUpdate(BaseModel):
    risk_per_trade_pct: float | None = None
    max_position_pct: float | None = None
    buy_signal_threshold: float | None = None
    sell_signal_threshold: float | None = None


@router.post("/risk")
async def update_risk_settings(req: RiskUpdate):
    if req.risk_per_trade_pct is not None:
        settings.risk_per_trade_pct = req.risk_per_trade_pct
    if req.max_position_pct is not None:
        settings.max_position_pct = req.max_position_pct
    if req.buy_signal_threshold is not None:
        settings.buy_signal_threshold = req.buy_signal_threshold
    if req.sell_signal_threshold is not None:
        settings.sell_signal_threshold = req.sell_signal_threshold
    return {"updated": True}
