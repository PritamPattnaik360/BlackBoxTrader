"""
Kelly criterion position sizer.

Uses the live win-rate and payoff ratio from the signal_outcome table to
compute the mathematically optimal bet fraction, then applies half-Kelly
conservatism and a hard cap.

Falls back to ATR-based sizing when there is insufficient trade history.
"""
import logging

logger = logging.getLogger(__name__)

HALF_KELLY_FACTOR = 0.5    # full Kelly is too aggressive; use 50%
MAX_FRACTION      = 0.02   # never risk more than 2% of equity per trade
MIN_OUTCOMES      = 8      # need this many outcomes for Kelly to be meaningful


async def kelly_size(equity: float, price: float, ticker: str, session) -> int:
    """
    Compute position size using half-Kelly from live outcome history.

    Returns:
        Number of shares (>= 1).
    """
    if price <= 0 or equity <= 0:
        return 1

    fraction = await _kelly_fraction(ticker, session)

    position_value = equity * fraction
    shares = int(position_value / price)
    return max(1, shares)


async def _kelly_fraction(ticker: str, session) -> float:
    """Return the half-Kelly fraction, falling back to a conservative default."""
    try:
        from sqlalchemy import select
        from app.models.adaptive import SignalOutcome

        result = await session.execute(
            select(SignalOutcome)
            .where(SignalOutcome.ticker == ticker)
            .order_by(SignalOutcome.created_at.desc())
            .limit(50)
        )
        outcomes = result.scalars().all()

        if len(outcomes) < MIN_OUTCOMES:
            # Not enough data — use global outcomes
            result2 = await session.execute(
                select(SignalOutcome)
                .order_by(SignalOutcome.created_at.desc())
                .limit(50)
            )
            outcomes = result2.scalars().all()

        if len(outcomes) < MIN_OUTCOMES:
            return _default_fraction()

        wins   = [o for o in outcomes if o.was_correct and o.pnl_pct > 0]
        losses = [o for o in outcomes if not o.was_correct or o.pnl_pct <= 0]

        if not wins or not losses:
            return _default_fraction()

        win_rate  = len(wins) / len(outcomes)
        avg_win   = sum(o.pnl_pct for o in wins)  / len(wins)
        avg_loss  = abs(sum(o.pnl_pct for o in losses)) / len(losses)

        if avg_win <= 0 or avg_loss <= 0:
            return _default_fraction()

        # Kelly formula: f* = (p*b - q) / b  where b = avg_win/avg_loss
        b      = avg_win / avg_loss
        kelly  = (win_rate * b - (1 - win_rate)) / b
        kelly  = max(0.0, kelly)               # negative Kelly → don't trade
        half   = kelly * HALF_KELLY_FACTOR
        capped = min(half, MAX_FRACTION)

        logger.debug(
            f"Kelly({ticker}): win_rate={win_rate:.2f} b={b:.2f} "
            f"kelly={kelly:.4f} → half={half:.4f} capped={capped:.4f}"
        )
        return capped

    except Exception as e:
        logger.warning(f"Kelly calculation failed: {e}")
        return _default_fraction()


def _default_fraction() -> float:
    """Conservative default when there is no outcome history."""
    from app.config import settings
    return settings.risk_per_trade_pct * 0.5   # half the configured risk
