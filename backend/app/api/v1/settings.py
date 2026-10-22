from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from app.config import settings
from app.services.risk_manager import portfolio_limits
from app.services.trading_engine import broker as broker_module
from app.services.trading_engine.executor import (
    enable_live_execution, disable_live_execution,
    enable_autonomous, disable_autonomous,
    is_autonomous, is_dry_run,
)

router = APIRouter(prefix="/settings", tags=["settings"])

_ET = ZoneInfo("America/New_York")


def _market_open() -> bool:
    now = datetime.now(_ET)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(9, 30) <= t <= dtime(16, 0)


class ModeSwitch(BaseModel):
    mode: str         # paper | live
    confirm: bool = False
    enable_execution: bool = False


@router.get("/mode")
async def get_mode():
    return {
        "trading_mode":    settings.trading_mode,
        "execution_live":  not is_dry_run(),
        "autonomous":      is_autonomous(),
        "alpaca_base_url": settings.alpaca_base_url,
        "market_open":     _market_open(),
        "auto_start_autonomous": settings.auto_start_autonomous,
        "day_trade_only":  settings.day_trade_only,
        "llm_signal_enabled": settings.llm_signal_enabled,
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
        "market_crash_halt_pct": settings.market_crash_halt_pct,
        "position_max_loss_pct": settings.position_max_loss_pct,
        "option_max_loss_pct": settings.option_max_loss_pct,
        "max_open_positions": settings.max_open_positions,
        "buy_signal_threshold": settings.buy_signal_threshold,
        "sell_signal_threshold": settings.sell_signal_threshold,
    }


class RiskUpdate(BaseModel):
    risk_per_trade_pct: float | None = None
    max_position_pct: float | None = None
    max_drawdown_halt_pct: float | None = Field(None, gt=0, lt=1)
    daily_loss_halt_pct: float | None = Field(None, gt=0, lt=1)
    market_crash_halt_pct: float | None = Field(None, gt=0, lt=1)
    position_max_loss_pct: float | None = Field(None, gt=0, le=1)
    option_max_loss_pct: float | None = Field(None, gt=0, le=1)
    buy_signal_threshold: float | None = None
    sell_signal_threshold: float | None = None


@router.post("/risk")
async def update_risk_settings(req: RiskUpdate):
    for key, value in req.model_dump(exclude_none=True).items():
        setattr(settings, key, value)
    return {"updated": True}


# ── Circuit breaker ───────────────────────────────────────────────────────────

def _current_equity() -> float | None:
    try:
        return broker_module.get_account()["equity"]
    except Exception:
        return None


@router.get("/risk/breaker")
async def get_breaker_status():
    return {**portfolio_limits.status(), "flatten_on_halt": settings.flatten_on_halt}


@router.post("/risk/kill")
async def kill_switch():
    """Halt all new entries now. The risk guard liquidates open positions on its next tick."""
    portfolio_limits.kill()
    return portfolio_limits.status()


@router.post("/risk/resume")
async def resume_trading():
    portfolio_limits.resume(_current_equity())
    return portfolio_limits.status()
